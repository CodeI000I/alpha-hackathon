"""Deterministic validation and version-aware synthesis for business issues."""

from collections.abc import Mapping
from datetime import datetime
import re

from orchestrator.models import digest

from .models import (
    BusinessIssue, CompanyImpact, EvidencePack, ImpactAssessment, IssueSynthesis,
    SnapshotSynthesis, SituationSnapshot,
)


def validate_claims(output, available_ids):
    """Reject every recursively nested claim that cites evidence outside its input set."""
    available_ids = set(available_ids)

    def visit(value):
        if hasattr(value, 'model_dump'):
            value = value.model_dump(mode='python')
        if isinstance(value, Mapping):
            if 'evidence_ids' in value:
                ids = value['evidence_ids']
                if not isinstance(ids, (list, tuple)) or any(not isinstance(i, str) for i in ids):
                    raise ValueError('claim evidence_ids must be a list of strings')
                unknown = set(ids) - available_ids
                if unknown:
                    raise ValueError(f'unknown claim evidence references: {", ".join(sorted(unknown))}')
            for item in value.values():
                visit(item)
        elif isinstance(value, (list, tuple, set)):
            for item in value:
                visit(item)

    visit(output)


def validate_assessment(assessment: ImpactAssessment, pack: EvidencePack):
    """Validate evidence references and the assessment's basic logical consistency."""
    facts = {fact.fact_id for fact in pack.company_facts}
    paths = {path.path_id for path in pack.candidate_paths}
    for path in pack.candidate_paths:
        unknown_refs = set(path.evidence_refs) - pack.evidence_ids
        if unknown_refs:
            raise ValueError(f'unknown path evidence references: {", ".join(sorted(unknown_refs))}')
    unknown_facts = set(assessment.supporting_fact_ids) - facts
    unknown_paths = set(assessment.supporting_path_ids) - paths
    if unknown_facts or unknown_paths:
        unknown = sorted(unknown_facts | unknown_paths)
        raise ValueError(f'unknown assessment references: {", ".join(unknown)}')
    validate_claims(assessment.causal_chain, pack.evidence_ids)

    if assessment.relevance == 'irrelevant' and (
            assessment.risk_supported == 'yes' or assessment.opportunity_supported == 'yes'):
        raise ValueError('irrelevant assessment cannot support an impact')
    if assessment.relevance == 'relevant' and assessment.link_type == 'unknown':
        raise ValueError('relevant assessment requires an established link type')


def route_assessment(assessment: ImpactAssessment, pack: EvidencePack):
    """Route conservatively: missing or unknown grounds never become irrelevant."""
    try:
        validate_assessment(assessment, pack)
    except ValueError:
        return 'inconsistent'
    if assessment.evidence_sufficiency == 'conflicting':
        return 'inconsistent'
    if pack.event.status in {'cancelled', 'superseded'} and assessment.relevance == 'relevant':
        return 'inconsistent'
    supported_facts = {fact.fact_id: fact for fact in pack.company_facts}
    if any(supported_facts[fact_id].status == 'conflicting'
           for fact_id in assessment.supporting_fact_ids):
        return 'inconsistent'
    if any(supported_facts[fact_id].modality == 'hypothesis'
           or supported_facts[fact_id].verification_status == 'unverified'
           for fact_id in assessment.supporting_fact_ids):
        return 'needs_context'
    if any(not supported_facts[fact_id].applicable(pack.as_of)
           for fact_id in assessment.supporting_fact_ids):
        return 'needs_context'
    if any(path.status != 'supported' for path in pack.candidate_paths
           if path.path_id in assessment.supporting_path_ids):
        return 'needs_context'
    if assessment.relevance == 'unknown' or assessment.evidence_sufficiency == 'insufficient':
        return 'needs_context'
    if assessment.relevance == 'irrelevant':
        return ('irrelevant' if assessment.evidence_sufficiency == 'sufficient'
                else 'needs_context')
    if assessment.link_type == 'unknown':
        return 'needs_context'
    if assessment.risk_supported == 'unknown' and assessment.opportunity_supported == 'unknown':
        return 'needs_context'
    if not (assessment.supporting_fact_ids or assessment.supporting_path_ids):
        return 'needs_context'
    return 'accepted'


def _text_key(text):
    return re.sub(r'\s+', ' ', text).strip().casefold()


def _normalize_strings(value):
    if isinstance(value, str):
        return re.sub(r'\s+', ' ', value).strip()
    if isinstance(value, list):
        return [_normalize_strings(item) for item in value]
    if isinstance(value, dict):
        return {key: _normalize_strings(item) for key, item in value.items()}
    return value


def _temporal_state(pack, as_of):
    event = pack.event
    if event.status != 'active':
        event_state = event.status
    elif event.effective_from and as_of < event.effective_from:
        event_state = 'upcoming'
    elif event.effective_until and as_of >= event.effective_until:
        event_state = 'expired'
    else:
        event_state = 'active'
    return dict(
        event=event_state,
        applicable_facts=sorted(f.fact_id for f in pack.company_facts if f.applicable(as_of)),
        supported_paths=sorted(p.path_id for p in pack.candidate_paths if p.status == 'supported'),
    )


def semantic_fingerprint(value, *, as_of: datetime | None = None):
    """Hash substantive inputs; assessment summary whitespace/style is intentionally ignored."""
    if isinstance(value, CompanyImpact):
        assessment = _normalize_strings(value.assessment.model_dump(mode='json', exclude={'summary'}))
        # The evidence pack's as_of timestamp alone is not a change; only applicability transitions are.
        pack = value.evidence.model_dump(mode='json', exclude={'as_of', 'retrieval'})
        pack['news'] = [{key: val for key, val in news.items() if key != 'received_at'}
                        for news in pack['news']]
        pack = _normalize_strings(pack)
        return digest(dict(
            impact_id=value.impact_id, event_id=value.event_id, event_revision=value.event_revision,
            knowledge_revision=value.company_knowledge_revision, route=value.route,
            policy=value.policy_version, context=getattr(value, 'context_version', ''),
            assessment=assessment, evidence=pack,
            temporal=_temporal_state(value.evidence, as_of or value.evidence.as_of),
        ))
    if isinstance(value, BusinessIssue):
        return value.semantic_key
    return digest(value)


def issue_identity(impact: CompanyImpact) -> str:
    """Stable grouping key; broad factors alone never merge distinct events."""
    assessment, pack = impact.assessment, impact.evidence
    supporting = {fact.fact_id: fact for fact in pack.company_facts}
    exposure = _text_key(assessment.exposure)
    if not exposure or not any(
            fact_id in supporting and supporting[fact_id].status == 'known'
            and supporting[fact_id].modality == 'current_fact'
            and supporting[fact_id].verification_status != 'unverified'
            and supporting[fact_id].applicable(pack.as_of)
            and _text_key(supporting[fact_id].exposure) == exposure
            for fact_id in assessment.supporting_fact_ids):
        exposure = ''
    return digest(dict(
        company=pack.company_id, exposure=exposure,
        event=None if exposure else impact.event_id,
        factors=sorted(set(assessment.business_factors)), horizon=assessment.impact_horizon,
    ))


def _effect(impacts):
    risks = {i.assessment.risk_supported for i in impacts}
    opportunities = {i.assessment.opportunity_supported for i in impacts}
    risk_yes, opportunity_yes = 'yes' in risks, 'yes' in opportunities
    if risk_yes and opportunity_yes:
        return 'mixed'
    if risk_yes:
        return 'risk'
    if opportunity_yes:
        return 'opportunity'
    if 'unknown' in risks or 'unknown' in opportunities:
        return 'unknown'
    return 'neutral'


def _urgency(impacts):
    rank = {'unknown': 0, 'none': 1, 'monitor': 2, 'soon': 3, 'immediate': 4}
    return max((i.assessment.urgency for i in impacts), key=rank.__getitem__)


def _magnitude(impacts):
    rank = {'unknown': 0, 'low': 1, 'medium': 2, 'high': 3}
    return max((i.assessment.impact_magnitude for i in impacts), key=rank.__getitem__)


def _impact_versions(impacts, versions):
    supplied = versions or {}
    return {i.impact_id: supplied.get(i.impact_id, i.event_revision)
            for i in sorted(impacts, key=lambda item: item.impact_id)}


def _supported_exposure(impact):
    target = _text_key(impact.assessment.exposure)
    if target and any(f.fact_id in impact.assessment.supporting_fact_ids
                      and f.status == 'known' and f.modality == 'current_fact'
                      and f.applicable(impact.evidence.as_of)
                      and _text_key(f.exposure) == target for f in impact.evidence.company_facts):
        return impact.assessment.exposure
    return ''


def _deterministic_issue(impact, *, issue_id, company_id, as_of, impact_versions, semantic_key,
                         version=1):
    assessment, event = impact.assessment, impact.evidence.event
    title = f'{event.subject}: {event.action}'[:250]
    return BusinessIssue(
        issue_id=issue_id, company_id=company_id, title=title, summary=assessment.summary,
        overall_effect=_effect([impact]), evidence_sufficiency=assessment.evidence_sufficiency,
        key_unknowns=assessment.missing_factors, conditions=assessment.conditions,
        suggested_action=assessment.suggested_action, claims=assessment.causal_chain,
        business_factors=sorted(set(assessment.business_factors)),
        exposure=_supported_exposure(impact), horizon=assessment.impact_horizon,
        event_ids=[impact.event_id], impact_ids=[impact.impact_id],
        impact_versions=_impact_versions([impact], impact_versions),
        status='active', urgency=assessment.urgency, version=version, as_of=as_of,
        semantic_key=semantic_key, evidence_ids=sorted(impact.evidence.evidence_ids),
        impact_magnitude=_magnitude([impact]),
    )


ISSUE_PROMPT = '''Объедини оценки нескольких различных событий в один конкретный вопрос компании.
Используй только переданные факты и доказательства. Не складывай и не перемножай вероятности,
не выводи численные вероятности или финансовые величины. Риск и возможность могут сосуществовать;
не превращай неизвестное или отсутствие данных в отрицательное утверждение. Гипотезы о факторах
не называй фактами компании. Каждый причинный вывод в claims должен ссылаться на evidence_ids.
Сохрани условия, противоречия и существенные неизвестные. Верни типизированный IssueSynthesis.'''


def synthesize_issue(llm, impacts: list[CompanyImpact], *, issue_id, company_id, as_of,
                     previous=None, impact_versions=None) -> BusinessIssue:
    if not impacts:
        raise ValueError('at least one impact is required')
    selected = {}
    for impact in impacts:
        route = route_assessment(impact.assessment, impact.evidence)
        if route != 'accepted':
            raise ValueError(f'impact {impact.impact_id} is not accepted: {route}')
        if impact.evidence.company_id != company_id:
            raise ValueError('impact company does not match issue company')
        current = selected.get(impact.event_id)
        if current is None or (impact.event_revision, impact.company_knowledge_revision, impact.generated_at) > (
                current.event_revision, current.company_knowledge_revision, current.generated_at):
            selected[impact.event_id] = impact
    impacts = sorted(selected.values(), key=lambda item: item.event_id)
    if len({i.company_knowledge_revision for i in impacts}) > 1:
        raise ValueError('impacts use different company knowledge revisions')
    if len({i.policy_version for i in impacts}) > 1:
        raise ValueError('impacts use different policy versions')
    if previous and (previous.issue_id != issue_id or previous.company_id != company_id):
        raise ValueError('previous issue does not match the requested identity')
    version_map = _impact_versions(impacts, impact_versions)
    semantic_key = digest([semantic_fingerprint(i, as_of=as_of) for i in impacts])
    if previous is not None and previous.semantic_key == semantic_key:
        return previous
    if len(impacts) == 1:
        return _deterministic_issue(impacts[0], issue_id=issue_id, company_id=company_id,
                                    as_of=as_of, impact_versions=version_map,
                                    semantic_key=semantic_key,
                                    version=1 if previous is None else previous.version + 1)

    evidence_ids = {e for impact in impacts for e in impact.evidence.evidence_ids}
    context = dict(
        company_id=company_id, as_of=as_of.isoformat(),
        impacts=[dict(impact_id=i.impact_id, event_id=i.event_id,
                      assessment=i.assessment.model_dump(mode='json'),
                      event=i.evidence.event.model_dump(mode='json'),
                      facts=[f.model_dump(mode='json') for f in i.evidence.company_facts],
                      paths=[p.model_dump(mode='json') for p in i.evidence.candidate_paths],
                      news=[n.model_dump(mode='json') for n in i.evidence.news],
                      chunks=[c.model_dump(mode='json') for c in i.evidence.chunks])
                 for i in impacts],
    )
    synthesis: IssueSynthesis = llm.structured(
        'analysis', ISSUE_PROMPT, context, IssueSynthesis,
        lambda output: validate_claims(output, evidence_ids),
    )
    supported_effect = _effect(impacts)
    if synthesis.overall_effect != supported_effect:
        synthesis = synthesis.model_copy(update={'overall_effect': supported_effect})
    return BusinessIssue(
        **synthesis.model_dump(mode='python'), issue_id=issue_id, company_id=company_id,
        business_factors=sorted({f for i in impacts for f in i.assessment.business_factors}),
        exposure=next((_supported_exposure(i) for i in impacts if _supported_exposure(i)), ''),
        horizon=max((i.assessment.impact_horizon for i in impacts),
                    key={'unknown': 0, 'long': 1, 'medium': 2, 'short': 3}.__getitem__),
        event_ids=[i.event_id for i in impacts], impact_ids=[i.impact_id for i in impacts],
        impact_versions=version_map, status='active', urgency=_urgency(impacts),
        version=1 if previous is None else previous.version + 1, as_of=as_of,
        semantic_key=semantic_key, evidence_ids=sorted(evidence_ids),
        impact_magnitude=_magnitude(impacts),
    )


SNAPSHOT_PROMPT = '''Подготовь краткий общий обзор текущего положения компании по активным ситуациям.
Передавай только подкреплённые выводы; гипотезы и неизвестное сохраняй как неизвестное, не превращай
их в отрицательные факты. Не суммируй вероятности и не выдумывай численные последствия. Сохрани
одновременно существующие риски и возможности. Claims должны ссылаться на переданные evidence_ids.'''


def _version_id(issue):
    return f'{issue.issue_id}:v{issue.version}'


def _active_issues(issues):
    return sorted((i for i in issues if i.status in {'active', 'watching'}),
                  key=lambda i: i.issue_id)


def _urgency_rank(value):
    return {'unknown': 0, 'none': 1, 'monitor': 2, 'soon': 3, 'immediate': 4}.get(value, 0)


def _magnitude_rank(issue):
    value = getattr(issue, 'impact_magnitude', 'unknown')
    return {'unknown': 0, 'low': 1, 'medium': 2, 'high': 3}.get(value, 0)


def _changes(issues, previous):
    current = {i.issue_id: i for i in issues}
    old = {}
    if previous:
        for value in previous.issue_version_ids:
            issue_id, sep, version = value.rpartition(':v')
            if sep:
                old[issue_id] = int(version)
    changes = []
    for issue in issues:
        if issue.issue_id not in old:
            changes.append(dict(issue_id=issue.issue_id, change_type='new',
                                description=f'Добавлена ситуация: {issue.title}.'))
        elif old[issue.issue_id] != issue.version:
            changes.append(dict(issue_id=issue.issue_id, change_type='updated',
                                description=f'Обновлена ситуация: {issue.title}.'))
    for issue_id in sorted(old.keys() - current.keys()):
        changes.append(dict(issue_id=issue_id, change_type='no_longer_active',
                            description='Ситуация больше не входит в активный набор.'))
    return changes


def _snapshot_key(issues, company_id, role, knowledge_revision, policy_version):
    return dict(company_id=company_id, role=role, knowledge_revision=knowledge_revision,
                policy_version=policy_version,
                issue_versions=sorted(_version_id(i) for i in issues),
                temporal=sorted((i.issue_id, i.status, i.urgency, i.horizon,
                                 i.impact_magnitude,
                                 i.evidence_sufficiency) for i in issues))


def snapshot_fingerprint(issues, *, company_id, role, knowledge_revision, policy_version):
    """Public semantic fingerprint for service-level snapshot invalidation."""
    active = _active_issues(issues)
    return digest(_snapshot_key(active, company_id, role, knowledge_revision, policy_version))


def _previous_snapshot_key(previous):
    versions = []
    for value in previous.issue_version_ids:
        issue_id, sep, version = value.rpartition(':v')
        if sep:
            versions.append((issue_id, int(version)))
    temporal = [(p['issue_id'], p.get('status', 'active'), p.get('urgency', 'unknown'),
                 p.get('horizon', 'unknown'), p.get('impact_magnitude', 'unknown'),
                 p.get('evidence_sufficiency', 'insufficient'))
                for p in previous.priority_issues]
    return dict(company_id=previous.company_id, role=previous.role,
                knowledge_revision=previous.company_knowledge_revision,
                policy_version=previous.policy_version,
                issue_versions=sorted(previous.issue_version_ids),
                temporal=sorted(temporal))


def synthesize_snapshot(llm, issues, *, company_id, role, knowledge_revision, as_of,
                        news_processed_through, policy_version, previous=None):
    if previous and (previous.company_id != company_id or previous.role != role):
        raise ValueError('previous snapshot does not match the requested company and role')
    active = _active_issues(issues)
    current_key = _snapshot_key(active, company_id, role, knowledge_revision, policy_version)
    previous_key = _previous_snapshot_key(previous) if previous else None
    if previous and current_key == previous_key:
        return previous.model_copy(update=dict(as_of=as_of,
                                               news_processed_through=news_processed_through))

    ordered = sorted(active, key=lambda i: (-_urgency_rank(i.urgency), -_magnitude_rank(i), i.issue_id))
    priorities = [dict(issue_id=i.issue_id, issue_version=i.version, reason=i.summary,
                       action_required=i.urgency in {'immediate', 'soon'}, status=i.status,
                       urgency=i.urgency, horizon=i.horizon,
                       evidence_sufficiency=i.evidence_sufficiency,
                       impact_magnitude=getattr(i, 'impact_magnitude', 'unknown'))
                  for i in ordered]
    changes = _changes(active, previous)
    if not active:
        overall = SnapshotSynthesis(summary='Сейчас нет существенных активных бизнес-ситуаций.',
                                     key_unknowns=[], actions=[])
    elif len(active) == 1:
        issue = active[0]
        overall = SnapshotSynthesis(summary=issue.summary, key_unknowns=issue.key_unknowns,
                                     actions=[issue.suggested_action] if issue.suggested_action else [],
                                     claims=issue.claims)
    else:
        available = {e for issue in active for e in issue.evidence_ids}
        context = dict(company_id=company_id, role=role, as_of=as_of.isoformat(),
                       company_knowledge_revision=knowledge_revision,
                       policy_version=policy_version, changes_since_previous=changes,
                       issues=[i.model_dump(mode='json') for i in ordered])
        overall: SnapshotSynthesis = llm.structured(
            'analysis', SNAPSHOT_PROMPT, context, SnapshotSynthesis,
            lambda output: validate_claims(output, available),
        )

    return SituationSnapshot(
        snapshot_id=digest([company_id, role]), company_id=company_id, role=role,
        as_of=as_of, news_processed_through=news_processed_through,
        company_knowledge_revision=knowledge_revision,
        issue_version_ids=[_version_id(i) for i in ordered], overall=overall,
        priority_issues=priorities, changes_since_previous=changes,
        snapshot_version=1 if previous is None else previous.snapshot_version + 1,
        policy_version=policy_version,
    )
