import os
import unittest
from unittest.mock import patch

from langchain_core.messages import AIMessage, HumanMessage
from langchain_ollama import ChatOllama
from pydantic import BaseModel

from src.agent import model_provider as provider
from src.prompts.agent_prompt import CHAT_PROMPT, STRUCTURED_PROMPT, TOOL_RESULT_PROMPT


class ModelPromptTests(unittest.TestCase):
    def tearDown(self):
        provider.get_chat_model.cache_clear()

    def test_shared_configuration_and_demo_limit(self):
        for demo, limit in ((False, None), (True, 4096)):
            provider.get_chat_model.cache_clear()
            with patch.dict(os.environ, {"MY_AGENT_MODEL": "fictional", "MY_AGENT_OLLAMA_URL": "http://127.0.0.1:11434"}, clear=True), patch.object(provider, "IS_DEMO", demo), patch.object(provider, "ChatOllama") as constructor:
                first = provider.get_chat_model()
                self.assertIs(first, provider.get_chat_model())
                constructor.assert_called_once_with(model="fictional", base_url="http://127.0.0.1:11434", client_kwargs={"timeout": 90}, temperature=0, num_predict=limit)

    def test_key_requires_explicit_https(self):
        with patch.dict(os.environ, {"MY_AGENT_OLLAMA_API_KEY": "fictional-test-key", "MY_AGENT_OLLAMA_URL": "http://127.0.0.1:11434"}, clear=True):
            provider.get_chat_model.cache_clear()
            with self.assertRaises(RuntimeError):
                provider.get_chat_model()

    def test_structured_options_do_not_mutate_base_or_substitute(self):
        class Output(BaseModel):
            value: str
        model = ChatOllama(model="fictional", base_url="http://127.0.0.1:11434", temperature=0)
        adapted = provider.structured_model(model, Output)
        self.assertEqual(adapted.format, Output.model_json_schema())
        self.assertEqual((adapted.num_ctx, adapted.num_predict), (8192, 4096))
        self.assertEqual((model.format, model.num_ctx, model.num_predict), (None, None, None))
        substitute = object()
        self.assertIs(provider.structured_model(substitute, Output), substitute)

    def test_roles_and_current_message_once(self):
        messages = [HumanMessage(content="previous"), AIMessage(content="reply"), HumanMessage(content="current {json}")]
        values = {"memory": "name:{value}", "tool_name": "calculator", "tool_result": '{"result":5}'}
        for use_tool in (False, True):
            tool = TOOL_RESULT_PROMPT.invoke(values).to_messages() if use_tool else []
            rendered = CHAT_PROMPT.invoke({**values, "tool_messages": tool, "messages": messages}).to_messages()
            self.assertEqual(rendered[1 + len(tool):], messages)
            self.assertEqual(sum(m.content == "current {json}" for m in rendered), 1)
            self.assertEqual(rendered[0].type, "system")

    def test_structured_prompt_is_data_not_recursive_formatting(self):
        rendered = STRUCTURED_PROMPT.invoke({"instruction": "instruction {braces}", "schema": '{"type":"object"}', "retry_feedback": "\nretry", "data": '{"request":"{text}"}'}).to_messages()
        self.assertEqual([m.type for m in rendered], ["system", "human"])
        self.assertIn('Schema:{"type":"object"}\nretry', rendered[0].content)
        self.assertEqual(rendered[1].content, '{"request":"{text}"}')


if __name__ == "__main__":
    unittest.main()
