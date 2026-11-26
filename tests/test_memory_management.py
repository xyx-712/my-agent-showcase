"""Management uses the existing policy, with temporary memory databases only."""
from contextlib import closing
import json
import unittest
from unittest.mock import patch
from fastapi import HTTPException
from tests import test_memory_policy as original
from src.memory import management


class MemoryManagementTests(unittest.TestCase):
    def setUp(self):
        original.MemoryPolicyTests.setUp(self)
        # Settings writes also acquire the existing coordination lease. Keep that
        # auxiliary SQLite file temporary, not just the memory policy database.
        self.session_path=patch('src.server.session.APP_DB',self.path.with_name('app.db'))
        self.session_path.start()
        self.addCleanup(self.session_path.stop)
    tearDown=original.MemoryPolicyTests.tearDown
    row=original.MemoryPolicyTests.row
    apply=original.MemoryPolicyTests.apply

    def manual(self,value='',delete=False,revision=None):
        return self.policy.apply('a',[{'key':'name','value':value,'action':'delete_key' if delete else 'save','intent':'replace'}],
            source_type='user_management',expected_revision=revision or self.row()['revision'],management_floor=20)

    def test_revision_snapshots_and_management_provenance(self):
        self.apply('李四',source=1)
        self.manual('王五')
        row=self.row()
        self.assertEqual((row['value'],row['revision'],row['confirmation_state']),('王五',2,'user_confirmed'))
        self.assertIsNone(row['source_message_id'])
        with closing(self.store.get_conn()) as db:
            versions=[json.loads(r[0]) for r in db.execute('SELECT snapshot FROM memory_revisions ORDER BY revision')]
            self.assertEqual([v['value'] for v in versions],['李四','王五'])
            self.assertEqual(db.execute('SELECT count(*) FROM memory_management_actions').fetchone()[0],1)
        self.assertEqual(management.settings(self.store,'a')['revision'],1)

    def test_stale_edit_rejected_and_old_fact_tombstoned(self):
        self.apply('李四',source=1);self.manual('王五')
        self.assertEqual(self.manual('赵六',revision=1)[0]['status'],'stale_revision')
        self.apply('李四')
        self.assertEqual(self.row()['value'],'王五')
        self.apply('李四',source=10)
        self.assertEqual(self.row()['value'],'王五')

    def test_delete_rejects_edit_and_delayed_replay(self):
        self.apply('李四',source=1);self.manual(delete=True)
        self.assertEqual(self.row()['status'],'deleted')
        self.assertEqual(self.manual('王五')[0]['status'],'not_manageable')
        self.apply('李四');self.apply('王五',source=10)
        self.assertEqual(self.row()['status'],'deleted')

    def test_setting_compare_and_swap_and_isolation(self):
        result=management.set_settings(self.store,'a',False,0)
        self.assertEqual(result,{'automatic_enabled':False,'revision':1})
        self.assertTrue(management.settings(self.store,'b')['automatic_enabled'])
        with self.assertRaises(HTTPException) as error:management.set_settings(self.store,'a',True,0)
        self.assertEqual(error.exception.status_code,409)
        self.assertTrue(management.set_settings(self.store,'a',True,1)['automatic_enabled'])

    def test_paused_and_delayed_generation_cannot_write(self):
        management.set_settings(self.store,'a',False,0)
        self.assertEqual(self.apply('李四',automatic=True,generation=1)[0]['status'],'automatic_paused')
        management.set_settings(self.store,'a',True,1)
        for generation in (None,0,1):
            self.assertEqual(self.apply('李四',automatic=True,generation=generation)[0]['status'],'stale_generation')
        self.apply('李四',automatic=True,generation=2)
        self.assertEqual(self.row()['value'],'李四')

    def test_manual_edit_fences_inflight_extraction(self):
        self.apply('李四');self.manual('王五')
        self.assertEqual(self.apply('赵六',automatic=True,generation=0)[0]['status'],'stale_generation')
        self.assertEqual(self.row()['value'],'王五')

    def test_management_ownership(self):
        self.apply('李四')
        with self.assertRaises(HTTPException) as error:management.owned(self.store,'b',self.row()['id'])
        self.assertEqual(error.exception.status_code,404)
        self.assertEqual(management.listing(self.store,'b')['items'],[])

    def test_manual_requires_server_boundary_and_revision(self):
        self.apply('李四')
        for kwargs in ({},{'expected_revision':1},{'expected_revision':1,'management_floor':-1}):
            with self.assertRaises(ValueError):
                self.policy.apply('a',[{'key':'name','value':'王五'}],source_type='user_management',**kwargs)

    def test_partial_replace_does_not_resurrect_removed_values(self):
        self.apply('篮球、苹果',key='hobby')
        self.policy.apply('a',[{'key':'hobby','value':'篮球','intent':'replace'}],source_type='user_management',expected_revision=1,management_floor=20)
        self.apply('苹果',key='hobby')
        self.assertEqual(self.row('hobby')['value'],'篮球')
        self.policy.apply('a',[{'key':'hobby','value':'篮球、苹果','intent':'replace'}],source_type='user_management',expected_revision=2,management_floor=20)
        self.assertEqual(self.row('hobby')['value'],'篮球、苹果')

    def test_migration_backfills_only_available_revision_idempotently(self):
        from src.server.migrations import migrate_memories
        self.apply('李四');self.manual('王五')
        with closing(self.store.get_conn()) as db,db:
            db.execute('DELETE FROM memory_revisions')
            migrate_memories(db);migrate_memories(db)
            rows=db.execute('SELECT revision,snapshot FROM memory_revisions').fetchall()
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0][0],2)
        self.assertEqual(json.loads(rows[0][1])['value'],'王五')

    def test_manual_edit_works_while_automatic_paused(self):
        self.apply('李四')
        management.set_settings(self.store,'a',False,0)
        self.manual('王五')
        self.assertEqual(self.row()['value'],'王五')
        self.assertEqual(management.settings(self.store,'a'),{'automatic_enabled':False,'revision':2})


if __name__=='__main__':unittest.main()
