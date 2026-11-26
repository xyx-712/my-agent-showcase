"""Real answer-only regression; fictional sources; no database/index access."""
import json,sys,time
from pathlib import Path
from unittest.mock import patch

def run():
 def audit(event,args):
  if event=='sqlite3.connect':raise RuntimeError('No database access allowed')
 sys.addaudithook(audit)
 from src.agent import skills,execution
 from src.agent.model_provider import get_chat_model
 from src.retrieval.qa import answer
 fixture=json.loads(Path('tests/fixtures/rag_chinese.json').read_text(encoding='utf-8'))
 old=json.loads(Path('docs/rag-hybrid-real-results.json').read_text(encoding='utf-8'))
 model=get_chat_model();report={'model':model.model,'rows':[],'threshold':.65,'scope':'Replay captured authorized evidence into unchanged QA gate; no retrieval/index rerun'}
 docs={d['id']:d for d in fixture['documents']}
 mapping={old['rows'][i]['expected']:docs[q['expected']] for i,q in enumerate(fixture['queries'])}
 original=execution.invoke_model;started=time.perf_counter()
 def execute(question,hits,expected):
  record={'question':question,'calls':[],'expected':expected}
  def capture(client,messages):
   item={'messages':[m.model_dump(mode='json') for m in messages]};record['calls'].append(item)
   response=original(client,messages);item['raw']=response.content
   try:item['parsed']=json.loads(response.content)
   except Exception as ex:item['parse_error']=str(ex)
   return response
  class Service:
   def search(self,*args):return hits
  try:
   with patch.object(execution,'invoke_model',capture),patch('src.server.documents.get_document'),patch('src.retrieval.service.statuses',return_value={h['document_id']:{'status':'READY','generation':h['generation']} for h in hits}):
    text,citations,diagnostic=answer('fictional',question,[h['document_id'] for h in hits],model,Service())
   record.update(answer=text,citations=citations,audit=diagnostic,refused=not bool(citations),quote_checks=[])
   for citation in citations:
    record['quote_checks'].append(any(citation['text']==h['text'] and citation['file_id']==h['document_id'] for h in hits))
  except Exception as ex:record['error']=str(ex)
  report['rows'].append(record);print('CASE',len(report['rows']),bool(record.get('citations')),record.get('error',''),flush=True)
 for row in old['rows']:
  hits=[]
  for h in row['hybrid']:
   d=mapping[h['document_id']];source={'file_id':h['document_id'],'name':d['name'],'text':d['text'],'page':None,'start':1,'end':1}
   hits.append({**h,'text':d['text'],'source':source})
  execute(row['question'],hits,row['expected'])
 source_texts=['员工每年享有十五天年假。','年假申请需要提前三天向直属主管提交。']
 hits=[dict(document_id=str(i),chunk_id=str(i),generation='g',similarity=score,text=text,source={'file_id':str(i),'name':str(i)+'.txt','text':text,'page':None,'start':1,'end':1},retrieval_channels=['vector']) for i,(score,text) in enumerate(zip([.8,.6],source_texts))]
 execute('员工年假有几天，年假申请需要提前多久向谁提交？',hits,['0','1'])
 report['direct_answer_negatives']=[]
 for q in ['年假未休完可以折算多少元现金？','火星大气中氩气的比例是多少？']:
  source={'file_id':'fictional-leave','name':'leave.txt','page':None,'start':1,'end':1,'text':docs['leave']['text']};record={'question':q,'calls':[]}
  def record_invoke(client,messages):
   response=original(client,messages);record['calls'].append({'messages':[m.model_dump(mode='json') for m in messages],'raw':response.content,'parsed':json.loads(response.content)});return response
  with patch.object(execution,'invoke_model',record_invoke):text,citations=skills.answer_documents(model,[source],q,evidence_only=True)
  record.update(answer=text,citations=citations);report['direct_answer_negatives'].append(record)
 report['injected_contradiction_retries']=[]
 from langchain_core.messages import AIMessage
 for q,key in [('谁有权恢复数据，需要检查什么？','backup'),('设置登录密码有什么要求？','security'),('发现有人异常登录账号应该如何处理？','security')]:
  source={'file_id':key,'name':docs[key]['name'],'page':None,'start':1,'end':1,'text':docs[key]['text']};record={'question':q,'calls':[]}
  def injected(client,messages):
   is_first=not record['calls']
   response=AIMessage(content=json.dumps({'answerable':False,'items':[{'source':0,'quote':source['text']}],'synthesis':[]},ensure_ascii=False)) if is_first else original(client,messages)
   record['calls'].append({'injected':is_first,'messages':[m.model_dump(mode='json') for m in messages],'raw':response.content,'parsed':json.loads(response.content)});return response
  with patch.object(execution,'invoke_model',injected):text,citations=skills.answer_documents(model,[source],q,evidence_only=True)
  record.update(answer=text,citations=citations);report['injected_contradiction_retries'].append(record)
 report['seconds']=round(time.perf_counter()-started,3)
 Path('docs/rag-answer-quality-results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
 print('SAVED',report['seconds'],flush=True)
if __name__=='__main__':run()
