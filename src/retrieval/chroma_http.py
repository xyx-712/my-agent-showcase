"""Bounded HTTP transport adapter for pinned chromadb 1.5.9."""
import httpx
import chromadb
from chromadb.config import Settings


def http_client(url):
    # Preflight avoids entering upstream discovery against an unavailable server.
    # Upstream constructor discovery itself has no supported timeout option.
    httpx.get(url.geturl().rstrip('/')+'/api/v2/heartbeat',timeout=10).raise_for_status()
    client = chromadb.HttpClient(host=url.hostname,port=url.port or (443 if url.scheme=='https' else 8000),
                                ssl=url.scheme=='https',settings=Settings(anonymized_telemetry=False))
    client._server._session.timeout=httpx.Timeout(10)
    return client
