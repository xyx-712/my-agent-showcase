"""Local schema/ownership/context tests. All files and coordination are temporary."""
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from fastapi import HTTPException
from src.server import conversations as chats
from src.server.migrations import migrate_conversations,thread_columns


def legacy(db):
    db.executescript('''
    CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY);
    CREATE TABLE chat_messages(id INTEGER PRIMARY KEY,user_id TEXT,role TEXT,content TEXT);
    INSERT INTO chat_messages VALUES(7,'owner','user','旧消息');
    CREATE TABLE documents(id TEXT PRIMARY KEY,user_id TEXT,name TEXT);
    INSERT INTO documents VALUES('old-file','owner','old.txt');
    CREATE TABLE schedule_tasks(user_id TEXT PRIMARY KEY,state TEXT);
    INSERT INTO schedule_tasks VALUES('owner','{"id":"old-task"}');
    CREATE TABLE agent_tasks(user_id TEXT,id TEXT,state TEXT,PRIMARY KEY(user_id,id));
    INSERT INTO agent_tasks VALUES('owner','old-task','{"id":"old-task"}');
    CREATE TABLE chat_requests(user_id TEXT,id TEXT,fingerprint TEXT,state TEXT,response TEXT,created INTEGER,PRIMARY KEY(user_id,id));
    INSERT INTO chat_requests VALUES('owner','old-request','old-hash','completed','{}',1);
    CREATE TABLE history_summaries(user_id TEXT PRIMARY KEY,revision INTEGER,items TEXT);
    INSERT INTO history_summaries VALUES('owner',4,'[]');
    CREATE TABLE history_summary_revisions(user_id TEXT,revision INTEGER,PRIMARY KEY(user_id,revision));
    INSERT INTO history_summary_revisions VALUES('owner',4);
    ''')


class ConversationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'app.db'
        self.scope=patch('src.server.session.APP_DB',self.path);self.scope.start()
        with closing(sqlite3.connect(self.path)) as db:
            legacy(db)
            with db:
                db.execute('BEGIN IMMEDIATE');migrate_conversations(db)
                for table in ('history_summaries','history_summary_revisions'):thread_columns(db,table)
    def tearDown(self):self.scope.stop();self.temp.cleanup()

    def test_legacy_migration_and_repeat_preserve_every_row(self):
        with closing(sqlite3.connect(self.path)) as db,db:
            migrate_conversations(db)
            self.assertEqual(db.execute('SELECT id,user_id,content,session_id FROM chat_messages').fetchone(),(7,'owner','旧消息',''))
            self.assertEqual(db.execute('SELECT thread_id,user_id,state,session_id FROM schedule_tasks').fetchone(),('owner','owner','{"id":"old-task"}',''))
            self.assertEqual(db.execute('SELECT thread_id,user_id,revision FROM history_summaries').fetchone(),('owner','owner',4))
            self.assertEqual(db.execute('SELECT count(*) FROM conversation_documents').fetchone()[0],1)
            self.assertEqual(db.execute('SELECT fingerprint FROM chat_requests').fetchone()[0],'old-hash')

    def test_default_checkpoint_key_and_new_keys_are_distinct(self):
        original=chats.resolve('owner')
        new=chats.create('owner','新会话')
        with chats.bind('owner',original['id']):self.assertEqual(chats.thread('owner'),'owner');self.assertEqual(chats.storage_session('owner'),'')
        with chats.bind('owner',new['id']):self.assertEqual(chats.thread('owner'),'chat:'+new['id']);self.assertEqual(chats.storage_session('owner'),new['id'])
        self.assertEqual(chats.thread('owner'),'owner')

    def test_owner_validation_and_deleted_session(self):
        new=chats.create('owner','新会话')
        with self.assertRaises(HTTPException) as error:chats.resolve('other',new['id'])
        self.assertEqual(error.exception.status_code,404)
        chats.mark('owner',new['id'],True)
        with self.assertRaises(HTTPException):chats.resolve('owner',new['id'])
        chats.mark('owner',new['id'],False)
        self.assertEqual(chats.resolve('owner',new['id'])['name'],'新会话')

    def test_default_is_not_destructively_deleted(self):
        with self.assertRaises(HTTPException) as error:chats.mark('owner',chats.resolve('owner')['id'],True)
        self.assertEqual(error.exception.status_code,409)

    def test_concurrent_default_creation_is_idempotent(self):
        with ThreadPoolExecutor(2) as pool:values=list(pool.map(chats.resolve,['owner','owner']))
        self.assertEqual(values[0]['id'],values[1]['id'])
        self.assertEqual(len(chats.listing('owner')),1)

    def test_context_restored_on_exception(self):
        one=chats.create('owner','甲');two=chats.create('owner','乙')
        with chats.bind('owner',one['id']):
            with self.assertRaises(RuntimeError):
                with chats.bind('owner',two['id']):raise RuntimeError('test')
            self.assertEqual(chats.thread('owner'),one['thread_id'])

    def test_profile_questions_are_not_new_memory(self):
        from src.memory.extractor import extract_operations
        for text in ('我叫什么','我的名字是什么','我的职业是什么'):
            self.assertEqual(extract_operations(text),[])

    def test_migration_fault_rolls_back_and_can_retry(self):
        fault_path=Path(self.temp.name)/'legacy-fault.db'
        with closing(sqlite3.connect(fault_path)) as db:
            legacy(db)
            def authorizer(action,name,*args):
                return sqlite3.SQLITE_DENY if action==sqlite3.SQLITE_CREATE_TABLE and name=='conversation_documents' else sqlite3.SQLITE_OK
            with self.assertRaises(sqlite3.DatabaseError):
                with db:
                    db.execute('BEGIN IMMEDIATE');db.set_authorizer(authorizer);migrate_conversations(db)
            db.set_authorizer(None)
            self.assertEqual([r[1] for r in db.execute('PRAGMA table_info(schedule_tasks)')],['user_id','state'])
            self.assertEqual(db.execute('SELECT content FROM chat_messages WHERE id=7').fetchone()[0],'旧消息')
            with db:db.execute('BEGIN IMMEDIATE');migrate_conversations(db)
            self.assertEqual(db.execute('SELECT count(*) FROM conversation_documents').fetchone()[0],1)


if __name__=='__main__':unittest.main()
