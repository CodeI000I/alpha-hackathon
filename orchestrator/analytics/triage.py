"""Identity for optional advisory triage, also safe to compute in read-only commands."""

from orchestrator.decision import FALLBACK_INSTRUCTION, QUESTIONS, RoutingDecision
from orchestrator.models import digest


def triage_policy(settings):
    return digest(dict(version='advisory-triage-v1', questions=QUESTIONS,
        schema=RoutingDecision.model_json_schema(), primary_url=settings.systemone_url.rstrip('/'),
        primary_model=settings.systemone_model, timeout=settings.systemone_timeout_seconds,
        cooldown=settings.systemone_cooldown_seconds, rpm=settings.requests_per_minute,
        fallback_url=settings.base_url, fallback_instruction=FALLBACK_INSTRUCTION,
        fallback_model=settings.model_for('decision'), max_input_chars=settings.max_input_chars,
        max_output_tokens=settings.max_output_tokens, configured_version=settings.policy_version))
