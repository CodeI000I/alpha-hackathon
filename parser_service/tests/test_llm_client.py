import asyncio
import json
import math
import os
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from pydantic import SecretStr

from parser_service.ai_extract import ExtractionError, extract_document
from parser_service.extraction_models import DocumentBlock, SourceDocument
from parser_service.llm_client import (
    MODEL_ID,
    PRIMARY_BASE_URL,
    SECONDARY_BASE_URL,
    ModelConfigurationError,
    open_extraction_model,
)


REAL_ASYNC_CLIENT_INIT = httpx.AsyncClient.__init__
REAL_ASYNC_CLIENT_SEND = httpx.AsyncClient.send


def source_document():
    text = "Ставка составит 16 процентов."
    return SourceDocument(
        document_revision="revision-llm-client",
        text=text,
        blocks=[DocumentBlock(block_id="body", start=0, end=len(text))],
    )


def extraction_json(source):
    quote = source.text
    return json.dumps({
        "title": None,
        "publication": {"at": None, "date": None, "precision": "unknown",
                        "evidence_ids": []},
        "claims": [{"claim_id": "claim-1", "text": quote,
                    "modality": "announcement", "event_date": None,
                    "effective_date": None, "evidence_ids": ["evidence-1"]}],
        "evidence": [{"evidence_id": "evidence-1",
                      "document_revision": source.document_revision,
                      "text_hash": source.text_hash,
                      "locator": {"block_id": "body", "start": 0,
                                  "end": len(quote)},
                      "quote": quote}],
        "incomplete_fields": ["title", "publication"],
    }, ensure_ascii=False)


def completion_response(request, content):
    return httpx.Response(200, request=request, json={
        "id": "chatcmpl-fixture",
        "object": "chat.completion",
        "created": 1,
        "model": MODEL_ID,
        "choices": [{"index": 0, "finish_reason": "stop",
                     "message": {"role": "assistant", "content": content}}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    })


class LlmClientTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.sync_send_guard = patch.object(
            httpx.Client, "send", side_effect=AssertionError("unexpected sync network")
        )
        self.async_send_guard = patch.object(
            httpx.AsyncClient, "send",
            new=AsyncMock(side_effect=AssertionError("unexpected async network")),
        )
        self.sync_send_guard.start()
        self.async_send_guard.start()
        self.addCleanup(self.async_send_guard.stop)
        self.addCleanup(self.sync_send_guard.stop)

    async def test_opens_configured_real_chat_model_without_request_and_closes_clients(self):
        send = AsyncMock(side_effect=AssertionError("no request expected"))
        with patch.object(httpx.AsyncClient, "send", send):
            async with open_extraction_model(
                api_key=SecretStr("test-key"), max_output_tokens=321,
                timeout_seconds=2.5,
            ) as model:
                sync_client = model.http_client
                async_client = model.http_async_client
                self.assertEqual(model.model_name, MODEL_ID)
                self.assertEqual(model.max_tokens, 321)
                self.assertEqual(model.request_timeout, 2.5)
                self.assertEqual(model.max_retries, 0)
                self.assertIs(model.streaming, False)
                self.assertIs(model.cache, False)
                self.assertIs(model.use_responses_api, False)
                self.assertIs(sync_client._trust_env, False)
                self.assertIs(async_client._trust_env, False)
                self.assertIs(sync_client.follow_redirects, False)
                self.assertIs(async_client.follow_redirects, False)
                self.assertFalse(sync_client.is_closed)
                self.assertFalse(async_client.is_closed)
            self.assertTrue(sync_client.is_closed)
            self.assertTrue(async_client.is_closed)
        send.assert_not_awaited()

    async def test_body_error_is_not_rewritten_and_still_closes_clients(self):
        class BodyFailure(RuntimeError):
            pass

        with self.assertRaises(BodyFailure):
            async with open_extraction_model(
                api_key=SecretStr("test-key"), max_output_tokens=100,
                timeout_seconds=1,
            ) as model:
                sync_client = model.http_client
                async_client = model.http_async_client
                raise BodyFailure("body failed")

        self.assertTrue(sync_client.is_closed)
        self.assertTrue(async_client.is_closed)

    async def test_body_cancellation_propagates_and_still_closes_clients(self):
        clients = {}

        async def cancelled_body():
            async with open_extraction_model(
                api_key=SecretStr("test-key"), max_output_tokens=100,
                timeout_seconds=1,
            ) as model:
                clients["sync"] = model.http_client
                clients["async"] = model.http_async_client
                raise asyncio.CancelledError

        task = asyncio.create_task(cancelled_body())
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(clients["sync"].is_closed)
        self.assertTrue(clients["async"].is_closed)

    async def test_selected_gateway_wire_payload_passes_existing_evidence_validation(self):
        source = source_document()
        requests = []

        async def respond(request, **_kwargs):
            requests.append(request)
            return completion_response(request, extraction_json(source))

        with patch.object(httpx.AsyncClient, "send", new=AsyncMock(side_effect=respond)):
            async with open_extraction_model(
                api_key=SecretStr("test-key"), max_output_tokens=456,
                timeout_seconds=2,
            ) as model:
                result = await extract_document(
                    source, model, max_input_chars=100_000,
                    max_output_chars=10_000, timeout_seconds=1,
                )

        self.assertEqual(result.evidence[0].quote, source.text)
        self.assertEqual(len(requests), 1)
        request = requests[0]
        self.assertEqual(str(request.url), PRIMARY_BASE_URL + "/chat/completions")
        payload = json.loads(request.content)
        self.assertEqual(payload["model"], MODEL_ID)
        self.assertEqual(payload["max_completion_tokens"], 456)
        self.assertNotIn("tools", payload)
        self.assertNotIn("response_format", payload)

    async def test_503_is_single_safe_failure_without_gateway_fallback(self):
        requests = []

        async def unavailable(request, **_kwargs):
            requests.append(request)
            return httpx.Response(
                503, request=request,
                json={"error": {"message": "private-upstream-detail", "type": "fixture"}},
            )

        with patch.object(
            httpx.AsyncClient, "send", new=AsyncMock(side_effect=unavailable)
        ):
            async with open_extraction_model(
                api_key=SecretStr("test-key"), max_output_tokens=100,
                timeout_seconds=2,
            ) as model:
                with self.assertRaises(ExtractionError) as raised:
                    await extract_document(
                        source_document(), model, max_input_chars=100_000,
                        max_output_chars=10_000, timeout_seconds=1,
                    )

        self.assertEqual(raised.exception.code, "MODEL_UNAVAILABLE")
        self.assertNotIn("private-upstream-detail", str(raised.exception))
        self.assertEqual(len(requests), 1)
        self.assertTrue(str(requests[0].url).startswith(PRIMARY_BASE_URL))
        self.assertNotIn("alfahack-gateway26", str(requests[0].url))

    async def test_rejects_invalid_configuration_before_creating_or_sending(self):
        cases = [
            {"api_key": "plain-key"},
            {"api_key": SecretStr("")},
            {"api_key": SecretStr("white space")},
            {"api_key": SecretStr("bad\nkey")},
            {"max_output_tokens": True},
            {"max_output_tokens": 0},
            {"timeout_seconds": False},
            {"timeout_seconds": math.inf},
            {"timeout_seconds": 10**1000},
            {"base_url": PRIMARY_BASE_URL + "/"},
            {"base_url": "https://example.test/v1?gateway=primary"},
            {"base_url": []},
            {"base_url": None},
        ]
        defaults = dict(api_key=SecretStr("test-key"), max_output_tokens=100,
                        timeout_seconds=1, base_url=PRIMARY_BASE_URL)
        send = AsyncMock()
        with patch.object(httpx.AsyncClient, "send", send):
            for changes in cases:
                values = {**defaults, **changes}
                with self.subTest(changes=changes):
                    with self.assertRaises(ModelConfigurationError) as raised:
                        async with open_extraction_model(**values):
                            self.fail("invalid configuration entered the context")
                    message = str(raised.exception)
                    self.assertNotIn("plain-key", message)
                    self.assertNotIn("white space", message)
                    self.assertNotIn("example.test", message)
        send.assert_not_awaited()

    async def test_explicit_secondary_gateway_is_allowed_without_request(self):
        send = AsyncMock(side_effect=AssertionError("no request expected"))
        with patch.object(httpx.AsyncClient, "send", send):
            async with open_extraction_model(
                api_key=SecretStr("test-key"), max_output_tokens=100,
                timeout_seconds=1, base_url=SECONDARY_BASE_URL,
            ) as model:
                self.assertEqual(str(model.openai_api_base).rstrip("/"), SECONDARY_BASE_URL)
        send.assert_not_awaited()

    async def test_synthetic_openai_environment_cannot_inject_request_headers(self):
        source = source_document()
        requests = []
        observed_headers = []

        async def handle(request):
            requests.append(request)
            observed_headers.append(dict(request.headers))
            return completion_response(request, extraction_json(source))

        transport = httpx.MockTransport(handle)

        def init_with_transport(client, *args, **kwargs):
            kwargs["transport"] = transport
            REAL_ASYNC_CLIENT_INIT(client, *args, **kwargs)

        poisoned_env = {
            "OPENAI_ORG_ID": "synthetic-org",
            "OPENAI_PROJECT_ID": "synthetic-project",
            "OPENAI_CUSTOM_HEADERS": (
                "Authorization: Bearer poisoned\n"
                "Host: poisoned.example\n"
                "Content-Length: 1\n"
                "X-Stainless-Raw-Response: stream\n"
                "X-Synthetic-Leak: present"
            ),
        }
        with patch.dict(os.environ, poisoned_env, clear=False), \
             patch.object(httpx.AsyncClient, "__init__", init_with_transport), \
             patch.object(httpx.AsyncClient, "send", REAL_ASYNC_CLIENT_SEND):
            async with open_extraction_model(
                api_key=SecretStr("test-key"), max_output_tokens=100,
                timeout_seconds=1,
            ) as model:
                result = await extract_document(
                    source, model, max_input_chars=100_000,
                    max_output_chars=10_000, timeout_seconds=1,
                )

        self.assertEqual(len(requests), 1)
        self.assertEqual(result.evidence[0].quote, source.text)
        payload = json.loads(requests[0].content)
        self.assertEqual(payload["reasoning_effort"], "high")
        headers = observed_headers[0]
        self.assertEqual(headers["authorization"], "Bearer test-key")
        self.assertEqual(headers["host"], "changellenge.up.railway.app")
        self.assertEqual(headers["content-length"], str(len(requests[0].content)))
        self.assertEqual(headers["content-type"], "application/json")
        self.assertEqual(headers["accept"], "application/json")
        self.assertEqual(headers["user-agent"], "KIBNewsPrototype/0.1")
        self.assertEqual(headers["x-stainless-raw-response"], "true")
        self.assertNotIn("openai-organization", headers)
        self.assertNotIn("openai-project", headers)
        self.assertNotIn("x-synthetic-leak", headers)


if __name__ == "__main__":
    unittest.main()
