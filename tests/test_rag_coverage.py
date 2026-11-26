import unittest,json
from unittest.mock import Mock
from langchain_core.messages import AIMessage
from src.agent.skills import answer_documents
SOURCES=[{'text':'员工年假十五天，由直属主管审批。','file_id':'leave','name':'leave.txt','page':None,'start':1,'end':1},{'text':'数据恢复必须由管理员执行并核对完整性。','file_id':'backup','name':'backup.txt','page':None,'start':1,'end':1}]
def point(i,answer,source):return {'part':i,'missing':False,'answer':answer,'evidence':[{'source':source,'quote':SOURCES[source]['text']}]}
def payload(points):return {'answerable':True,'items':[],'synthesis':[],'coverage':points}
class CoverageTests(unittest.TestCase):
 def call(self,q,responses):
  model=Mock();model.invoke.side_effect=[AIMessage(content=json.dumps(x,ensure_ascii=False)) for x in responses];return model,answer_documents(model,SOURCES,q,evidence_only=True)
 def test_both_recovery_points_render_in_body(self):
  _,(text,citations)=self.call('谁有权恢复数据，需要检查什么？',[payload([point(0,'管理员执行',1),point(1,'核对完整性',1)])]);self.assertIn('[原文事实] 管理员执行',text);self.assertIn('[原文事实] 核对完整性',text);self.assertEqual([c['file_id'] for c in citations],['backup'])
 def test_joint_sources_and_all_parts(self):
  _,(text,citations)=self.call('年假有几天、由谁审批，数据库由谁恢复并核对什么？',[payload([point(0,'十五天',0),point(1,'直属主管审批',0),point(2,'管理员恢复',1),point(3,'核对完整性',1)])]);self.assertEqual({c['file_id'] for c in citations},{'leave','backup'});self.assertEqual(text.count('[原文事实]'),4)
 def test_omitted_part_retries(self):
  a=payload([point(0,'管理员执行',1)]);b=payload([point(0,'管理员执行',1),point(1,'核对完整性',1)]);model,_=self.call('谁恢复，需要检查什么？',[a,b]);self.assertEqual(model.invoke.call_count,2);self.assertIn('不可漏项',model.invoke.call_args.args[0][0].content)
 def test_duplicate_part_rejected(self):
  a=payload([point(0,'管理员',1),point(0,'完整性',1)])
  with self.assertRaises(ValueError):self.call('谁恢复，需要检查什么？',[a,a])
 def test_partial_missing_is_explicit_without_citation(self):
  p={'part':1,'missing':True,'answer':'','evidence':[]};_,(text,citations)=self.call('谁恢复，需要支付多少钱？',[payload([point(0,'管理员恢复',1),p])]);self.assertIn('资料未说明：需要支付多少钱',text);self.assertEqual(len(citations),1)
 def test_all_missing_refuses(self):
  p={'answerable':False,'items':[],'synthesis':[],'coverage':[{'part':0,'missing':True,'answer':'','evidence':[]}]};_,(text,citations)=self.call('火星有多高？',[p]);self.assertEqual(citations,[]);self.assertIn('找不到可核对',text)
 def test_missing_cannot_include_fake_evidence(self):
  p={'answerable':False,'items':[],'synthesis':[],'coverage':[{'part':0,'missing':True,'answer':'','evidence':[{'source':1,'quote':SOURCES[1]['text']}]}]}
  with self.assertRaises(ValueError):self.call('火星有多高？',[p,p])
