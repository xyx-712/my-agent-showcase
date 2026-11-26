"""LangChain loader adapter over validated canonical source chunks."""
from copy import deepcopy
import hashlib
import json
from langchain_core.document_loaders import BaseLoader
from langchain_core.documents import Document


def parent_identifier(file_id, name, chunk):
    payload = json.dumps([file_id, name, chunk], ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class SourceLoader(BaseLoader):
    """Adapt parsed chunks without reopening paths or changing canonical positions."""
    def __init__(self, name, chunks, file_id):
        self.name, self.chunks, self.file_id = name, deepcopy(chunks), file_id

    def lazy_load(self):
        for chunk in self.chunks:
            parent_id = parent_identifier(self.file_id, self.name, chunk)
            metadata = {k: deepcopy(v) for k, v in chunk.items() if k != "text"}
            metadata.update({"name": self.name, "source": self.name, "file_id": self.file_id,
                             "parent_id": parent_id, "loader_version": "source-adapter-v1"})
            yield Document(id=parent_id, page_content=chunk["text"], metadata=metadata)


def load_document(name, content):
    """Load supplied bytes through the existing safety checks, never a caller's path."""
    from src.server.documents import parse_document
    chunks = parse_document(name, content)
    return SourceLoader(name, chunks, hashlib.sha256(content).hexdigest()).load()


def load_owned_document(user_id, file_id):
    """Server-side identity required; reuse persisted content and original references."""
    from src.server.documents import get_document
    doc = get_document(user_id, file_id)
    return SourceLoader(doc["name"], doc["chunks"], doc["id"]).load()
