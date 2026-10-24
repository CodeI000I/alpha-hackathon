"""Offline lexical baseline; no unsupported embedding API or LLM extraction."""

import re

from rank_bm25 import BM25Plus
from snowballstemmer import stemmer

from .models import Company, Evidence, News, RetrievalResult, canonical, digest

_stop = set('и в во на по из за для с со от до а но или как что это при о об к не'.split())


def tokens(text: str) -> list[str]:
    words = re.findall(r'[\w]+', text.lower().replace('ё', 'е'))
    # Snowball instances have mutable buffers; don't share one across HTTP threads.
    return stemmer('russian').stemWords([w for w in words if len(w) > 2 and w not in _stop])


def profile_evidence(company: Company):
    """Bounded, traceable profile values shared by legacy and integrated analytics."""
    for key, value in sorted(company.profile.items()):
        text = value if isinstance(value, str) else canonical(value)
        for i in range(0, len(text), 4000):
            yield Evidence(id=f'profile:{company.id}:{key}:{i // 4000}', kind='company',
                           text=text[i:i+4000], source=f'company.profile.{key}',
                           version=digest(value), element=key)


class Retriever:
    # shortcut: lexical retrieval with core facts; add dense search if measured recall is insufficient.
    version = 'bm25plus-core-v2'

    def retrieve(self, news: News, company: Company, top_k: int, *, query: str | None = None) -> RetrievalResult:
        candidates = [Evidence(
            id=f'company:{company.id}:identity', kind='company',
            text=f'{company.name}; ИНН {company.inn}', source='company:identity', version=company.version,
        )]
        candidates.extend(profile_evidence(company))
        for fact in company.facts:
            if fact.valid_from and fact.valid_from > news.analysis_time:
                continue
            if fact.valid_to and fact.valid_to < news.analysis_time:
                continue
            if fact.observed_at and fact.observed_at > news.analysis_time:
                continue
            candidates.append(Evidence(
                id=f'fact:{company.id}:{fact.id}', kind='company', text=fact.text,
                source=fact.source, version=fact.source_version, element=fact.element, modality=fact.modality,
            ))
        corpus = [tokens(e.text) or ['_empty_'] for e in candidates]
        query_tokens = tokens(query if query is not None else news.text)
        scores = BM25Plus(corpus).get_scores(query_tokens)
        overlap = [bool(set(query_tokens) & set(words)) for words in corpus]
        order = sorted(range(len(candidates)), key=lambda i: (-float(scores[i]), candidates[i].id))
        # Exact matches lead; remaining business facts keep indirect cases in the baseline.
        # An unrelated company name alone is not business context.
        order = [i for i in order if overlap[i]] + [i for i in order if not overlap[i] and i != 0]
        selected = [candidates[i] for i in order[:top_k]]
        dropped = max(0, len(order) - len(selected))
        # News is already verified by the bank; preserve its origin, don't re-fact-check it.
        evidence = [Evidence(id=f'news:{news.id}', kind='news', text=news.text,
                             source=news.url or news.source_id, version=news.version, modality=news.modality), *selected]
        return RetrievalResult(evidence=evidence, candidate_count=len(order), dropped_fact_count=dropped,
                               lexical_matches=sum(overlap), truncated=dropped > 0)
