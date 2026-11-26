import unittest
from unittest.mock import Mock
from src.retrieval.embeddings import OllamaVectors, IndexSettings


class EmbeddingTests(unittest.TestCase):
    def test_validation_and_dimension(self):
        backend=OllamaVectors.__new__(OllamaVectors)
        backend.dimension=None
        backend.client=Mock()
        backend.client.embed_documents.return_value=[[1.0,0.0],[0.0,1.0]]
        self.assertEqual(len(backend.embed_documents(["中文甲","中文乙"])),2)
        self.assertEqual(backend.dimension,2)
        backend.client.embed_query.return_value=[1.0,0.0]
        self.assertEqual(backend.embed_query("中文问题"),[1.0,0.0])
        for bad in ([[1.0]], [[float('nan'),0]], [], [[1,0],[1]]):
            with self.assertRaises(ValueError): backend._validate(bad,1)

    def test_model_and_split_changes_invalidate_key(self):
        base=IndexSettings()
        self.assertNotEqual(base.key,IndexSettings(model="new-model").key)
        self.assertNotEqual(base.key,IndexSettings(revision="changed").key)
        self.assertNotEqual(base.key,IndexSettings(chunk_size=900).key)


if __name__=="__main__": unittest.main()
