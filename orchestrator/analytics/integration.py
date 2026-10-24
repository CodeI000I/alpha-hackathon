"""Adapters for the existing Go contracts; analytics remains the only inference path."""

from pydantic import Field

from orchestrator.models import Company, News, RankRequest, digest
from .models import CompanyFact, CompanyProfile, NewsArticle, Scope


class BackendNews(News):
    revision: int = Field(default=1, ge=1)


class BackendRankRequest(RankRequest):
    news: BackendNews


def sync_company(service, value):
    company = value if isinstance(value, Company) else Company.model_validate(value)
    scope = Scope(tenant_id='alpha', company_id=str(company.id))
    # Use the same bounded profile chunks as the existing lexical retriever. Values
    # are user assertions, never source-supported facts or inferred graph edges.
    from orchestrator.retrieval import profile_evidence
    facts = [CompanyFact(
        fact_id='backend-profile:' + digest(item.id), text=item.text,
        subject_id=str(company.id), predicate='profile_value', object_id=item.element,
        qualifiers={'element': item.element}, verification_status='user_asserted',
    ) for item in profile_evidence(company)]
    with service._company_lock(scope):
        old = service.store.get('company', scope.company_id, **scope.db())
        previous = CompanyProfile.model_validate(old.payload) if old else None
        if previous and previous.name == company.name and previous.profile == company.profile and previous.aliases == [company.inn]:
            return scope
        retained = [fact for fact in previous.facts if not fact.fact_id.startswith('backend-profile:')] if previous else []
        profile = CompanyProfile(name=company.name, aliases=[company.inn], profile=company.profile,
                                 facts=retained + facts,
                                 subscriptions=previous.subscriptions if previous else [])
        service.update_company_profile(scope, profile, expected_revision=old.version if old else 0)
    return scope


def rank(service, request: BackendRankRequest, *, company=None):
    scope = sync_company(service, company or request.company)
    news = request.news
    article = NewsArticle(
        source=news.source_id, news_id=str(news.id), revision=news.revision,
        title=news.title, content=news.text, published_at=news.published_at,
        source_url=news.url or None,
        metadata={'backend_news_id': news.id, 'content_status': 'full' if news.body else 'metadata_only'},
    )
    event_id = service.ingest_news(article)['event_id']
    impact = service.analyze_event_for_company(scope, event_id)
    for role in request.roles:
        service.refresh_snapshot(scope.model_copy(update={'role': role}))
    if impact.route != 'accepted':
        return []
    assessment = impact.assessment
    risk, opportunity = assessment.risk_supported == 'yes', assessment.opportunity_supported == 'yes'
    kind = 'risk' if risk and not opportunity else 'opportunity' if opportunity and not risk else 'event'
    # The legacy UI requires a score. This is an ordinal sort key, not probability.
    score = {'none': 0.0, 'unknown': 0.25, 'monitor': 0.5, 'soon': 0.8, 'immediate': 1.0}[assessment.urgency]
    supported = set(assessment.supporting_fact_ids)
    elements = sorted({fact.qualifiers['element'] for fact in impact.evidence.company_facts
                       if fact.fact_id in supported and fact.qualifiers.get('element')})
    return [dict(role=role, kind=kind, score=score, insight=assessment.summary, elements=elements)
            for role in request.roles]
