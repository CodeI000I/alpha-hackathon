import unittest

from orchestrator.analytics.embeddings import EmbeddingError, SentenceTransformerEmbeddingProvider


class EmbeddingProviderTests(unittest.TestCase):
    def test_requires_an_explicit_local_model_path(self):
        with self.assertRaises(EmbeddingError):
            SentenceTransformerEmbeddingProvider('/missing/model', model_id='test', version='1')

    def test_uses_injected_model_and_returns_finite_vectors(self):
        class Model:
            def encode(self, texts, **kwargs):
                return [[1.0, 2.0] for _ in texts]

        provider = SentenceTransformerEmbeddingProvider(
            '.', model_id='fixture', version='v1', model=Model()
        )
        vectors = provider.embed(['поставщик', 'логистика'])

        self.assertEqual(vectors, [[1.0, 2.0], [1.0, 2.0]])

    def test_rejects_empty_input_and_bad_model_output(self):
        class BadModel:
            def encode(self, texts, **kwargs):
                return [[0.0, float('nan')] for _ in texts]

        provider = SentenceTransformerEmbeddingProvider(
            '.', model_id='fixture', version='v1', model=BadModel()
        )
        with self.assertRaises(ValueError):
            provider.embed([])
        with self.assertRaises(EmbeddingError):
            provider.embed(['text'])


if __name__ == '__main__':
    unittest.main()
