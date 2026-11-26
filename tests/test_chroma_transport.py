import sqlite3
import unittest
from unittest.mock import Mock, patch
from urllib.parse import urlsplit
import httpx
from src.retrieval.chroma_http import http_client


class TransportTests(unittest.TestCase):
    def test_storage_switch_invalidates_index_key(self):
        from src.retrieval.embeddings import IndexSettings
        with patch.dict('os.environ',{'MY_AGENT_CHROMA_URL':'http://127.0.0.1:8002'}):
            server=IndexSettings().key
        with patch.dict('os.environ',{'MY_AGENT_CHROMA_URL':'http://127.0.0.1:8003'}):
            self.assertNotEqual(server,IndexSettings().key)
    def test_unavailable_server_is_bounded_before_discovery(self):
        with patch('src.retrieval.chroma_http.httpx.get',side_effect=httpx.ConnectError('offline')) as request, \
             patch('src.retrieval.chroma_http.chromadb.HttpClient') as construct:
            with self.assertRaises(httpx.ConnectError):http_client(urlsplit('http://127.0.0.1:8002'))
            self.assertEqual(request.call_args.kwargs['timeout'],10)
            construct.assert_not_called()

    def test_http_calls_have_timeout(self):
        with patch('src.retrieval.chroma_http.httpx.get'), \
             patch('src.retrieval.chroma_http.chromadb.HttpClient') as construct:
            result=http_client(urlsplit('http://127.0.0.1:8002'))
            self.assertEqual(result._server._session.timeout.read,10)
            self.assertEqual(construct.call_args.kwargs['port'],8002)

    def test_sqlite_failure_cannot_generate_uncited_answer(self):
        from src.retrieval.qa import answer
        service=Mock();service.search.side_effect=sqlite3.OperationalError('injected SQLite read failure')
        model=Mock()
        with self.assertRaises(sqlite3.OperationalError):answer('owner','question',['file'],model,service)
        model.invoke.assert_not_called()
