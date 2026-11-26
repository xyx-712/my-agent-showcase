"""Chroma adapter: embedded single-worker or explicitly configured shared server."""
import hashlib
import json
import os
from urllib.parse import urlsplit


def index_path():
    from src.server import session
    from pathlib import Path
    configured = os.environ.get("MY_AGENT_CHROMA_DIR")
    return (Path(configured) if configured else session.APP_DB.with_name(session.APP_DB.stem + "_chroma")).resolve()


def collection_name(owner, key, revision):
    return "rag_" + hashlib.sha256(json.dumps([owner, key, revision]).encode()).hexdigest()[:48]


class VectorStore:
    def __init__(self, owner, key, revision, embeddings):
        from langchain_chroma import Chroma
        from chromadb.config import Settings
        self.collection = collection_name(owner, key, revision)
        server = os.environ.get("MY_AGENT_CHROMA_URL", "")
        options = {"collection_name": self.collection, "embedding_function": embeddings,
                   "collection_metadata": {"hnsw:space": "cosine"}, "client_settings": Settings(anonymized_telemetry=False)}
        if server:
            import chromadb
            url = urlsplit(server)
            if url.scheme not in {"http", "https"} or not url.hostname or url.path not in {"", "/"} or url.username or url.password or url.query or url.fragment:
                raise ValueError("MY_AGENT_CHROMA_URL需为服务地址")
            from src.retrieval.chroma_http import http_client
            options['client'] = http_client(url)
        else:
            from src.server.coordination import connection
            import time
            db = connection()
            try:
                if db.execute("SELECT count(*) FROM workers WHERE expires>?", (time.time(),)).fetchone()[0] > 1:
                    raise ValueError("嵌入式Chroma仅支持单Worker；请停用索引或配置共享Chroma Server")
            finally:
                db.close()
            options["persist_directory"] = str(index_path())
        self.store = Chroma(**options)

    def upsert(self, documents, owner, document_id, generation):
        metadata = [{"owner": owner, "document_id": document_id, "generation": generation, "chunk_id": d.id} for d in documents]
        self.store.add_texts([d.page_content for d in documents], metadatas=metadata,
                             ids=[generation + "_" + d.id for d in documents])

    @staticmethod
    def scope(owner, document_id, generation):
        return {"$and": [{"owner": owner}, {"document_id": document_id}, {"generation": generation}]}

    def delete(self, owner, document_id, generation):
        existing = self.store.get(where=self.scope(owner, document_id, generation), include=[])
        if existing["ids"]:
            self.store.delete(ids=existing["ids"])

    def count(self, owner, document_id, generation):
        return len(self.store.get(where=self.scope(owner, document_id, generation), include=[])["ids"])

    def search(self, vector, owner, document_id, generation, k):
        return self.store.similarity_search_by_vector_with_relevance_scores(vector, k=k, filter=self.scope(owner, document_id, generation))
