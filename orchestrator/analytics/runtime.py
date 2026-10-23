"""Explicit runtime configuration; imports do not connect to any service."""

from contextlib import contextmanager, ExitStack
import os
from pathlib import Path
from typing import Literal

from dotenv import dotenv_values
from pydantic import Field, SecretStr

from orchestrator.config import ROOT, load_settings
from orchestrator.llm import LLMClient
from .embeddings import SentenceTransformerEmbeddingProvider
from .knowledge import HybridRetriever, KnowledgeService
from .models import Model
from .service import AnalyticsService
from .store import PostgresStore


class AnalyticsSettings(Model):
    database_url: SecretStr
    object_dir: Path = ROOT / 'orchestrator/data/documents'
    embedding_backend: Literal['lexical', 'local'] = 'lexical'
    embedding_model_path: Path | None = None
    embedding_model: str = 'sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2'
    embedding_version: str = 'e8f8c211226b894fcb81acc59f3b34ba3efd5f42'
    top_k: int = Field(default=12, ge=1, le=100)
    graph_depth: int = Field(default=2, ge=0, le=4)
    graph_enabled: bool = True
    graphify_enabled: bool = False
    graphify_json_path: Path | None = None
    debounce_seconds: int = Field(default=30, ge=0, le=3600)
    max_job_attempts: int = Field(default=3, ge=1, le=10)
    checkpoints: bool = True
    operational_retention_days: int = Field(default=30, ge=1, le=3650)


def load_analytics_settings(env_file=None):
    values = {**dotenv_values(env_file or ROOT / '.env.local', interpolate=False), **os.environ}
    options = {}
    for name in AnalyticsSettings.model_fields:
        value = values.get('ANALYTICS_' + name.upper())
        if value is not None and value.strip():
            options[name] = value
    for name in ('embedding_backend', 'embedding_model_path', 'embedding_model', 'embedding_version'):
        value = values.get(name.upper())
        if value is not None and value.strip():
            options[name] = value
    if not options.get('database_url'):
        raise ValueError('ANALYTICS_DATABASE_URL is required; no default database is used')
    settings = AnalyticsSettings(**options)
    if settings.embedding_backend == 'local' and settings.embedding_model_path is None:
        raise ValueError('EMBEDDING_MODEL_PATH is required for local embeddings')
    if settings.graphify_enabled and settings.graphify_json_path is None:
        raise ValueError('ANALYTICS_GRAPHIFY_JSON_PATH is required when Graphify import is enabled')
    return settings


class ReadOnlyModel:
    def __init__(self, settings):
        self.settings = settings

    def structured(self, *_args, **_kwargs):
        raise RuntimeError('This command only reads persisted results')


@contextmanager
def runtime(*, read_only=False, env_file=None):
    config = load_analytics_settings(env_file)
    model_settings = load_settings(env_file)
    store = PostgresStore(config.database_url.get_secret_value(), connect_timeout=5, statement_timeout_ms=10000)
    with ExitStack() as stack:
        llm = ReadOnlyModel(model_settings) if read_only else LLMClient(model_settings, store)
        if not read_only:
            stack.callback(llm.close)
        embeddings = None
        if config.embedding_backend == 'local':
            embeddings = SentenceTransformerEmbeddingProvider(config.embedding_model_path,
                model_id=config.embedding_model, version=config.embedding_version)
        checkpointer = None
        if config.checkpoints and not read_only:
            from langgraph.checkpoint.postgres import PostgresSaver
            checkpointer = stack.enter_context(PostgresSaver.from_conn_string(config.database_url.get_secret_value()))
            # Schema creation is an explicit migration command, not a serving side effect.
        retriever = HybridRetriever(store, embeddings=embeddings, top_k=config.top_k,
                                    max_depth=config.graph_depth, use_graph=config.graph_enabled)
        knowledge = KnowledgeService(store, llm, embeddings=embeddings, object_dir=config.object_dir,
                                     graph_extractor=config.graphify_json_path if config.graphify_enabled else None)
        yield AnalyticsService(store, llm, retriever=retriever, knowledge=knowledge, checkpointer=checkpointer,
                               debounce_seconds=config.debounce_seconds, max_job_attempts=config.max_job_attempts)


def migrate(config):
    from .migrate import apply_migrations
    dsn = config.database_url.get_secret_value()
    result = apply_migrations(dsn, connect_timeout=5, statement_timeout_ms=10000)
    if config.checkpoints:
        from langgraph.checkpoint.postgres import PostgresSaver
        with PostgresSaver.from_conn_string(dsn) as checkpointer:
            checkpointer.setup()
    return result


def cleanup(config):
    from datetime import timedelta
    from .models import utcnow
    store = PostgresStore(config.database_url.get_secret_value(), connect_timeout=5, statement_timeout_ms=10000)
    return store.cleanup_operational(utcnow() - timedelta(days=config.operational_retention_days),
                                     checkpoints=config.checkpoints)
