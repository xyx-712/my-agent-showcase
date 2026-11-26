from contextlib import closing
import multiprocessing
from pathlib import Path
import re
import sqlite3
import tempfile
import unittest
from src.server.migrations import migrate_memories
from src.memory.policy import MemoryPolicy
from src.memory.extractor import extract_operations


class Store:
    def __init__(self,path):self.path=path
    def get_conn(self):return sqlite3.connect(self.path,timeout=30)
    def split_values(self,value):return list(dict.fromkeys(v.strip() for v in re.split('[、，,和]',value) if v.strip()))


def concurrent_writer(path,index):
    store=Store(path)
    with closing(store.get_conn()) as db,db:
        db.execute('BEGIN IMMEDIATE');migrate_memories(db)
    policy=MemoryPolicy(store)
    for i in range(5):policy.apply('a',[{'key':'hobby','value':f'worker{index}-value{i}'}])


class MemoryPolicyTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();self.path=Path(self.directory.name)/'memory.db'
        self.store=Store(self.path)
        with closing(self.store.get_conn()) as db,db:
            db.execute('BEGIN IMMEDIATE');migrate_memories(db)
        self.sources={}
        self.policy=MemoryPolicy(self.store,lambda user,identity:self.sources.get((user,identity)))
    def tearDown(self):self.directory.cleanup()
    def row(self,key='name',user='a'):
        with closing(self.store.get_conn()) as db:
            db.row_factory=sqlite3.Row
            value=db.execute('SELECT * FROM memories WHERE user_id=? AND key=?',(user,key)).fetchone()
            return dict(value) if value else None
    def apply(self,value='',key='name',source=None,action='save',intent='statement',user='a',**kwargs):
        text=f'fictional message {source}'
        if source is not None:self.sources[(user,source)]={'role':'user','content':text}
        return self.policy.apply(user,[{'key':key,'value':value,'action':action,'intent':intent}],
            source_id=source,text=text,source_type='user_statement' if source is not None else 'internal',**kwargs)

    def test_legacy_migration_retains_id_and_unknown_metadata(self):
        with closing(self.store.get_conn()) as db,db:
            db.execute('DROP TABLE memories')
            db.execute('CREATE TABLE memories(id INTEGER PRIMARY KEY,user_id TEXT,key TEXT,value TEXT,UNIQUE(user_id,key))')
            db.execute("INSERT INTO memories VALUES(7,'a','name','旧名字')")
            migrate_memories(db);migrate_memories(db)
        row=self.row()
        self.assertEqual((row['id'],row['value'],row['source_type'],row['confirmation_state']),(7,'旧名字','legacy','unknown'))
        self.assertIsNone(row['created_at']);self.assertIsNone(row['source_message_id'])

    def test_migration_failure_rolls_back_and_can_retry(self):
        with closing(self.store.get_conn()) as db,db:
            db.execute('DROP TABLE memories')
            db.execute('CREATE TABLE memories(id INTEGER PRIMARY KEY,user_id TEXT,key TEXT,value TEXT,UNIQUE(user_id,key))')
            db.execute("INSERT INTO memories VALUES(9,'a','name','旧信息')")
        with closing(self.store.get_conn()) as db:
            alters=[]
            def authorize(action,*args):
                if action==sqlite3.SQLITE_ALTER_TABLE:
                    alters.append(action)
                    if len(alters)==2:return sqlite3.SQLITE_DENY
                return sqlite3.SQLITE_OK
            with self.assertRaises(sqlite3.DatabaseError):
                with db:
                    db.execute('BEGIN IMMEDIATE');db.set_authorizer(authorize);migrate_memories(db)
            db.set_authorizer(None)
            self.assertEqual([r[1] for r in db.execute('PRAGMA table_info(memories)')],['id','user_id','key','value'])
            with db:
                db.execute('BEGIN IMMEDIATE');migrate_memories(db)
        self.assertEqual(self.row()['id'],9)
        self.assertEqual(self.row()['value'],'旧信息')

    def test_multi_operation_failure_is_atomic(self):
        with self.assertRaises(ValueError):
            self.policy.apply('a',[{'key':'hobby','value':'足球'},{'key':'name','value':123}])
        self.assertIsNone(self.row('hobby'))

    def test_source_metadata_and_dedup(self):
        self.apply('李四',source=1);first=self.row()
        self.apply('李四',source=2);second=self.row()
        self.assertEqual(first['revision'],second['revision'])
        self.assertEqual(second['last_message_id'],2)
        self.assertEqual(second['source_message_id'],1)
        self.assertEqual(second['confirmation_state'],'user_stated')
        self.assertTrue(second['created_at'] and second['updated_at'])

    def test_conflict_preserves_old_and_correction_resolves(self):
        self.apply('李四',source=1);self.apply('王五',source=2)
        self.assertEqual(self.row()['value'],'李四')
        self.assertEqual(self.row()['status'],'pending_confirmation')
        self.apply('王五',source=3,intent='correction')
        self.assertEqual(self.row()['value'],'王五')
        self.assertEqual(self.row()['confirmation_state'],'user_confirmed')
        with closing(self.store.get_conn()) as db:
            self.assertEqual(db.execute('SELECT status FROM memory_candidates').fetchone()[0],'resolved')

    def test_candidate_never_becomes_active_fact(self):
        self.policy.apply('a',[{'key':'name','value':'候选名字'}],source_type='model_candidate')
        self.assertEqual(self.row()['value'],'')
        self.assertEqual(self.row()['confirmation_state'],'pending')
        with closing(self.store.get_conn()) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM memories WHERE value<>'' AND status IN ('active','pending_confirmation')").fetchone()[0],0)

    def test_resolved_conflict_can_be_raised_by_a_new_message(self):
        self.apply('李四',source=1);self.apply('王五',source=2)
        self.apply('李四',source=3,intent='correction')
        self.apply('王五',source=4)
        self.assertEqual(self.row()['status'],'pending_confirmation')
        with closing(self.store.get_conn()) as db:
            self.assertEqual(db.execute('SELECT source_message_id,status FROM memory_candidates').fetchone(),(4,'pending'))

    def test_model_candidate_does_not_override_user_priority(self):
        self.apply('李四',source=10)
        revision=self.row()['revision']
        self.policy.apply('a',[{'key':'name','value':'李四'}],source_type='model_candidate')
        self.assertEqual(self.row()['revision'],revision)
        self.sources[('a',100)]={'role':'user','content':'model inference input'}
        self.policy.apply('a',[{'key':'name','value':'候选名字'}],source_type='model_candidate',source_id=100,text='model inference input')
        self.assertEqual(self.row()['last_message_id'],10)
        self.apply('王五',source=20,intent='correction')
        self.assertEqual(self.row()['value'],'王五')

    def test_soft_delete_and_stale_source_blocked(self):
        self.apply('李四',source=1)
        self.apply(source=3,action='delete_key')
        self.assertEqual(self.row()['status'],'deleted')
        self.assertEqual(self.row()['value'],'李四')
        self.assertEqual(self.apply('王五',source=2)[0]['status'],'stale_source')
        self.assertEqual(self.apply('李四')[0]['status'],'deleted_barrier')
        self.assertEqual(self.apply('李四',source=4)[0]['status'],'deleted_barrier')
        self.apply('李四',source=5,intent='restore')
        self.assertEqual(self.row()['status'],'active')
        self.apply('王五',source=6,intent='correction')
        self.assertEqual(self.row()['value'],'王五')

    def test_unknown_delete_requires_version_for_restore(self):
        self.apply('李四');self.apply(action='delete_key')
        revision=self.row()['revision']
        self.assertEqual(self.apply('李四',source=4,intent='restore')[0]['status'],'deleted_barrier')
        self.apply('李四',source=5,intent='restore',expected_revision=revision)
        self.assertEqual(self.row()['status'],'active')

    def test_partial_delete_blocks_old_aggregate(self):
        self.apply('足球和苹果',key='hobby',source=1)
        self.apply('苹果',key='hobby',source=2,action='delete')
        self.assertEqual(self.row('hobby')['value'],'足球')
        self.assertEqual(self.apply('足球和苹果',key='hobby')[0]['status'],'deleted_barrier')
        self.apply('香蕉',key='hobby',source=3)
        self.apply('苹果',key='hobby',source=4,intent='restore')
        self.assertEqual(self.row('hobby')['value'],'足球、香蕉、苹果')

    def test_delete_before_delayed_first_insert(self):
        self.apply(source=10,action='delete_key')
        self.apply('旧信息',source=9)
        self.assertEqual(self.row()['status'],'deleted')

    def test_revision_compare_and_source_ownership(self):
        self.apply('李四',source=1)
        self.assertEqual(self.apply('王五',source=2,intent='correction',expected_revision=0)[0]['status'],'stale_revision')
        with self.assertRaises(ValueError):
            self.policy.apply('b',[{'key':'name','value':'李四'}],source_id=1,text='fictional message 1',source_type='user_statement')
        self.assertIsNone(self.row(user='b'))
        with self.assertRaises(ValueError):
            self.policy.apply('a',[{'key':'name','value':'不能确认'}],source_type='user_statement')
        self.sources[('a',99)]={'role':'assistant','content':'assistant output'}
        with self.assertRaises(ValueError):
            self.policy.apply('a',[{'key':'name','value':'模型答案'}],source_id=99,text='assistant output')

    def test_same_message_multiple_operations_and_replay(self):
        self.sources[('a',1)]={'role':'user','content':'message'}
        ops=[{'key':'hobby','value':'苹果'},{'key':'hobby','value':'苹果','action':'delete'},{'key':'hobby','value':'香蕉'}]
        self.policy.apply('a',ops,source_id=1,text='message',source_type='user_statement')
        revision=self.row('hobby')['revision']
        self.policy.apply('a',ops,source_id=1,text='message',source_type='user_statement')
        self.assertEqual(self.row('hobby')['value'],'香蕉')
        self.assertEqual(self.row('hobby')['revision'],revision)

    def test_two_process_merges_and_migrations(self):
        context=multiprocessing.get_context('spawn')
        workers=[context.Process(target=concurrent_writer,args=(str(self.path),i)) for i in range(2)]
        for worker in workers:worker.start()
        for worker in workers:
            worker.join(30)
            if worker.is_alive():worker.terminate();worker.join();self.fail('writer timed out')
            self.assertEqual(worker.exitcode,0)
        self.assertEqual(len(self.store.split_values(self.row('hobby')['value'])),10)

    def test_extraction_gates_and_explicit_updates(self):
        for text in ['他说我叫李四','“我叫李四”','假设我叫李四','请扮演，我是软件工程师','今天我喜欢苹果','附件中的我叫李四','这是引用：我叫李四']:
            self.assertEqual(extract_operations(text),[],text)
        self.assertEqual(extract_operations('更正，我的名字是王五')[0]['intent'],'correction')
        self.assertEqual(extract_operations('重新记住我喜欢苹果')[0]['intent'],'restore')
        self.assertEqual(extract_operations('忘记我的名字')[0]['action'],'delete_key')
        self.assertEqual(extract_operations('我的工作改为产品经理')[0]['value'],'产品经理')
        self.assertEqual(extract_operations('我的职业是医生')[0]['value'],'医生')
        self.assertEqual(extract_operations('不对，我叫王五')[0]['intent'],'correction')
        self.assertEqual(extract_operations('我叫李四明天继续'),[])

    def test_ambiguous_statement_kept_as_candidates(self):
        operations=extract_operations('我叫李四，我叫王五')
        self.assertEqual({op['value'] for op in operations},{'李四','王五'})
        self.assertTrue(all(op['intent']=='candidate' for op in operations))
        self.policy.apply('a',operations)
        self.assertEqual(self.row()['value'],'')
        self.assertEqual(extract_operations('我的职业是医生或者教师')[0]['intent'],'candidate')
