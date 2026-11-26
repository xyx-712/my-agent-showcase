"""Derived LangChain chunks with exact canonical-parent character spans."""
from copy import deepcopy
import hashlib
import json
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

VERSION = "recursive-char-v1"


def split_documents(documents, chunk_size=800, chunk_overlap=100):
    if (type(chunk_size) is not int or type(chunk_overlap) is not int
            or not 1 <= chunk_size <= 6000 or not 0 <= chunk_overlap < chunk_size):
        raise ValueError("chunk_size需1到6000，overlap需非负且小于chunk_size")
    splitter = RecursiveCharacterTextSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", "。", "；", " ", ""], keep_separator=True,
        add_start_index=True, strip_whitespace=False)
    output = []
    for parent in documents:
        if not parent.metadata.get("parent_id"):
            raise ValueError("父片段缺少稳定parent_id")
        for child in splitter.split_documents([Document(page_content=parent.page_content, metadata=deepcopy(parent.metadata))]):
            start = child.metadata.pop("start_index")
            end = start + len(child.page_content)
            if start < 0 or parent.page_content[start:end] != child.page_content:
                raise ValueError("子片段无法映射到原文")
            meta = child.metadata
            meta.update({"parent_char_start": start, "parent_char_end": end,
                         "splitter_version": VERSION, "chunk_size": chunk_size, "chunk_overlap": chunk_overlap})
            if parent.metadata.get("method") == "docx":
                base = parent.metadata.get("offset_start", 0)
                meta.update({"source_char_start": base + start, "source_char_end": base + end})
            else:
                meta.update({"child_line_start": parent.metadata["start"] + parent.page_content[:start].count("\n"),
                             "child_line_end": parent.metadata["start"] + parent.page_content[:max(start,end-1)].count("\n")})
            fingerprint = [meta["parent_id"], VERSION, chunk_size, chunk_overlap, start, end]
            identity = hashlib.sha256(json.dumps(fingerprint).encode()).hexdigest()
            meta["chunk_id"] = identity
            output.append(Document(id=identity, page_content=child.page_content, metadata=meta))
            if len(output) > 5000:
                raise ValueError("派生片段超过5000，请增大chunk_size")
    return output
