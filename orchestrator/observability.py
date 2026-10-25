"""Content-free diagnostics for the existing LangGraph and plain OpenAI client."""

import json
import logging
from time import perf_counter

from langchain_core.callbacks import BaseCallbackHandler
from langgraph.config import get_config


LOG = logging.getLogger('orchestrator.quality')
_FIELDS = {
    'run_id', 'policy', 'node', 'span_id', 'parent_span_id', 'stage', 'model', 'schema',
    'cache_hit', 'validation_outcome', 'error_code', 'duration_ms', 'outcome', 'route',
}


def configure_logging():
    """Configure only this logger at the service entry point, once per process."""
    if not LOG.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter('%(message)s'))
        LOG.addHandler(handler)
    LOG.setLevel(logging.INFO)
    LOG.propagate = False


def log_event(event, **fields):
    # Never serialize runnable inputs, outputs, metadata wholesale, or exception text.
    try:
        metadata = get_config().get('metadata', {})
    except RuntimeError:
        metadata = {}
    context = {key: metadata[source] for key, source in (
        ('run_id', 'analytics_run_id'), ('policy', 'model_policy'), ('node', 'langgraph_node'),
    ) if source in metadata}
    context.update({key: value for key, value in fields.items() if key in _FIELDS})
    LOG.info(json.dumps({'event': event, **context}, ensure_ascii=False, sort_keys=True))


class GraphTrace(BaseCallbackHandler):
    """Observe the fixed impact graph without retaining evidence in the callback."""
    run_inline = True

    def __init__(self, run_id, policy):
        self.run_id, self.policy = run_id, policy
        self._started = {}
        self.failed_node = None

    def on_chain_start(self, serialized, inputs, *, run_id, parent_run_id=None,
                       metadata=None, **kwargs):
        node = (metadata or {}).get('langgraph_node')
        if node in {'retrieve', 'triage', 'assess', 'save'} and kwargs.get('name') == node:
            self._started[run_id] = (perf_counter(), node, parent_run_id)

    def _finish(self, run_id, outcome, *, error_code=None, route=None):
        started = self._started.pop(run_id, None)
        if started is None:
            return
        at, node, parent = started
        if outcome == 'error':
            self.failed_node = node
        log_event('graph_node', run_id=self.run_id, policy=self.policy, node=node,
                  span_id=str(run_id), parent_span_id=str(parent) if parent else None,
                  duration_ms=round((perf_counter() - at) * 1000), outcome=outcome,
                  error_code=error_code, route=route)

    def on_chain_end(self, outputs, *, run_id, **kwargs):
        route = outputs.get('route') if isinstance(outputs, dict) else None
        if route not in {'accepted', 'irrelevant', 'needs_context', 'inconsistent', 'failed'}:
            route = None
        self._finish(run_id, 'ok', route=route)

    def on_chain_error(self, error, *, run_id, **kwargs):
        self._finish(run_id, 'error', error_code=getattr(error, 'code', type(error).__name__))
