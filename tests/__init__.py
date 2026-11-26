"""Test processes never implicitly start external indexing workers."""
import os
os.environ["MY_AGENT_RAG_ENABLED"] = "0"
