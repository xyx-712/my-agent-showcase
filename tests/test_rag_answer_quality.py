import json,unittest
from unittest.mock import Mock
from langchain_core.messages import AIMessage
from src.agent.skills import answer_documents
SOURCE={'text':'数据恢复必须由管理员执行并核对完整性。','file_id':'a','name':'backup.txt','page':None,'start':1,'end':1}
class AnswerQualityTests(unittest.TestCase):
 def run_case(self,outputs,question='谁有权恢复数据，需要检查什么？'):
  model=Mock();model.invoke.side_effect=[AIMessage(content=x if isinstance(x,str) else json.dumps(x,ensure_ascii=False)) for x in outputs]
  result=answer_documents(model,[SOURCE],question,evidence_only=True);return model,result
 def valid(self):return {'answerable':True,'items':[],'synthesis':[],'coverage':[{'part':i,'missing':False,'answer':answer,'evidence':[{'source':0,'quote':SOURCE['text']}]} for i,answer in enumerate(['管理员执行','核对完整性'])]}
 def test_contradiction_retry_keeps_evidence_and_specific_feedback(self):
  first={**self.valid(),'answerable':False}
  model,(text,citations)=self.run_case([first,self.valid()])
  self.assertEqual(len(citations),1);self.assertEqual(model.invoke.call_count,2)
  second=model.invoke.call_args_list[1].args[0]
  self.assertIn('不能仅通过清空',second[0].content);self.assertIn('矛盾',second[0].content)
  self.assertIn(SOURCE['text'],second[1].content);self.assertIn('谁有权恢复数据，需要检查什么？',second[1].content)
 def test_empty_true_is_retried(self):
  model,(_,citations)=self.run_case([{'answerable':True,'items':[],'synthesis':[]},self.valid()]);self.assertEqual(len(citations),1);self.assertEqual(model.invoke.call_count,2)
 def test_real_missing_answer_may_still_refuse_after_contradiction(self):
  model,(_,citations)=self.run_case([{**self.valid(),'answerable':False},{'answerable':False,'items':[],'synthesis':[],'coverage':[{'part':0,'missing':True,'answer':'','evidence':[]}]}], '恢复数据收费多少钱？');self.assertEqual(citations,[])
 def test_invalid_json_then_valid(self):
  model,(_,citations)=self.run_case(['not JSON',self.valid()]);self.assertEqual(len(citations),1)
 def test_wrong_quote_rejected_with_two_call_limit(self):
  bad=self.valid();bad['coverage'][0]['evidence'][0]['quote']='恢复需要支付十元。'
  with self.assertRaises(ValueError):self.run_case([bad,bad])
 def test_unsupported_inference_rejected(self):
  bad={'answerable':True,'items':[],'synthesis':[{'text':'任何人都能恢复','kind':'inference','evidence':[{'source':0,'quote':SOURCE['text']}]}]}
  with self.assertRaises(ValueError):self.run_case([bad,bad])
