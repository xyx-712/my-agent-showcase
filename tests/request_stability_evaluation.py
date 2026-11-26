"""Real API/graph with substitute model, temporary SQLite and fictional input."""
import os
import sqlite3
import tempfile
import time
from unittest.mock import patch
from fastapi.testclient import TestClient
from tests.vector_index_evaluation import setup
from tests.history_summary_evaluation import Model


def run():
    os.environ['MY_AGENT_RAG_ENABLED'] = '0'
    with tempfile.TemporaryDirectory() as directory:
        app, agent, session, _ = setup(directory)
        from src.server import api
        try:
            with TestClient(app, headers={'Origin': 'http://127.0.0.1:5173'}) as client:
                client.post('/session', json={}).raise_for_status()
                def post(message, identity, **extra):
                    return client.post('/chat', json={'message': message, 'request_id': identity, 'mode': 'chat', **extra})
                def state(identity):
                    with session.app_db() as db:
                        return db.execute('SELECT state FROM chat_requests WHERE id=?', (identity,)).fetchone()
                agent.llm = Model()
                assert post('x' * 7000, 'invalid-request').status_code == 422
                assert state('invalid-request') is None
                result = post('先计算100+200，再将结果乘以3。', 'normal-request')
                result.raise_for_status()
                assert '900' in result.json()['answer'], result.text
                before = len(client.get('/history').json()['messages'])
                assert post('先计算100+200，再将结果乘以3。', 'normal-request').json() == result.json()
                assert len(client.get('/history').json()['messages']) == before

                class Slow:
                    calls = 0
                    def invoke(self, messages):
                        self.calls += 1
                        time.sleep(.7)
                        return Model().invoke(messages)
                slow = Slow()
                agent.llm = slow
                with patch.dict(os.environ, MY_AGENT_REQUEST_SECONDS='.5'):
                    result = post('你好，请介绍你自己', 'timeout-request')
                assert result.status_code == 504, result.text
                assert slow.calls == 1, slow.calls
                assert state('timeout-request') == ('timed_out',)
                assert post('你好，请介绍你自己', 'timeout-request').status_code == 504
                assert slow.calls == 1

                with patch.object(api, 'execute_chat', side_effect=RuntimeError('injected')):
                    assert post('虚构请求', 'failure-request').status_code == 500
                assert state('failure-request') == ('failed',)
                with patch.object(api, 'execute_chat', side_effect=AssertionError('must not replay')):
                    assert post('虚构请求', 'failure-request').status_code == 500
                with patch.object(api, 'execute_chat', side_effect=sqlite3.OperationalError('injected disk failure')):
                    assert post('虚构数据库故障', 'database-request').status_code == 503
                assert state('database-request') == ('running',)
                assert post('虚构数据库故障', 'database-request').status_code == 409
                agent.llm = Model()
                post('现在计算2+3', 'after-timeout').raise_for_status()
                with patch.object(api, 'session_user', side_effect=sqlite3.OperationalError('injected auth DB failure')):
                    assert client.get('/history').status_code == 503
                print('PASS API: validation, real graph 300→900, cached replay, model timeout, failure, SQLite uncertainty, subsequent execution')
        finally:
            agent.conn.close()


if __name__ == '__main__':
    run()
