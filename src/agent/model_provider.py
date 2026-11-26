"""Shared local model configuration; callers may still inject an invoke-compatible model."""
from functools import lru_cache
import os

from langchain_ollama import ChatOllama

from src.config import IS_DEMO


@lru_cache(maxsize=1)
def get_chat_model():
    """Create one base model per process, using the existing environment contract."""
    model_url = os.environ.get("MY_AGENT_OLLAMA_URL")
    model_key = os.environ.get("MY_AGENT_OLLAMA_API_KEY")
    client_kwargs = {"timeout": 90}
    if model_key:
        if not model_url or not model_url.startswith("https://"):
            raise RuntimeError("MY_AGENT_OLLAMA_API_KEY requires an explicit HTTPS model URL")
        client_kwargs["headers"] = {"Authorization": f"Bearer {model_key}"}
    return ChatOllama(
        model=os.environ.get("MY_AGENT_MODEL", "qwen2.5:7b"),
        base_url=model_url,
        client_kwargs=client_kwargs,
        temperature=0,
        num_predict=4096 if IS_DEMO else None,
    )


def structured_model(model, schema):
    """Preserve current Ollama JSON format and limits without mutating the shared model."""
    if isinstance(model, ChatOllama):
        return model.model_copy(update={"format": schema.model_json_schema(), "num_ctx": 8192, "num_predict": 4096})
    return model
