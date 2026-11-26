"""Lazy, independently configured Ollama embeddings; never initialized at API startup."""
from dataclasses import dataclass
import hashlib
import json
import math
import os
from langchain_core.embeddings import Embeddings


@dataclass(frozen=True)
class IndexSettings:
    model: str = "embeddinggemma"
    url: str = "http://127.0.0.1:11434"
    revision: str = ""
    chunk_size: int = 800
    chunk_overlap: int = 100

    @property
    def key(self):
        from src.retrieval.splitter import VERSION
        payload = [self.model, self.url, self.revision, self.chunk_size, self.chunk_overlap, VERSION, "cosine", "source-adapter-v1",
                   os.environ.get('MY_AGENT_CHROMA_URL','embedded'),os.environ.get('MY_AGENT_CHROMA_DIR','default')]
        return hashlib.sha256(json.dumps(payload).encode()).hexdigest()


def settings():
    value = IndexSettings(os.environ.get("MY_AGENT_EMBEDDING_MODEL", "embeddinggemma"),
        os.environ.get("MY_AGENT_EMBEDDING_URL", "http://127.0.0.1:11434"),
        os.environ.get("MY_AGENT_EMBEDDING_REVISION", ""),
        int(os.environ.get("MY_AGENT_RAG_CHUNK_SIZE", "800")), int(os.environ.get("MY_AGENT_RAG_CHUNK_OVERLAP", "100")))
    if not value.model or not 1 <= value.chunk_size <= 6000 or not 0 <= value.chunk_overlap < value.chunk_size:
        raise ValueError("Embedding或切分配置无效")
    return value


class OllamaVectors(Embeddings):
    def __init__(self, config):
        from langchain_ollama import OllamaEmbeddings
        self.config = config
        self.dimension = None
        self.client = OllamaEmbeddings(model=config.model, base_url=config.url, client_kwargs={"timeout": 30})

    def identity(self):
        from ollama import Client
        expected = self.config.model if ":" in self.config.model else self.config.model + ":latest"
        for model in Client(host=self.config.url, timeout=10).list().models:
            if model.model in {self.config.model, expected}:
                return model.digest + ":" + self.config.revision
        raise RuntimeError("Embedding模型未安装，请运行 ollama pull " + self.config.model)

    def _validate(self, vectors, expected):
        if len(vectors) != expected or not vectors:
            raise ValueError("Embedding数量错误")
        dimension = len(vectors[0])
        if not 1 <= dimension <= 16384 or any(len(v) != dimension or any(not math.isfinite(x) for x in v) for v in vectors):
            raise ValueError("Embedding维度或数值无效")
        if self.dimension is not None and dimension != self.dimension:
            raise ValueError("Embedding维度发生变化")
        self.dimension = dimension
        return vectors

    def embed_documents(self, texts):
        return self._validate(self.client.embed_documents(texts), len(texts))

    def embed_query(self, text):
        return self._validate([self.client.embed_query(text)], 1)[0]
