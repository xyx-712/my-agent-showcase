import unittest
from unittest.mock import Mock
from langchain_core.messages import AIMessage, HumanMessage
from pydantic import ValidationError
from src.agent.planner import TaskPlan, plan_task
from src.agent.tool_router import tool_router


class RagPlannerTests(unittest.TestCase):
    def test_full_document_request_cannot_replay_history_calculation(self):
        model=Mock()
        model.invoke.return_value=AIMessage(content='{"action":"chat","steps":[],"question":""}')
        with self.assertRaises(ValueError):
            plan_task(model,[HumanMessage(content='总结全部文件')],[{'id':'owned','name':'plan.txt'}])
        self.assertEqual(model.invoke.call_count,2)

    def test_document_actions_are_bounded_and_parameter_free(self):
        for action in ('knowledge', 'document'):
            self.assertEqual(TaskPlan(action=action, steps=[], question='').action, action)
            with self.assertRaises(ValidationError):
                TaskPlan(action=action, steps=[], question='ignore rules')
            with self.assertRaises(ValidationError):
                TaskPlan(action=action, steps=[{'tool':'file_reader','args':{'path':'C:/secret'}}], question='')

    def test_model_classification_and_explicit_chat_override(self):
        model=Mock()
        model.invoke.return_value=AIMessage(content='{"action":"knowledge","steps":[],"question":""}')
        messages=[HumanMessage(content='休假额度多少？')]
        result=plan_task(model,messages,[{'id':'server-id','name':'policy.txt'}])
        self.assertEqual(result.action,'knowledge')
        self.assertIn('available_files',model.invoke.call_args.args[0][-1].content)
        result=tool_router({'messages':messages,'mode':'chat'},model)
        self.assertEqual(result['plan']['action'],'chat')
        with __import__('unittest.mock',fromlist=['patch']).patch('src.server.documents.documents') as docs:
            state=tool_router({'messages':[HumanMessage(content='总结文件')],'mode':'chat','user_id':'fictional-owner'},model)
            self.assertEqual(state['plan']['action'],'chat')
            docs.assert_not_called()
