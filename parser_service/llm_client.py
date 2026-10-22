"""Owned, explicitly configured GLM client for the extraction adapter."""

from __future__ import annotations

from contextlib import AsyncExitStack, asynccontextmanager
import math

import httpx
from langchain_openai import ChatOpenAI
from pydantic import SecretStr


MODEL_ID = "z-ai/glm-5.3-flash"
PRIMARY_BASE_URL = "https://changellenge.up.railway.app/v1"
SECONDARY_BASE_URL = "https://api.alfahack-gateway26.ru/v1"
_ALLOWED_BASE_URLS = {PRIMARY_BASE_URL, SECONDARY_BASE_URL}
_USER_AGENT = "KIBNewsPrototype/0.1"


class ModelConfigurationError(ValueError):
    def __init__(self) -> None:
        super().__init__("The extraction model configuration is invalid.")


def _validate(
    api_key: SecretStr,
    max_output_tokens: int,
    timeout_seconds: float,
    base_url: str,
) -> float:
    if not isinstance(api_key, SecretStr):
        raise ModelConfigurationError() from None
    key = api_key.get_secret_value()
    if (
        not key
        or not key.isascii()
        or any(character.isspace() or not character.isprintable() for character in key)
    ):
        raise ModelConfigurationError() from None
    if type(max_output_tokens) is not int or max_output_tokens <= 0:
        raise ModelConfigurationError() from None
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)):
        raise ModelConfigurationError() from None
    try:
        timeout = float(timeout_seconds)
    except (OverflowError, ValueError):
        raise ModelConfigurationError() from None
    if (
        not math.isfinite(timeout)
        or timeout <= 0
        or not isinstance(base_url, str)
        or base_url not in _ALLOWED_BASE_URLS
    ):
        raise ModelConfigurationError() from None
    return timeout


@asynccontextmanager
async def open_extraction_model(
    *,
    api_key: SecretStr,
    max_output_tokens: int,
    timeout_seconds: float,
    base_url: str = PRIMARY_BASE_URL,
):
    """Yield one configured chat model and close both owned transports afterward."""
    timeout = _validate(api_key, max_output_tokens, timeout_seconds, base_url)
    key = api_key.get_secret_value()

    def sanitize_request(request: httpx.Request) -> None:
        content_length = len(request.content)
        request.headers.clear()
        request.headers.update({
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Host": request.url.netloc,
            "Content-Length": str(content_length),
            "User-Agent": _USER_AGENT,
            # ChatOpenAI expects the SDK's raw response wrapper before parsing JSON.
            "X-Stainless-Raw-Response": "true",
        })

    async def sanitize_async_request(request: httpx.Request) -> None:
        sanitize_request(request)

    http_timeout = httpx.Timeout(timeout)
    async with AsyncExitStack() as stack:
        try:
            sync_client = stack.enter_context(
                httpx.Client(
                    timeout=http_timeout,
                    trust_env=False,
                    follow_redirects=False,
                    event_hooks={"request": [sanitize_request]},
                )
            )
            async_client = await stack.enter_async_context(
                httpx.AsyncClient(
                    timeout=http_timeout,
                    trust_env=False,
                    follow_redirects=False,
                    event_hooks={"request": [sanitize_async_request]},
                )
            )
            model = ChatOpenAI(
                model=MODEL_ID,
                api_key=api_key,
                base_url=base_url,
                max_tokens=max_output_tokens,
                reasoning_effort="high",
                timeout=timeout,
                max_retries=0,
                streaming=False,
                cache=False,
                use_responses_api=False,
                callbacks=[],
                http_client=sync_client,
                http_async_client=async_client,
                openai_proxy=None,
            )
        except Exception:
            raise ModelConfigurationError() from None
        yield model
