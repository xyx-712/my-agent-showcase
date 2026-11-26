import unittest
from src.retrieval.qa import lexical_evidence_terms

class LexicalEvidenceTests(unittest.TestCase):
    def test_original_compound_question(self):
        self.assertEqual(lexical_evidence_terms('根据上传文件，每年年假有几天，找谁申请？', '青禾公司每年提供十五天年假，申请须提前三天提交给直属主管审批。'), ['年假', '申请'])
    def test_generic_and_one_term_are_insufficient(self):
        self.assertEqual(lexical_evidence_terms('根据上传文件，公司每年补贴多少？','公司每年提供年假。'), [])
        self.assertEqual(lexical_evidence_terms('年假可以折算多少现金？','年假为十五天。'), [])
    def test_unrelated(self):
        self.assertEqual(lexical_evidence_terms('火星大气中的氩气比例是多少？','公司年假申请须主管审批。'), [])
    def test_overlapping_terms_do_not_count_twice(self):
        self.assertEqual(lexical_evidence_terms('数据库','数据库'), [])
    def test_repeated_term_is_not_two_terms(self):
        self.assertEqual(lexical_evidence_terms('年假年假','年假'), [])
