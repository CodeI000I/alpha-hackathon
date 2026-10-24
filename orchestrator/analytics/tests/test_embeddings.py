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

    def test_long_inputs_are_windowed_and_tail_changes_affect_aggregated_embedding(self):
        class Tokenizer:
            def encode(self, text, add_special_tokens=False):
                return [int(token) for token in text.split()]

            def num_special_tokens_to_add(self, pair=False):
                return 2

            def decode(self, tokens, skip_special_tokens=True):
                return ' '.join(str(token) for token in tokens)

        class Model:
            max_seq_length = 4
            tokenizer = Tokenizer()

            def __init__(self):
                self.batches = []

            def encode(self, texts, **kwargs):
                self.batches.append(list(texts))
                return [[float(sum(self.tokenizer.encode(text))),
                         float(sum(token * token for token in self.tokenizer.encode(text)))]
                        for text in texts]

        model = Model()
        provider = SentenceTransformerEmbeddingProvider('.', model_id='fixture', version='v1', model=model)

        first = provider.embed(['1 2 3 4 5 6'])[0]
        changed_tail = provider.embed(['1 2 3 4 5 7'])[0]

        self.assertEqual(model.batches[0], ['1 2', '3 4', '5 6'])
        self.assertNotEqual(first, changed_tail)
        self.assertEqual(provider.version, 'v1:token-windows-v1')


if __name__ == '__main__':
    unittest.main()
