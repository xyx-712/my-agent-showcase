import unittest
from unittest.mock import Mock,patch
from src.retrieval.qa import answer
class HybridTests(unittest.TestCase):
 def test_partial_semantic_does_not_suppress_lexical(self):
  hits=[dict(document_id=i,chunk_id=i,generation='g',similarity=score,text=text,source={'file_id':i,'name':i,'page':None,'start':1,'end':1}) for i,score,text in [('a',.8,'员工每年十五天年假。'),('b',.6,'年假申请须向主管提交。')]]
  service=Mock();service.search.return_value=hits
  with patch('src.agent.skills.answer_documents',return_value=('ok',[])) as gen,patch('src.server.documents.get_document'),patch('src.retrieval.service.statuses',return_value={i:{'status':'READY','generation':'g'} for i in ['a','b']}):
   _,_,audit=answer('u','年假额度及年假申请流程？',['a','b'],Mock(),service)
   self.assertEqual(len(gen.call_args.args[1]),2)
   self.assertEqual(audit[1]['accepted_by'],'lexical')
   self.assertEqual(audit[1]['similarity'],.6)
 def test_unrelated_lexical_does_not_pass(self):
  service=Mock();service.search.return_value=[dict(document_id='a',chunk_id='a',generation='g',similarity=.2,text='年假申请。')]
  model=Mock();_,citations,audit=answer('u','火星氩气比例？',['a'],model,service)
  self.assertFalse(citations);self.assertFalse(audit[0]['accepted']);model.invoke.assert_not_called()

class IndependentLexicalRecallTests(unittest.TestCase):
 def test_outside_vector_pool_is_scored_deduplicated_and_scoped(self):
  from contextlib import contextmanager
  from langchain_core.documents import Document
  from src.retrieval.service import IndexService
  from src.retrieval.embeddings import IndexSettings
  @contextmanager
  def database():
   db=Mock();db.execute.return_value=[('doc','g')];yield db
  backend=Mock();backend.identity.return_value='rev';backend.embed_query.return_value=[1.,0.];backend.embed_documents.return_value=[[.6,.8]]
  store=Mock();store.count.return_value=2
  a=Document(id='a',page_content='unrelated',metadata={'chunk_id':'a'})
  b=Document(id='b',page_content='年假申请找主管',metadata={'chunk_id':'b'})
  store.search.return_value=[(a,.2)]
  row={'status':'READY','model_revision':'rev','dimension':2,'generation':'g','chunk_count':2}
  with patch('src.server.documents.documents',return_value=[{'id':'doc'}]),patch('src.server.documents.get_document') as owned,patch('src.retrieval.service.enqueue',return_value=row),patch('src.retrieval.service.database',database),patch('src.retrieval.service.settings',return_value=IndexSettings()),patch('src.retrieval.service.load_owned_document'),patch('src.retrieval.service.split_documents',return_value=[a,b]),patch('src.retrieval.service.statuses',return_value={'doc':row}):
   hits=IndexService(lambda cfg:backend,lambda *args:store).search('owner','年假申请', ['doc'],1)
   self.assertEqual(len(hits),2)
   extra=next(h for h in hits if h['chunk_id']=='b')
   self.assertEqual(extra['retrieval_channels'],['lexical']);self.assertAlmostEqual(extra['similarity'],.6)
   self.assertTrue(all(call.args[0]=='owner' for call in owned.call_args_list))
   store.search.return_value=[(b,.4)]
   hits=IndexService(lambda cfg:backend,lambda *args:store).search('owner','年假申请',['doc'],1)
   self.assertEqual(len(hits),1);self.assertEqual(hits[0]['retrieval_channels'],['vector','lexical'])
 def test_foreign_document_rejected_before_embedding(self):
  from src.retrieval.service import IndexService
  backend=Mock()
  with patch('src.server.documents.documents',return_value=[]),patch('src.server.documents.get_document',side_effect=ValueError('not owned')):
   with self.assertRaises(ValueError):IndexService(lambda cfg:backend).search('owner','年假申请',['foreign'],1)
  backend.embed_query.assert_not_called()
