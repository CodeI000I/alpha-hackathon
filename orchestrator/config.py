"""One server-side configuration source; secrets never enter graph state."""

import os
from pathlib import Path
from typing import Literal

from dotenv import dotenv_values
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError, model_validator

ROOT = Path(__file__).resolve().parent.parent
ModelID = Literal[
    'google/gemma-4-26b-a4b-it', 'z-ai/glm-5.3-flash',
    'qwen/qwen3.6-35b-a3b', 'deepseek/deepseek-v4.1-flash',
    'qwen/qwen3-vl-30b-a3b-instruct', 'moonshotai/kimi-k2.6',
]


class ConfigurationError(ValueError):
    pass


class Settings(BaseModel):
    model_config = ConfigDict(frozen=True)
    api_key: SecretStr = SecretStr('')
    base_url: str = 'https://changellenge.up.railway.app/v1'
    default_model: ModelID = 'deepseek/deepseek-v4.1-flash'
    decision_model: ModelID | None = None
    analysis_model: ModelID | None = None
    synthesis_model: ModelID | None = None
    chat_model: ModelID | None = None
    request_timeout_seconds: float = Field(default=60, gt=0, le=180)
    max_retries: int = Field(default=2, ge=0, le=3)
    max_retry_delay_seconds: float = Field(default=15, gt=0, le=60)
    max_concurrent_requests: int = Field(default=2, ge=1, le=8)
    requests_per_minute: int = Field(default=20, ge=1, le=120)
    max_output_tokens: int = Field(default=1800, ge=64, le=8192)
    max_input_chars: int = Field(default=32000, ge=1000, le=100000)
    retrieval_top_k: int = Field(default=8, ge=1, le=30)
    relevance_low: float = Field(default=0.35, ge=0, le=1)
    relevance_high: float = Field(default=0.7, ge=0, le=1)
    policy_version: str = 'bank-analysis-v1'
    db_path: Path = ROOT / 'orchestrator/data/analytics.sqlite3'
    service_token: SecretStr = SecretStr('')

    @model_validator(mode='after')
    def validate_policy(self):
        if self.relevance_low >= self.relevance_high:
            raise ValueError('relevance_low must be below relevance_high')
        # The team key must never be redirected to an arbitrary host via config.
        if self.base_url.rstrip('/') != 'https://changellenge.up.railway.app/v1':
            raise ValueError('unsupported gateway')
        return self

    def model_for(self, stage: str) -> str:
        if stage == 'analysis' and self.synthesis_model:
            return self.synthesis_model
        return getattr(self, f'{stage}_model', None) or self.default_model

    def require_key(self):
        value = self.api_key.get_secret_value().strip()
        if not value or value in {'ВСТАВЬ_КОМАНДНЫЙ_КЛЮЧ', 'PASTE_KEY_HERE'}:
            raise ConfigurationError('Вставьте командный ключ в AI_API_KEY файла .env.local.')


def load_settings(env_file: Path | None = None) -> Settings:
    path = env_file or ROOT / '.env.local'
    # No interpolation: a pasted key containing $ is read literally. Process env wins.
    values = {**dotenv_values(path, interpolate=False), **os.environ}
    options = {}
    for name in Settings.model_fields:
        value = values.get('AI_' + name.upper())
        if value is not None and value.strip():
            options[name] = value
    if 'db_path' in options:
        options['db_path'] = ROOT / options['db_path']
    try:
        return Settings(**options)
    except ValidationError as exc:
        fields = ', '.join(sorted({str(e['loc'][0]) for e in exc.errors() if e['loc']}))
        raise ConfigurationError(f'Проверьте настройки AI_: {fields}.') from None
