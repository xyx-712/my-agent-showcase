import unittest
from unittest.mock import Mock, patch

from src.retrieval.qa import answer, general_question


class RagTests(unittest.TestCase):
    def test_contradictory_answerability_is_retried(self):
        from langchain_core.messages import AIMessage
        from src.agent.skills import answer_documents
        model = Mock()
        model.invoke.side_effect = [
            AIMessage(content='{"answerable":false,"items":[{"source":0,"quote":"每份二十元。"}],"synthesis":[]}'),
            AIMessage(content='{"answerable":true,"items":[],"synthesis":[],"coverage":[{"part":0,"missing":false,"answer":"每份二十元。","evidence":[{"source":0,"quote":"每份二十元。"}]}]}')]
        text, citations = answer_documents(model, [{'text':'每份二十元。','file_id':'a','name':'policy.txt','page':None,'start':1,'end':1}],
                                          '每份多少钱？', evidence_only=True)
        self.assertEqual(model.invoke.call_count, 2)
        self.assertEqual(len(citations), 1)
        self.assertIn('二十元', text)

    def test_explicit_insufficient_evidence_has_no_citations(self):
        from langchain_core.messages import AIMessage
        from src.agent.skills import answer_documents
        model = Mock()
        model.invoke.return_value = AIMessage(content='{"answerable":false,"items":[],"synthesis":[],"digest":"缺少金额","coverage":[{"part":0,"missing":true,"answer":"","evidence":[]}]}')
        text, citations = answer_documents(model, [{'text':'每年十五天。','file_id':'a','name':'policy.txt','page':None,'start':1,'end':1}],
                                          '未休假折现多少钱？', evidence_only=True)
        self.assertEqual(citations, [])
        self.assertIn('找不到可核对的依据', text)

    def test_full_document_routing(self):
        for question in ('总结全文', '缩减摘要', '比较版本', '计算工期', '批准变更'):
            self.assertFalse(general_question(question))
        self.assertTrue(general_question('员工休假需要找谁申请？'))

    def test_irrelevant_never_calls_model(self):
        service = Mock()
        service.search.return_value = [dict(document_id='a', chunk_id='b', generation='g', similarity=.2)]
        model = Mock()
        text, citations, audit = answer('owner', '火星有多远', ['a'], model, service)
        self.assertIn('没有找到足够依据', text)
        self.assertEqual(citations, [])
        self.assertFalse(audit[0]['accepted'])
        model.invoke.assert_not_called()

    def test_verified_sources_and_deleted_generation(self):
        service = Mock()
        source = {'file_id': 'a', 'name': 'policy.txt', 'page': None, 'start': 1, 'end': 1}
        service.search.return_value = [dict(document_id='a', chunk_id='b', generation='g',
            similarity=.9, source=source, text='向主管申请。')]
        with patch('src.agent.skills.answer_documents', return_value=('主管', [source])) as generate, \
             patch('src.server.documents.get_document'), \
             patch('src.retrieval.service.statuses', return_value={'a': {'status':'READY','generation':'g'}}):
            text, citations, _ = answer('owner', '找谁申请', ['a'], Mock(), service)
            self.assertEqual(text, '主管')
            self.assertEqual(citations, [source])
            self.assertEqual(generate.call_args.args[1][0]['text'], '向主管申请。')
        with patch('src.agent.skills.answer_documents', return_value=('主管', [source])), \
             patch('src.server.documents.get_document'), \
             patch('src.retrieval.service.statuses', return_value={}):
            with self.assertRaises(ValueError):
                answer('owner', '找谁申请', ['a'], Mock(), service)
