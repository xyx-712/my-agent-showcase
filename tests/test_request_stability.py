"""Deadline and replay invariants with fictional data and a temporary database."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager, closing
from pathlib import Path
import sqlite3
import tempfile
from threading import Event
import unittest
from unittest.mock import Mock, patch

from fastapi import HTTPException
from src.agent import execution
from src.server import request_log


class RequestStabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'requests.db'
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY)')
        @contextmanager
        def database():
            db = sqlite3.connect(self.path, timeout=2)
            try:
                with db:
                    yield db
            finally:
                db.close()
        self.database = database
        self.scope = patch.object(request_log, 'app_db', database)
        self.scope.start()
        request_log.init_requests()
        self.response = {'answer': 'fictional result', 'task': {}}

    def tearDown(self):
        self.scope.stop()
        self.temp.cleanup()

    def state(self, user='owner', identity='request'):
        with self.database() as db:
            return db.execute('SELECT state FROM chat_requests WHERE user_id=? AND id=?', (user, identity)).fetchone()[0]

    def run_request(self, callback, user='owner', identity='request', payload='fictional'):
        return request_log.run(user, identity, payload, callback)

    def test_completed_replay_and_conflicting_payload(self):
        callback = Mock(return_value=self.response)
        self.assertEqual(self.run_request(callback), self.response)
        self.assertEqual(self.run_request(callback), self.response)
        self.assertEqual(callback.call_count, 1)
        with self.assertRaises(HTTPException):
            self.run_request(callback, payload='changed')

    def test_failure_is_final_only_after_execution_unwinds(self):
        def fail():
            self.assertEqual(self.state(), 'running')
            raise RuntimeError('private failure')
        for callback in (fail, Mock(side_effect=AssertionError('must not replay'))):
            with self.assertRaises(HTTPException) as error:
                self.run_request(callback)
            self.assertEqual(error.exception.status_code, 500)
            self.assertNotIn('private', str(error.exception.detail))
        self.assertEqual(self.state(), 'failed')

    def test_waiting_response_is_cached_and_new_continuation_is_allowed(self):
        result = {'answer': '补充条件', 'task': {'status': 'waiting'}}
        callback = Mock(return_value=result)
        self.run_request(callback)
        self.assertEqual(self.state(), 'recoverable')
        self.assertEqual(self.run_request(callback), result)
        self.assertEqual(callback.call_count, 1)
        self.run_request(callback, identity='continuation')
        self.assertEqual(callback.call_count, 2)

    def test_database_execution_failure_keeps_running(self):
        with self.assertRaises(HTTPException) as error:
            self.run_request(Mock(side_effect=sqlite3.OperationalError('locked')))
        self.assertEqual(error.exception.status_code, 503)
        self.assertEqual(self.state(), 'running')
        callback = Mock()
        with self.assertRaises(HTTPException):
            self.run_request(callback)
        callback.assert_not_called()

    def test_final_result_storage_failure_does_not_reexecute(self):
        with patch.object(request_log, 'complete', side_effect=sqlite3.OperationalError('disk')):
            with self.assertRaises(HTTPException):
                self.run_request(lambda: self.response)
        self.assertEqual(self.state(), 'running')
        with self.assertRaises(HTTPException):
            self.run_request(Mock(side_effect=AssertionError('replayed')))

    def test_failure_storage_failure_keeps_running(self):
        with patch.object(request_log, 'fail', side_effect=sqlite3.OperationalError('disk')):
            with self.assertRaises(HTTPException) as error:
                self.run_request(Mock(side_effect=RuntimeError('failed')))
        self.assertEqual(error.exception.status_code, 503)
        self.assertEqual(self.state(), 'running')

    def test_begin_storage_failure_never_starts_execution(self):
        callback = Mock()
        with patch.object(request_log, 'begin', side_effect=sqlite3.OperationalError('disk')):
            with self.assertRaises(HTTPException):
                self.run_request(callback)
        callback.assert_not_called()

    def test_blocked_model_is_not_abandoned_or_replayed(self):
        entered, release = Event(), Event()
        clock = Mock()
        clock.monotonic.return_value = 0
        def invoke(messages):
            entered.set()
            if not release.wait(5):
                raise AssertionError('test release missing')
            clock.monotonic.return_value = 2
            return 'late result'
        model = Mock(invoke=Mock(side_effect=invoke))
        following = Mock()
        def execute():
            execution.invoke_model(model, [])
            following()
            return self.response
        with patch.object(execution, 'time', clock), patch.dict('os.environ', MY_AGENT_REQUEST_SECONDS='1'):
            with ThreadPoolExecutor(1) as pool:
                future = pool.submit(self.run_request, execute)
                try:
                    self.assertTrue(entered.wait(3))
                    self.assertFalse(future.done())
                    self.assertEqual(self.state(), 'running')
                    with self.assertRaises(HTTPException) as error:
                        self.run_request(Mock(side_effect=AssertionError('duplicate')))
                    self.assertEqual(error.exception.status_code, 409)
                finally:
                    release.set()
                with self.assertRaises(HTTPException) as error:
                    future.result(timeout=3)
                self.assertEqual(error.exception.status_code, 504)
        self.assertEqual(self.state(), 'timed_out')
        following.assert_not_called()
        model.invoke.assert_called_once()
        self.assertIsNone(execution.deadline.get())
        with self.assertRaises(HTTPException) as error:
            self.run_request(Mock(side_effect=AssertionError('replayed timeout')))
        self.assertEqual(error.exception.status_code, 504)

    def test_same_budget_is_shared_by_nested_workflows(self):
        clock = Mock()
        clock.monotonic.return_value = 0
        with patch.object(execution, 'time', clock), patch.dict('os.environ', MY_AGENT_REQUEST_SECONDS='1'):
            with execution.request_budget():
                end = execution.deadline.get()
                with execution.request_budget():
                    self.assertEqual(execution.deadline.get(), end)
                clock.monotonic.return_value = 2
                with self.assertRaises(execution.RequestTimeout):
                    execution.budgeted_step(Mock())({})
                clock.monotonic.return_value = 0

    def test_graph_preserves_completed_step_before_next_step_timeout(self):
        from langgraph.graph import StateGraph, START, END
        from langgraph.checkpoint.memory import InMemorySaver
        clock = Mock()
        clock.monotonic.return_value = 0
        def first(state):
            clock.monotonic.return_value = 2
            return {'completed': 'real tool result'}
        second = Mock(return_value={})
        builder = StateGraph(dict)
        builder.add_node('first', execution.budgeted_step(first))
        builder.add_node('second', execution.budgeted_step(second))
        builder.add_edge(START, 'first'); builder.add_edge('first', 'second'); builder.add_edge('second', END)
        graph = builder.compile(checkpointer=InMemorySaver())
        config = {'configurable': {'thread_id': 'fictional'}}
        with patch.object(execution, 'time', clock), patch.dict('os.environ', MY_AGENT_REQUEST_SECONDS='1'):
            with self.assertRaises(execution.RequestTimeout):
                with execution.request_budget():
                    graph.invoke({}, config)
        self.assertEqual(graph.get_state(config).values['completed'], 'real tool result')
        second.assert_not_called()

    def test_timeout_recovery_keeps_latest_document_evidence(self):
        from src.agent import document_agent
        latest = {'id': 'fictional-task', 'sources': ['durable evidence'], 'result': 15, 'status': 'running'}
        with patch.object(document_agent, 'step', side_effect=execution.RequestTimeout()), \
             patch.object(document_agent, 'load_task', return_value=latest), \
             patch.object(document_agent, 'save_task') as save:
            with self.assertRaises(execution.RequestTimeout):
                document_agent.counted_step({'user_id': 'owner', 'task': {'id': latest['id']}})
        self.assertEqual(save.call_args.args[1], {**latest, 'status': 'waiting', 'pending': 'continue'})

    def test_expired_budget_never_starts_model(self):
        model = Mock()
        token = execution.deadline.set(-1)
        try:
            with self.assertRaises(execution.RequestTimeout):
                execution.invoke_model(model, [])
        finally:
            execution.deadline.reset(token)
        model.invoke.assert_not_called()

    def test_document_database_failure_does_not_attempt_cleanup_write(self):
        from src.agent import document_agent
        with patch.object(document_agent, 'step', side_effect=sqlite3.OperationalError('disk')), \
             patch.object(document_agent, 'load_task') as load, patch.object(document_agent, 'save_task') as save:
            with self.assertRaises(sqlite3.Error):
                document_agent.counted_step({'user_id': 'owner', 'task': {'id': 'fictional'}})
        load.assert_not_called()
        save.assert_not_called()

    def test_late_timeout_does_not_downgrade_completed_document_task(self):
        from src.agent import document_agent
        latest = {'id': 'fictional', 'status': 'completed', 'result': 15}
        with patch.object(document_agent, 'step', side_effect=execution.RequestTimeout()), \
             patch.object(document_agent, 'load_task', return_value=latest), patch.object(document_agent, 'save_task') as save:
            with self.assertRaises(execution.RequestTimeout):
                document_agent.counted_step({'user_id': 'owner', 'task': {'id': 'fictional'}})
        save.assert_not_called()

    def test_owner_isolation(self):
        self.run_request(lambda: self.response)
        self.run_request(lambda: {'answer': 'other'}, user='other')
        self.assertEqual(self.state('owner'), 'completed')
        self.assertEqual(self.state('other'), 'completed')

    def test_legacy_running_is_not_unsafely_reclaimed(self):
        request_log.begin('owner', 'request', 'fictional')
        request_log.init_requests()
        callback = Mock()
        with self.assertRaises(HTTPException) as error:
            self.run_request(callback)
        self.assertEqual(error.exception.status_code, 409)
        callback.assert_not_called()
