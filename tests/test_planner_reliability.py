"""Planner contract regressions. No server, database, files or live model."""
import json
import unittest
from unittest.mock import Mock,patch
from langchain_core.messages import AIMessage,HumanMessage
from src.agent.planner import TaskPlan,plan_task,request_requirements
from src.agent.tool_executor import execute_plan_step
from src.tools.registry import TOOL_REGISTRY
from tests.test_planner import plan,step


def clock():return {'id':'s1','order':1,'task_type':'time_query','tool':'time','args':{},'depends_on':[]}


class PlannerReliabilityTests(unittest.TestCase):
    def model(self,*plans):
        model=Mock();model.invoke.side_effect=[AIMessage(content=json.dumps(p)) for p in plans];return model
    def test_timestamp_reference_rejected_before_tools(self):
        invalid=plan(clock(),step(2,'$s1.result + 2 + 3',['s1']))
        with self.assertRaisesRegex(ValueError,'time'):TaskPlan.model_validate(invalid)

    def test_bad_timestamp_dependency_can_be_replanned(self):
        invalid=plan(clock(),step(2,'$s1.result + 2 + 3',['s1']))
        valid=plan(clock(),step(2,'2+3'))
        model=self.model(invalid,valid)
        # Not the literal fast path: let the model interpret a natural-language variant.
        result=plan_task(model,[HumanMessage(content='帮我查询当前时间，还需要计算2+3的结果')])
        self.assertEqual(result.steps[1].args,{'expression':'2+3'})
        self.assertIn('time',model.invoke.call_args.args[0][0].content)
        self.assertEqual(model.invoke.call_count,2)

    def test_current_calculation_overrides_profile_history(self):
        result_plan=plan(step(1,'100+200'),step(2,'$s1.result*3',['s1']))
        model=self.model({'action':'chat','steps':[],'question':''},result_plan)
        result=plan_task(model,[HumanMessage(content='我叫李四'),AIMessage(content='你叫李四'),HumanMessage(content='先计算100+200，再将结果乘以3。')])
        self.assertEqual(result.action,'execute');self.assertEqual(model.invoke.call_count,2)
        data=json.loads(model.invoke.call_args.args[0][-1].content)
        self.assertTrue(data['request_constraints']['dependent_calculation'])
        self.assertEqual(data['current_message_index'],2)
        self.assertEqual(sum(m['content']=='先计算100+200，再将结果乘以3。' for m in data['messages']),1)

    def test_precomputed_or_collapsed_dependency_is_not_accepted(self):
        for invalid in (plan(step(1,'100+200'),step(2,'300*3')),plan(step(1,'(100+200)*3'))):
            model=self.model(invalid,invalid)
            with self.assertRaises(ValueError):plan_task(model,[HumanMessage(content='先计算100+200，再将结果乘以3。')])
            self.assertEqual(model.invoke.call_count,2)

    def test_second_step_uses_actual_modified_first_result(self):
        state={'plan':plan(step(1,'100+200'),step(2,'$s1.result*3',['s1']))}
        with patch.object(TOOL_REGISTRY['calculator'],'func',return_value={'success':True,'result':317}):
            state.update(execute_plan_step(state))
        state.update(execute_plan_step(state))
        self.assertEqual(state['execution_records'][1]['result']['result'],951)
        self.assertEqual(state['execution_records'][1]['args']['expression'],'(317)*3')

    def test_ordinary_followup_does_not_replay_old_tools(self):
        model=self.model({'action':'chat','steps':[],'question':''})
        result=plan_task(model,[HumanMessage(content='先计算100+200'),AIMessage(content='300'),HumanMessage(content='我叫什么？')])
        self.assertEqual(result.action,'chat')

    def test_examples_and_explanations_do_not_require_calculator(self):
        for text in ('解释计算器里的1+4是什么意思','例如先计算100+200是什么意思','总结文件中计算100+200的部分'):
            self.assertEqual(request_requirements(text)['required_tools'],[])

    def test_explicit_no_execution_is_enforced(self):
        for text in ('不要计算100+200，只解释加法','别计算100+200','不用计算100+200','不需要计算100+200','不要查询当前时间'):
            model=self.model(plan(step(1,'100+200')),{'action':'chat','steps':[],'question':''})
            result=plan_task(model,[HumanMessage(content=text)])
            self.assertEqual(result.action,'chat');self.assertEqual(model.invoke.call_count,2)

    def test_independent_literal_mixed_clauses_both_orders(self):
        for text,expected in (('查询当前时间，并计算2+3。',['time','calculator']),('算一下12×4，然后告诉我现在时间',['calculator','time'])):
            model=Mock();result=plan_task(model,[HumanMessage(content=text)])
            model.invoke.assert_not_called()
            self.assertEqual([s.tool for s in result.steps],expected)
            self.assertTrue(all(not s.depends_on for s in result.steps))

    def test_followup_binds_checkpoint_value_not_chat_text(self):
        record={'tool':'calculator','status':'completed','result':{'success':True,'result':317}}
        model=Mock()
        result=plan_task(model,[AIMessage(content='999'),HumanMessage(content='再将结果乘以3')],previous_records=[record])
        model.invoke.assert_not_called();self.assertEqual(result.steps[0].args,{'expression':'(317) * 3'})

    def test_missing_or_invalid_previous_result_is_clarified(self):
        self.assertEqual(plan_task(Mock(),[HumanMessage(content='再乘以三')]).action,'clarify')
        for record in (None,{'tool':'time','status':'completed','result':'2026-11-24 12:00:00'},
                       *[{'tool':'calculator','status':'completed','result':{'result':value}} for value in ('300',True,float('inf'),10**400)],
                       {'tool':'calculator','status':'failed','result':{'result':300}}):
            result=plan_task(Mock(),[HumanMessage(content='再乘以3')],previous_records=[record] if record else None)
            self.assertEqual(result.action,'clarify')

    def test_unsupported_time_arithmetic_does_not_force_execution(self):
        model=self.model({'action':'clarify','steps':[],'question':'时间不能直接当数值，请明确数值。'})
        result=plan_task(model,[HumanMessage(content='把当前时间乘以2')])
        self.assertEqual(result.action,'clarify')

    def test_chat_question_feedback_is_precise_but_contract_stays_strict(self):
        with self.assertRaisesRegex(ValueError,'question必须填空字符串'):
            TaskPlan(action='chat',steps=[],question='我叫什么')

    def test_followup_source_must_match_actual_previous_message(self):
        from src.agent.tool_router import tool_router
        record={'tool':'calculator','status':'completed','result':{'result':300},'source_message_id':10}
        for prior_id,expected in (('10','execute'),('20','clarify')):
            state={'mode':'chat','source_message_id':22,'execution_records':[record],
                   'messages':[HumanMessage(content='previous turn',id=prior_id),AIMessage(content='reply'),HumanMessage(content='再乘以3')]}
            self.assertEqual(tool_router(state,Mock())['plan']['action'],expected)


if __name__=='__main__':unittest.main()
