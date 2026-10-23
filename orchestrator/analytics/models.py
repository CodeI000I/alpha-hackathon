"""Versioned analytics contracts, separate from the existing Go /rank wire format."""

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from orchestrator.models import Answer, Claim, canonical, digest


def utcnow():
    return datetime.now(timezone.utc)


class Model(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Scope(Model):
    tenant_id: str = Field(min_length=1, max_length=200)
    company_id: str = Field(min_length=1, max_length=200)
    user_id: str = Field(default='system', min_length=1, max_length=200)
    role: str = Field(default='owner', min_length=1, max_length=80)

    def db(self):
        return dict(tenant_id=self.tenant_id, company_id=self.company_id)


Modality = Literal['realized', 'announcement', 'plan', 'forecast', 'proposal', 'unknown']
Factor = Literal['procurement_cost', 'supply_availability', 'logistics', 'demand',
                 'financing', 'market_expansion', 'regulation', 'competition',
                 'operations', 'workforce']
Sufficiency = Literal['sufficient', 'conditional', 'insufficient', 'conflicting']


class NewsArticle(Model):
    schema_version: str = '1.0'
    source: str = Field(default='alfabank', min_length=1, max_length=200)
    news_id: str = Field(min_length=1, max_length=200)
    revision: int = Field(default=1, ge=1)
    title: str = Field(min_length=1, max_length=1000)
    content: str = Field(min_length=1, max_length=200000)
    published_at: AwareDatetime
    received_at: AwareDatetime = Field(default_factory=utcnow)
    source_url: str | None = Field(default=None, max_length=2000)
    upstream_validated: Literal[True] = True
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def key(self):
        return digest([self.source, self.news_id])

    @property
    def evidence_id(self):
        return f'news:{self.key}:v{self.revision}'


class EventDraft(Model):
    event_type: str = Field(min_length=1, max_length=100)
    action: str = Field(min_length=1, max_length=300)
    subject: str = Field(min_length=1, max_length=500)
    modality: Modality = 'unknown'
    summary: str = Field(min_length=1, max_length=4000)
    entities: list[str] = Field(default_factory=list, max_length=50)
    affected_factors: list[Factor] = Field(default_factory=list)
    event_time: AwareDatetime | None = None
    effective_from: AwareDatetime | None = None
    effective_until: AwareDatetime | None = None
    project: str = Field(default='', max_length=300)
    conditions: dict[str, str] = Field(default_factory=dict)
    status: Literal['active', 'cancelled', 'superseded'] = 'active'
    evidence_quote: str = Field(min_length=1, max_length=6000)

    @model_validator(mode='after')
    def interval(self):
        if self.effective_from and self.effective_until and self.effective_from >= self.effective_until:
            raise ValueError('invalid event applicability interval')
        return self


class Event(EventDraft):
    schema_version: str = '1.0'
    event_id: str
    revision: int = 1
    source_news_ids: list[str] = Field(default_factory=list)
    extraction_version: str = 'event-v1'
    factor_status: Literal['hypothesis'] = 'hypothesis'


class SourceChunk(Model):
    chunk_id: str
    document_id: str
    document_revision: int
    text: str = Field(min_length=1)
    locator: str
    start: int = Field(default=0, ge=0)
    end: int = Field(ge=0)
    text_hash: str


class SourceDocument(Model):
    schema_version: str = '1.0'
    document_id: str = Field(min_length=1, max_length=200)
    revision: int = Field(default=1, ge=1)
    filename: str = Field(min_length=1, max_length=500)
    media_type: str
    text: str
    chunks: list[SourceChunk] = Field(default_factory=list)
    received_at: AwareDatetime = Field(default_factory=utcnow)
    status: Literal['received', 'ready', 'failed'] = 'received'
    error: str | None = None
    extraction_version: str = 'corporate-v1'
    original_path: str | None = None


class CompanyFact(Model):
    schema_version: str = '1.0'
    fact_id: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=6000)
    subject_id: str = Field(min_length=1, max_length=200)
    predicate: str = Field(min_length=1, max_length=100)
    object_id: str = Field(min_length=1, max_length=200)
    modality: Literal['current_fact', 'plan', 'hypothesis', 'historical'] = 'current_fact'
    qualifiers: dict[str, Any] = Field(default_factory=dict)
    business_factors: list[Factor] = Field(default_factory=list)
    exposure: str = Field(default='', max_length=300)
    status: Literal['known', 'unknown', 'not_applicable', 'conflicting', 'outdated'] = 'known'
    verification_status: Literal['source_supported', 'user_asserted', 'unverified'] = 'unverified'
    source_refs: list[str] = Field(default_factory=list, max_length=20)
    source_quote: str = Field(default='', max_length=6000)
    valid_from: AwareDatetime | None = None
    valid_until: AwareDatetime | None = None
    observed_at: AwareDatetime | None = None

    @model_validator(mode='after')
    def provenance(self):
        if self.verification_status == 'source_supported' and (not self.source_refs or not self.source_quote):
            raise ValueError('source-supported facts require a locator and quote')
        if self.valid_from and self.valid_until and self.valid_from >= self.valid_until:
            raise ValueError('invalid fact interval')
        if self.modality == 'hypothesis' and self.verification_status != 'unverified':
            raise ValueError('hypotheses cannot be confirmed facts')
        return self

    def applicable(self, as_of):
        return (self.status in {'known', 'conflicting'} and self.modality != 'historical'
                and (self.valid_from is None or self.valid_from <= as_of)
                and (self.valid_until is None or as_of < self.valid_until)
                and (self.observed_at is None or self.observed_at <= as_of))


class CompanyProfile(Model):
    schema_version: str = '1.0'
    knowledge_revision: int = Field(default=0, ge=0)
    name: str = Field(min_length=1, max_length=500)
    aliases: list[str] = Field(default_factory=list)
    profile: dict[str, Any] = Field(default_factory=dict)
    facts: list[CompanyFact] = Field(default_factory=list, max_length=500)
    subscriptions: list[Factor] = Field(default_factory=list)

    @model_validator(mode='after')
    def unique(self):
        if len({f.fact_id for f in self.facts}) != len(self.facts):
            raise ValueError('fact IDs must be unique')
        if len(canonical(self)) > 500000:
            raise ValueError('company profile exceeds input limit')
        return self


class KnowledgeEdge(Model):
    edge_id: str
    subject_id: str
    predicate: str
    object_id: str
    scope: Literal['private', 'global'] = 'private'
    evidence_refs: list[str] = Field(min_length=1)
    derivation: Literal['extracted', 'user_asserted', 'inferred'] = 'extracted'
    verification_status: Literal['source_supported', 'user_asserted', 'unverified'] = 'unverified'
    valid_from: AwareDatetime | None = None
    valid_until: AwareDatetime | None = None
    extractor_version: str = 'baseline-v1'


class CandidatePath(Model):
    path_id: str
    node_ids: list[str]
    relation_types: list[str]
    evidence_refs: list[str]
    status: Literal['supported', 'hypothesis'] = 'supported'


class EvidencePack(Model):
    schema_version: str = '1.0'
    tenant_id: str
    company_id: str
    event: Event
    as_of: AwareDatetime
    company_knowledge_revision: int
    news: list[NewsArticle]
    company_facts: list[CompanyFact]
    chunks: list[SourceChunk] = Field(default_factory=list)
    candidate_paths: list[CandidatePath] = Field(default_factory=list)
    related_events: list[str] = Field(default_factory=list)
    retrieval: dict[str, Any] = Field(default_factory=dict)

    @property
    def evidence_ids(self):
        return ({f.fact_id for f in self.company_facts} | {c.chunk_id for c in self.chunks}
                | {p.path_id for p in self.candidate_paths} | {n.evidence_id for n in self.news})


class ImpactAssessment(Model):
    relevance: Literal['relevant', 'irrelevant', 'unknown']
    evidence_sufficiency: Sufficiency
    link_type: Literal['direct', 'indirect', 'unknown']
    risk_supported: Literal['yes', 'no', 'unknown']
    opportunity_supported: Literal['yes', 'no', 'unknown']
    impact_magnitude: Literal['low', 'medium', 'high', 'unknown']
    urgency: Literal['none', 'monitor', 'soon', 'immediate', 'unknown']
    impact_horizon: Literal['short', 'medium', 'long', 'unknown']
    business_factors: list[Factor]
    supporting_fact_ids: list[str]
    supporting_path_ids: list[str]
    missing_factors: list[str]
    event_probability: None = None
    summary: str = Field(min_length=1, max_length=2500)
    causal_chain: list[Claim] = Field(default_factory=list, max_length=8)
    conditions: list[str] = Field(default_factory=list)
    suggested_action: str = Field(min_length=1, max_length=1500)
    exposure: str = Field(default='', max_length=300)


class CompanyImpact(Model):
    schema_version: str = '1.0'
    impact_id: str
    event_id: str
    event_revision: int
    company_knowledge_revision: int
    assessment: ImpactAssessment
    evidence: EvidencePack
    route: Literal['accepted', 'irrelevant', 'needs_context', 'inconsistent', 'failed']
    policy_version: str
    context_version: str = ''
    generated_at: AwareDatetime


class IssueSynthesis(Model):
    title: str = Field(min_length=1, max_length=250)
    summary: str = Field(min_length=1, max_length=4000)
    overall_effect: Literal['risk', 'opportunity', 'mixed', 'neutral', 'unknown']
    evidence_sufficiency: Sufficiency
    key_unknowns: list[str]
    conditions: list[str]
    suggested_action: str = Field(min_length=1, max_length=1500)
    claims: list[Claim] = Field(default_factory=list, max_length=12)


class BusinessIssue(IssueSynthesis):
    schema_version: str = '1.0'
    issue_id: str
    company_id: str
    business_factors: list[Factor]
    exposure: str
    horizon: str
    event_ids: list[str]
    impact_ids: list[str]
    impact_versions: dict[str, int] = Field(default_factory=dict)
    status: Literal['active', 'watching', 'resolved', 'superseded', 'archived'] = 'active'
    urgency: Literal['none', 'monitor', 'soon', 'immediate', 'unknown'] = 'unknown'
    impact_magnitude: Literal['low', 'medium', 'high', 'unknown'] = 'unknown'
    version: int = 1
    as_of: AwareDatetime
    semantic_key: str
    evidence_ids: list[str]


class SnapshotSynthesis(Model):
    summary: str = Field(min_length=1, max_length=5000)
    key_unknowns: list[str]
    actions: list[str]
    claims: list[Claim] = Field(default_factory=list, max_length=12)


class SituationSnapshot(Model):
    schema_version: str = '1.0'
    snapshot_id: str
    company_id: str
    role: str
    as_of: AwareDatetime
    news_processed_through: AwareDatetime | None
    company_knowledge_revision: int
    issue_version_ids: list[str]
    overall: SnapshotSynthesis
    priority_issues: list[dict[str, Any]]
    changes_since_previous: list[dict[str, str]]
    snapshot_version: int = 1
    policy_version: str
