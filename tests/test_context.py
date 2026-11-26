import json
import os
import unittest
from unittest.mock import patch
from langchain_core.messages import HumanMessage as H, AIMessage as A, ToolMessage
from src.agent.context import chat,prepare_messages,structured,cost,budget,ContextBudgetError,bounded_model


class ContextTests(unittest.TestCase):
    def test_memory_entries_are_not_cut_at_newlines(self):
        value='前提：禁止删除\n'+'完整说明'*500
        result=chat([H(content='question')],memory=[{'key':'name','value':'Fictional'},{'key':'preference','value':value}])
        self.assertIn('name: Fictional',result[0].content)
        self.assertNotIn('禁止删除',result[0].content)

    def test_duplicate_current_identity_removed_not_equal_text(self):
        current=H(content='current',id='fictional-current')
        messages=prepare_messages([H(content='current'),A(content='previous answer'),current,current])
        self.assertEqual(sum(m.id=='fictional-current' for m in messages),1)
        self.assertEqual(sum(m.content=='current' for m in messages),2)

    def test_single_turn_and_roles(self):
        history=[H(content='前提：不要删除文件'),A(content='明白'),H(content='如何继续？')]
        result=chat(history)
        self.assertEqual([m.content for m in result[1:]], [m.content for m in history])
        self.assertEqual([m.type for m in result],['system','human','ai','human'])
        self.assertEqual(sum(m.content=='如何继续？' for m in result),1)

    def test_drop_old_complete_turns_not_message_suffix(self):
        recent='前提：不允许删除任何文件。'+'很长的说明'*250
        messages=[H(content='old'*5000),A(content='old answer'),H(content=recent),A(content='明白'),H(content='继续')]
        result=chat(messages)
        self.assertNotIn('old answer',[m.content for m in result])
        self.assertIn(recent,[m.content for m in result])
        self.assertLessEqual(cost(result),budget().available)

    def test_repeated_question_is_not_content_deduplicated(self):
        result=chat([H(content='相同的问题'),A(content='第一次回答'),H(content='相同的问题')])
        self.assertEqual(sum(m.content=='相同的问题' for m in result),2)

    def test_essential_long_input_fails_without_silent_truncation(self):
        text='当前问题'*5000
        with self.assertRaises(ContextBudgetError):chat([H(content=text)])
        self.assertEqual(prepare_messages([H(content=text)])[-1].content,text)

    def test_tool_pair_preserved_and_only_once(self):
        ai=A(content='',tool_calls=[{'name':'time','args':{},'id':'call1','type':'tool_call'}])
        tool=ToolMessage(content='SERVER_TIME_RESULT',tool_call_id='call1')
        result=chat([H(content='现在几点')],execution_messages=[ai,tool])
        self.assertEqual(result[-2:],[ai,tool])
        self.assertEqual(sum(m.content=='SERVER_TIME_RESULT' for m in result),1)

    def test_memory_and_task_share_budget(self):
        result=chat([H(content='当前问题')],memory='name: Fictional\n'+'偏好：'+'长'*3000,task_context={'status':'waiting'})
        self.assertIn('name: Fictional',result[0].content)
        self.assertTrue(any('waiting' in m.content for m in result))
        self.assertLessEqual(cost(result),budget().available)

    def test_structured_evidence_never_truncated(self):
        data={'request':'问题','sources':[{'text':'证据'*6000}]}
        with self.assertRaises(ContextBudgetError):structured('规则','{}','',data)
        self.assertEqual(len(data['sources'][0]['text']),12000)

    def test_structured_history_budget_and_immutable_input(self):
        history=[{'role':'human','content':'old'*15000},{'role':'ai','content':'answer'},{'role':'human','content':'current'}]
        data={'messages':history,'sources':[{'text':'原文'}]}
        rendered=structured('规则','{}','',data)
        actual=json.loads(rendered[-1].content)
        self.assertEqual(actual['messages'],[history[-1]])
        self.assertEqual(actual['sources'],data['sources'])
        self.assertEqual(len(data['messages']),3)

    def test_custom_counter_and_bounded_model_copy(self):
        from langchain_ollama import ChatOllama
        model=ChatOllama(model='fictional')
        copied=bounded_model(model)
        self.assertEqual((copied.num_ctx,copied.num_predict),(8192,4096))
        self.assertIsNone(model.num_ctx)
        result=chat([H(content='question')],counter=lambda text:len(text))
        self.assertLessEqual(cost(result,lambda text:len(text)),budget().available)

    def test_bad_configuration_rejected(self):
        with patch.dict(os.environ,{'MY_AGENT_CONTEXT_RESERVE':'9000'}):
            with self.assertRaises(ContextBudgetError):budget()
