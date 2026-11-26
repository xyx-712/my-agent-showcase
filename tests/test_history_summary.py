"""Temporary SQLite only, substitute model, no user history or Ollama required."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch
from langchain_core.messages import AIMessage,HumanMessage
from src.agent import history_summary as summary


class SummaryModel:
    def __init__(self):self.calls=[];self.bad=False;self.unknown=False;self.assistant=False
    def invoke(self,messages):
        data=json.loads(messages[-1].content);self.calls.append(data)
        if self.bad:return AIMessage(content='not-json')
        items=list(data['previous'])
        for group in data['turns']:
            message=group[-1] if self.assistant else group[0]
            if '项目' in message['content'] or '更正' in message['content']:
                items.append({'kind':'background','source_id':999999 if self.unknown else message['id'],'quote':message['content'][:100]})
        return AIMessage(content=json.dumps({'items':items[-5:]},ensure_ascii=False))


class HistorySummaryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'app.db'
        self.patches=[patch('src.server.session.APP_DB',self.path),patch.object(summary,'memory_revision',return_value=0),
            patch.dict('os.environ',{'MY_AGENT_SUMMARY_MIN_TURNS':'2','MY_AGENT_SUMMARY_BATCH_TURNS':'2','MY_AGENT_SUMMARY_TOKENS':'640','MY_AGENT_SUMMARY_RETRY_SECONDS':'1'})]
        for item in self.patches:item.start()
        from src.server.migrations import migrate_sessions,migrate_history,migrate_history_summaries
        with closing(sqlite3.connect(self.path)) as db,db:
            migrate_sessions(db);migrate_history(db,None);migrate_history_summaries(db);migrate_history_summaries(db)
        self.model=SummaryModel()
    def tearDown(self):
        for item in reversed(self.patches):item.stop()
        self.temp.cleanup()
    def message(self,text,role='user',user='a'):
        from src.server.history import save_history
        return save_history(user,role,text)
    def turn(self,text,user='a'):
        identity=self.message(text,user=user);self.message('已收到',role='assistant',user=user);return identity
    def update(self,text='继续',force=False,user='a'):
        current=self.message(text,user=user)
        return summary.update(user,self.model,current,current,text,force)
    def state(self):
        with closing(sqlite3.connect(self.path)) as db:return summary.row(db,'a')
    def retry(self):
        with closing(sqlite3.connect(self.path)) as db,db:db.execute('UPDATE history_summaries SET retry_at=0')

    def test_short_dialogue_needs_no_model(self):
        self.turn('项目叫青禾');self.assertIsNone(self.update());self.assertEqual(self.model.calls,[])

    def test_only_complete_turns_and_real_ranges(self):
        start=self.turn('项目青禾禁止删除任何文件。');self.turn('项目采用本地部署。')
        incomplete=self.message('项目仍未收到回复')
        result=self.update()
        self.assertEqual((result['start_id'],result['end_id']),(start,incomplete-1))
        self.assertTrue(all(any(m['role']=='assistant' for m in group) for group in self.model.calls[0]['turns']))
        self.assertEqual(result['revision'],1)
        self.assertNotIn(incomplete,[m['source_id'] for m in result['items']])

    def test_incremental_does_not_resummarize_committed_range(self):
        self.turn('项目青禾');self.turn('项目里程碑待确认');first=self.update()
        self.turn('项目新增离线验收');self.turn('项目保留备份');second=self.update()
        self.assertEqual(second['revision'],2)
        self.assertEqual(self.model.calls[1]['previous'],first['items'])
        self.assertTrue(all(m['id']>first['end_id'] for g in self.model.calls[1]['turns'] for m in g))
        self.assertTrue(second['created_at'])

    def test_invalid_source_has_two_attempts_and_failure_fallback(self):
        self.turn('项目青禾');self.turn('项目不用云端');self.model.unknown=True
        self.assertIsNone(self.update());self.assertEqual(len(self.model.calls),2)
        self.assertEqual(self.state()['status'],'FAILED');self.assertEqual(self.state()['end_id'],0)

    def test_retry_and_resume_without_repeating_finished_batch(self):
        self.turn('项目青禾');self.turn('项目离线');self.model.bad=True
        self.assertIsNone(self.update());self.model.bad=False;self.retry()
        recovered=self.update();self.assertEqual(recovered['revision'],1)
        self.assertEqual(summary.load('a'),recovered)
        self.assertIsNone(summary.live('b',recovered))

    def test_abandoned_indexing_lease_is_recovered(self):
        self.turn('项目青禾');self.turn('项目离线');self.update()
        self.turn('项目增加验收');self.turn('项目暂停发布')
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute("UPDATE history_summaries SET status='INDEXING',worker_token='dead',lease_until=0")
        self.assertEqual(self.update()['revision'],2)

    def test_live_lease_prevents_duplicate_model_calls(self):
        self.turn('项目青禾');self.turn('项目本地')
        current=self.message('继续');entered=threading.Event();release=threading.Event()
        original=self.model.invoke
        def slow(messages):entered.set();release.wait(5);return original(messages)
        self.model.invoke=slow
        worker=threading.Thread(target=summary.update,args=('a',self.model,current,current,'继续'))
        worker.start();self.assertTrue(entered.wait(5))
        self.assertIsNone(summary.update('a',self.model,current,current,'继续'))
        release.set();worker.join(10);self.assertFalse(worker.is_alive())
        self.assertEqual(len(self.model.calls),1);self.assertEqual(self.state()['revision'],1)

    def test_current_correction_invalidates_old_reference(self):
        self.turn('项目采用旧日期');self.turn('项目要求离线');old=self.update()
        self.assertIsNone(self.update('更正，项目改为新日期。'))
        self.assertIsNone(summary.live('a',old));self.assertEqual(self.state()['status'],'INVALIDATED')
        self.message('确认',role='assistant');self.turn('项目继续保留本地验收')
        corrected=self.update()
        self.assertNotIn('旧日期',json.dumps(corrected,ensure_ascii=False))

    def test_memory_management_epoch_and_deletion_barrier(self):
        self.turn('项目青禾');self.turn('项目本地');old=self.update()
        with patch.object(summary,'memory_revision',return_value=1):
            self.assertIsNone(summary.live('a',old));self.assertIsNone(self.update('忘记我的名字'))
            self.assertEqual(self.state()['items'],'[]')
            self.assertGreater(self.state()['floor_id'],old['end_id'])

    def test_summary_never_saves_assistant_as_fact(self):
        self.turn('项目青禾');self.message('项目本地');self.message('项目已经全部完成',role='assistant')
        self.model.assistant=True
        self.assertIsNone(self.update());self.assertEqual(self.state()['status'],'FAILED')

    def test_negative_condition_must_not_be_cut_off(self):
        with self.assertRaises(ValueError):summary._validate([{'source_id':1,'quote':'删除任何文件'}],{1:{'role':'user','content':'不能删除任何文件。'}},640)
        with self.assertRaises(ValueError):summary._validate([{'source_id':1,'quote':'删除任何文件。项目本地'}],{1:{'role':'user','content':'不能删除任何文件。项目本地。'}},640)

    def test_context_budget_and_current_once(self):
        from src.agent.context import chat,cost,budget
        value={'items':[{'kind':'constraint','source_id':1,'quote':'禁止删除文件'}],'revision':1,'start_id':1,'end_id':2}
        result=chat([HumanMessage(content='当前问题')],history_summary=value)
        self.assertEqual(sum(m.content=='当前问题' for m in result),1)
        self.assertIn('禁止删除文件',result[1].content)
        self.assertLessEqual(cost(result),budget().available)

    def test_original_history_is_never_modified(self):
        self.turn('项目青禾');self.turn('项目本地')
        with closing(sqlite3.connect(self.path)) as db:before=db.execute('SELECT * FROM chat_messages').fetchall()
        self.update()
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT * FROM chat_messages WHERE id<=?',(before[-1][0],)).fetchall(),before)
            self.assertEqual(db.execute('SELECT count(*) FROM history_summary_revisions').fetchone()[0],1)

    def test_oversized_legacy_turn_falls_back_without_prefix_summary(self):
        self.turn('项目'+('legacy '*5000));self.turn('项目本地')
        self.assertIsNone(self.update())
        self.assertEqual(self.model.calls,[])
        self.assertEqual((self.state()['status'],self.state()['end_id']),('FAILED',0))

    def test_retry_is_bounded_and_explicit_command_can_reset(self):
        self.turn('项目青禾');self.turn('项目本地');self.model.bad=True
        for _ in range(3):self.retry();self.assertIsNone(self.update())
        count=len(self.model.calls);self.retry();self.update()
        self.assertEqual(len(self.model.calls),count)
        self.model.bad=False
        self.assertEqual(self.update(force=True)['revision'],1)

    def test_epoch_changed_during_generation_prevents_publication(self):
        self.turn('项目青禾');self.turn('项目本地')
        epoch=[0]
        original=self.model.invoke
        def changed(messages):
            output=original(messages);epoch[0]=1;return output
        self.model.invoke=changed
        with patch.object(summary,'memory_revision',side_effect=lambda user:epoch[0]):
            self.assertIsNone(self.update())
            self.assertEqual(self.state()['status'],'FAILED')

    def test_other_users_source_id_is_not_accepted(self):
        foreign=self.turn('项目属于另一账号',user='b')
        self.turn('项目青禾');self.turn('项目本地')
        def malicious(messages):
            return AIMessage(content=json.dumps({'items':[{'kind':'background','source_id':foreign,'quote':'项目属于另一账号'}]}))
        self.model.invoke=malicious
        self.assertIsNone(self.update())
        self.assertEqual(self.state()['revision'],0)

    def test_legacy_backlog_correction_beyond_first_batch_is_seen(self):
        self.turn('项目旧名为青禾')
        for _ in range(110):self.turn('闲聊')
        self.turn('更正，项目改名为白榆。');self.turn('项目仍然离线部署')
        result=self.update()
        self.assertIsNotNone(result)
        self.assertNotIn('青禾',json.dumps(result,ensure_ascii=False))
        self.assertIn('白榆',json.dumps(result,ensure_ascii=False))


if __name__=='__main__':unittest.main()
