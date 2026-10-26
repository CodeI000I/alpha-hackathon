"""Bounded Chat Completions adapter; no SDK retries, tools or JSON-mode assumption."""

import hashlib
import json
import math
import random
import threading
import time
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo

import httpx
from openai import APIConnectionError, APIResponseValidationError, APIStatusError, APITimeoutError, OpenAI
from openai.types.chat import ChatCompletion
from pydantic import ValidationError

from .models import canonical, digest
from .observability import log_event


class AIError(RuntimeError):
    def __init__(self, code, message, retry_at=0):
        super().__init__(message)
        self.code, self.retry_at = code, retry_at

    def public(self):
        return dict(code=self.code, message=str(self), retry_at=self.retry_at)


def next_reset(now: float) -> float:
    local = datetime.fromtimestamp(now, ZoneInfo('Europe/Moscow'))
    reset = local.replace(hour=3, minute=0, second=0, microsecond=0)
    if reset <= local:
        reset += timedelta(days=1)
    return reset.timestamp()


def budget_error(body) -> bool:
    text = str(body).lower()
    return 'budget has been exceeded' in text or 'insufficient_quota' in text


def structured_messages(instruction, context, schema):
    """Use the same serialized request for budget checks and model calls."""
    return [
        {'role': 'system', 'content': instruction + '\nВерни только JSON по схеме: ' + canonical(schema.model_json_schema())},
        {'role': 'user', 'content': canonical(context)},
    ]


class LLMClient:
    def __init__(self, settings, store, *, http_client=None, sleep=time.sleep, clock=time.time):
        settings.require_key()
        self.settings, self.store = settings, store
        self.sleep, self.clock = sleep, clock
        self.account = hashlib.sha256(settings.api_key.get_secret_value().encode()).hexdigest()
        self.semaphore = threading.BoundedSemaphore(settings.max_concurrent_requests)
        self.sdk = OpenAI(
            api_key=settings.api_key.get_secret_value(), base_url=settings.base_url,
            max_retries=0, timeout=httpx.Timeout(settings.request_timeout_seconds),
            http_client=http_client or httpx.Client(follow_redirects=False),
        )

    def close(self):
        self.sdk.close()

    def _budget(self):
        until = self.store.blocked_until(self.account)
        if until > self.clock():
            raise AIError('budget_exceeded', 'Бюджет команды исчерпан. Сброс в 03:00 МСК.', until)

    def _block(self):
        self.store.block_budget(self.account, next_reset(self.clock()))
        self._budget()

    def _delay(self, response, attempt):
        value = response.headers.get('retry-after') if response is not None else None
        if value:
            try:
                delay = float(value)
            except ValueError:
                try:
                    delay = parsedate_to_datetime(value).timestamp() - self.clock()
                except (ValueError, TypeError, OverflowError):
                    delay = 1
        else:
            delay = 2 ** attempt + random.uniform(0, 0.25)
        if not math.isfinite(delay):
            delay = 1
        delay = max(0, delay)
        if delay > self.settings.max_retry_delay_seconds:
            raise AIError('rate_limited', 'Шлюз попросил повторить запрос позже.', self.clock() + delay)
        return delay

    def complete(self, stage, messages, *, max_tokens=None):
        return self._complete(stage, messages, max_tokens=max_tokens)

    def _complete(self, stage, messages, *, max_tokens=None, validate=None):
        s = self.settings
        options = {}
        if not s.deepseek_thinking_enabled and s.model_for(stage).startswith('deepseek/'):
            options['extra_body'] = {'thinking': {'type': 'disabled'}}
        if len(canonical(messages)) > s.max_input_chars:
            raise AIError('input_limit', 'Контекст превышает лимит; сократите документы или top_k.')
        if not self.semaphore.acquire(timeout=s.request_timeout_seconds):
            raise AIError('busy', 'Достигнут предел одновременных запросов.')
        try:
            for attempt in range(s.max_retries + 1):
                self._budget()
                call_id, retry_at = self.store.reserve_call(
                    self.account, stage, s.model_for(stage), s.requests_per_minute, self.clock())
                if call_id is None:
                    raise AIError('rate_limited', 'Достигнут локальный лимит запросов в минуту.', retry_at)
                response = None
                try:
                    result = self.sdk.chat.completions.create(
                        model=s.model_for(stage), messages=messages,
                        max_tokens=max_tokens or s.max_output_tokens,
                        **options,
                    )
                except APIStatusError as exc:
                    if budget_error(exc.body):
                        self.store.record_call(call_id, 'budget_exceeded')
                        self._block()
                    code = exc.status_code
                    response = exc.response
                    self.store.record_call(call_id, f'http_{code}')
                    if code in (401, 403):
                        raise AIError('authentication', 'Ключ отклонён шлюзом. Проверьте AI_API_KEY.') from None
                    if code not in (408, 409, 429) and code < 500:
                        raise AIError('request_rejected', f'Шлюз отклонил запрос (HTTP {code}).') from None
                    failure = AIError('rate_limited' if code == 429 else 'unavailable',
                                      f'Временная ошибка шлюза (HTTP {code}).')
                except (APITimeoutError, APIConnectionError) as exc:
                    code = 'timeout' if isinstance(exc, APITimeoutError) else 'connection'
                    self.store.record_call(call_id, code)
                    failure = AIError(code, 'Шлюз не ответил за отведённое время.')
                except APIResponseValidationError:
                    self.store.record_call(call_id, 'invalid_response')
                    raise AIError('invalid_response', 'Некорректный ответ шлюза.') from None
                else:
                    if not isinstance(result, ChatCompletion):
                        self.store.record_call(call_id, 'invalid_response')
                        raise AIError('invalid_response', 'Некорректный ответ шлюза.')
                    if budget_error((result.model_extra or {}).get('error', '')):
                        self.store.record_call(call_id, 'budget_exceeded')
                        self._block()
                    choices = getattr(result, 'choices', None)
                    choice = choices[0] if isinstance(choices, list) and choices else None
                    message = getattr(choice, 'message', None)
                    content = getattr(message, 'content', None)
                    if getattr(choice, 'finish_reason', None) not in ('stop', None):
                        self.store.record_call(call_id, 'incomplete_response', result.usage)
                        raise AIError('incomplete_response', 'Ответ модели не завершён; результат не опубликован.')
                    if not isinstance(content, str) or not content.strip():
                        self.store.record_call(call_id, 'invalid_response', result.usage)
                        raise AIError('invalid_response', 'Шлюз вернул пустой ответ.')
                    if validate:
                        try:
                            content = validate(content)
                        except Exception:
                            self.store.record_call(call_id, 'invalid_response', result.usage)
                            raise
                        except BaseException:
                            self.store.record_call(call_id, 'cancelled', result.usage)
                            raise
                    self.store.record_call(call_id, 'ok', result.usage)
                    return content
                delay = self._delay(response, attempt)
                if attempt == s.max_retries:
                    failure.retry_at = self.clock() + delay
                    raise failure from None
                self.sleep(delay)
        finally:
            self.semaphore.release()

    def structured(self, stage, instruction, context, schema, validate=None):
        started = time.monotonic()
        cache_hit, validation_outcome, error_code = False, 'not_run', None

        def parse(raw):
            nonlocal validation_outcome
            validation_outcome = 'invalid'
            raw = raw.strip()
            if raw.startswith('```') and raw.endswith('```'):
                raw = raw.split('\n', 1)[-1].rsplit('```', 1)[0].strip()
            try:
                output = schema.model_validate_json(raw)
                if validate:
                    validate(output)
            except (ValidationError, ValueError, json.JSONDecodeError):
                # Invalid outputs are not repaired via additional paid calls.
                raise AIError('invalid_response', 'Ответ не прошёл проверку структуры или оснований.') from None
            validation_outcome = 'valid'
            return output

        try:
            messages = structured_messages(instruction, context, schema)
            key = digest(dict(model=self.settings.model_for(stage), messages=messages,
                              max_tokens=self.settings.max_output_tokens, gateway=self.settings.base_url,
                              deepseek_thinking_enabled=self.settings.deepseek_thinking_enabled))
            cached = self.store.cache_get(key)
            cache_hit = cached is not None
            output = parse(canonical(cached)) if cache_hit else self._complete(stage, messages, validate=parse)
            if not cache_hit:
                self.store.cache_put(key, output.model_dump(mode='json'))
            return output
        except AIError as exc:
            error_code = exc.code
            raise
        except Exception:
            error_code = 'internal'
            raise
        except BaseException:
            validation_outcome, error_code = 'cancelled', 'cancelled'
            raise
        finally:
            log_event('llm_structured', stage=stage, model=self.settings.model_for(stage),
                      schema=schema.__name__, cache_hit=cache_hit, validation_outcome=validation_outcome,
                      error_code=error_code, duration_ms=round((time.monotonic() - started) * 1000))
