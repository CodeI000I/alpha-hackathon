"""Validated inputs, evidence and model outputs. Go JSON aliases stay unchanged."""

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def canonical(value: Any) -> str:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode='json', by_alias=True)
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


class WireModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='ignore')


class News(WireModel):
    id: int = Field(gt=0)
    source_id: str = Field(alias='sourceId', min_length=1, max_length=100)
    url: str = Field(default='', max_length=2000)
    title: str = Field(min_length=1, max_length=1000)
    summary: str = Field(default='', max_length=30000)
    body: str = Field(default='', max_length=100000)
    published_at: datetime = Field(alias='publishedAt')
    situation_id: str | None = Field(default=None, alias='situationId', max_length=200)
    modality: Literal['reported', 'announced', 'completed', 'unknown'] = 'unknown'
    as_of: datetime | None = Field(default=None, alias='asOf')

    @field_validator('published_at', 'as_of')
    @classmethod
    def aware(cls, value):
        if value is None:
            return value
        if value.tzinfo is None or value.year < 2000:
            raise ValueError('publishedAt must contain a timezone and a real publication date')
        return value.astimezone(timezone.utc)

    @property
    def analysis_time(self):
        return self.as_of or self.published_at

    @property
    def version(self) -> str:
        return digest(self)

    @property
    def text(self) -> str:
        return '\n'.join([self.title, self.summary, self.body])


class Fact(WireModel):
    id: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=6000)
    source: str = Field(min_length=1, max_length=500)
    source_version: str = Field(alias='sourceVersion', min_length=1, max_length=200)
    element: str = Field(default='', max_length=50)
    valid_from: datetime | None = Field(default=None, alias='validFrom')
    valid_to: datetime | None = Field(default=None, alias='validTo')
    observed_at: datetime | None = Field(default=None, alias='observedAt')
    modality: Literal['current', 'planned', 'hypothesis', 'historical'] = 'current'

    @model_validator(mode='after')
    def dates(self):
        dates = [d for d in (self.valid_from, self.valid_to) if d is not None]
        if any(d.tzinfo is None for d in dates):
            raise ValueError('fact dates must contain timezone')
        if len(dates) == 2 and self.valid_from > self.valid_to:
            raise ValueError('invalid fact interval')
        if self.observed_at is not None and self.observed_at.tzinfo is None:
            raise ValueError('observedAt must contain timezone')
        return self


class Company(WireModel):
    id: int = Field(gt=0)
    inn: str = Field(default='', max_length=20)
    name: str = Field(min_length=1, max_length=500)
    profile: dict[str, Any] = Field(default_factory=dict)
    facts: list[Fact] = Field(default_factory=list, max_length=500)

    @model_validator(mode='after')
    def size(self):
        if len(canonical(self.profile)) > 200000:
            raise ValueError('profile too large')
        ids = [fact.id for fact in self.facts]
        if len(set(ids)) != len(ids):
            raise ValueError('fact IDs must be unique within a company')
        return self

    @property
    def version(self):
        # Unrelated backend updatedAt/createdAt do not invalidate paid results.
        return digest(self)


class RankRequest(WireModel):
    news: News
    company: Company
    roles: list[str] = Field(min_length=1, max_length=9)

    @field_validator('roles')
    @classmethod
    def roles_valid(cls, value):
        if any(not role.strip() or len(role) > 80 for role in value):
            raise ValueError('invalid role')
        return sorted(set(value))


class Evidence(BaseModel):
    id: str
    kind: Literal['news', 'company']
    text: str
    source: str
    version: str
    element: str = ''
    modality: str = 'reported'


class RetrievalResult(BaseModel):
    evidence: list[Evidence]
    candidate_count: int
    dropped_fact_count: int
    lexical_matches: int
    truncated: bool

    def metadata(self):
        return self.model_dump(exclude={'evidence'})


class Output(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class Claim(Output):
    text: str = Field(min_length=1, max_length=1500)
    evidence_ids: list[str] = Field(min_length=1, max_length=12)


class Assessment(Output):
    score: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    reason: str = Field(min_length=1, max_length=2000)
    relevance: Literal['relevant', 'irrelevant', 'unknown']
    link_evidence_status: Literal['sufficient', 'missing', 'conflicting']
    relation_kind: Literal['direct', 'indirect', 'not_established']
    risk_supported: bool
    opportunity_supported: bool
    potential_impact_band: Literal['negligible', 'limited', 'project', 'material', 'critical', 'unknown']
    urgency_band: Literal['none', 'monitor', 'this_month', 'this_week', 'today', 'unknown']
    effect_horizon: Literal['already_or_now', 'within_month', 'within_quarter', 'later', 'unknown']
    primary_channel: Literal['demand', 'inputs', 'logistics', 'financing', 'fx', 'regulation', 'competition', 'strategy', 'other', 'not_established']
    strongest_company_fact: str
    strongest_candidate_link: Literal['not_listed', 'none']
    evidence_ids: list[str] = Field(max_length=12)
    causal_chain: list[Claim] = Field(max_length=6)
    mitigations: list[Claim] = Field(max_length=6)
    missing_facts: list[str] = Field(max_length=10)


class Report(Output):
    headline: str = Field(min_length=1, max_length=200)
    summary: str = Field(min_length=1, max_length=1200)
    facts: list[Claim] = Field(min_length=1, max_length=6)
    bank_view: list[Claim] = Field(max_length=5)
    conclusions: list[Claim] = Field(min_length=1, max_length=6)
    risks: list[Claim] = Field(max_length=5)
    opportunities: list[Claim] = Field(max_length=5)
    actions: list[str] = Field(max_length=6)
    missing_facts: list[str] = Field(max_length=10)
    clarification_question: str | None = Field(default=None, max_length=500)


class CaseStatePatch(Output):
    workflow: Literal['open', 'watching', 'closed'] | None = None
    pinned: bool | None = None
    mark_read: bool = False


class Answer(Output):
    text: str = Field(min_length=1, max_length=6000)
    evidence_ids: list[str] = Field(max_length=12)
    missing_facts: list[str] = Field(max_length=10)


def validate_citations(output: BaseModel, evidence: list[Evidence], *, both=False):
    available = {e.id: e.kind for e in evidence}
    used = set()

    def visit(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key == 'evidence_ids':
                    used.update(child)
                else:
                    visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(output.model_dump())
    if isinstance(output, Assessment) and output.strongest_company_fact != 'none':
        if available.get(output.strongest_company_fact) != 'company':
            raise ValueError('strongest_company_fact must reference company evidence')
    if used - available.keys():
        raise ValueError('unknown evidence reference')
    if both and {available[i] for i in used} != {'news', 'company'}:
        raise ValueError('both news and company evidence required')
