import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock


class CatalogTests(unittest.TestCase):
    def test_catalog_filters_visible_models(self):
        from talaria.catalog import catalog_from_debug_json

        raw = {
            "models": [
                {
                    "slug": "gpt-5.5",
                    "display_name": "GPT-5.5",
                    "visibility": "list",
                    "default_reasoning_level": "medium",
                },
                {"slug": "gpt-5.4-mini", "display_name": "GPT-5.4-Mini", "visibility": "list"},
                {"slug": "codex-auto-review", "display_name": "Codex Auto Review", "visibility": "hide"},
                {"display_name": "Broken", "visibility": "list"},
            ]
        }

        catalog = catalog_from_debug_json(raw)

        self.assertEqual([m.slug for m in catalog], ["gpt-5.5", "gpt-5.4-mini"])
        self.assertEqual([m.alias for m in catalog], ["claude-gpt-5.5", "claude-gpt-5.4-mini"])
        self.assertEqual(catalog[0].reasoning_effort, "medium")
        self.assertEqual(catalog[1].reasoning_effort, "medium")

    def test_catalog_rejects_empty_visible_models(self):
        from talaria.catalog import CodexCatalogError, catalog_from_debug_json

        with self.assertRaisesRegex(CodexCatalogError, "No visible Codex models"):
            catalog_from_debug_json({"models": [{"slug": "hidden", "visibility": "hide"}]})

    def test_discover_catalog_accepts_codex_status_on_stderr(self):
        import talaria.catalog as catalog_mod

        def fake_run(args, capture_output, text, check):
            class Proc:
                returncode = 0
                stdout = ""
                stderr = ""

            proc = Proc()
            if args[-2:] == ["login", "status"]:
                proc.stderr = "Logged in using ChatGPT\n"
            elif args[-2:] == ["debug", "models"]:
                proc.stdout = json.dumps(
                    {
                        "models": [
                            {
                                "slug": "gpt-5.5",
                                "display_name": "GPT-5.5",
                                "visibility": "list",
                            }
                        ]
                    }
                )
            return proc

        with mock.patch.object(catalog_mod.shutil, "which", return_value="/bin/codex"):
            with mock.patch.object(catalog_mod.subprocess, "run", side_effect=fake_run):
                discovered = catalog_mod.discover_catalog()

        self.assertEqual([m.slug for m in discovered], ["gpt-5.5"])


class TranslationTests(unittest.TestCase):
    def test_anthropic_tools_and_tool_results_convert_to_responses(self):
        from talaria.translate import anthropic_request_to_responses

        req = {
            "system": [{"type": "text", "text": "system rules"}],
            "messages": [
                {"role": "user", "content": "weather?"},
                {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "checking"},
                        {"type": "tool_use", "id": "toolu_1", "name": "get_weather", "input": {"city": "Paris"}},
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "tool_result", "tool_use_id": "toolu_1", "content": "sunny"},
                    ],
                },
            ],
            "tools": [
                {
                    "name": "get_weather",
                    "description": "weather",
                    "input_schema": {"type": "object", "properties": {"city": {"type": "string"}}},
                }
            ],
            "tool_choice": {"type": "auto"},
        }

        converted = anthropic_request_to_responses(req)

        self.assertEqual(converted["instructions"], "system rules")
        self.assertIn({"type": "function_call_output", "call_id": "toolu_1", "output": "sunny"}, converted["input"])
        self.assertEqual(converted["tools"][0]["name"], "get_weather")
        self.assertEqual(converted["tool_choice"], "auto")

    def test_events_emit_anthropic_stream(self):
        from talaria.translate import events_to_anthropic_sse

        events = [
            {"type": "text_delta", "text": "Hello "},
            {"type": "tool_call", "id": "call_1", "name": "get_weather", "arguments": '{"city":"Paris"}'},
            {"type": "usage", "input_tokens": 2, "output_tokens": 3},
        ]

        stream = b"".join(events_to_anthropic_sse(events, "claude-gpt-5.5")).decode("utf-8")

        self.assertIn("event: message_start", stream)
        self.assertIn('"type": "tool_use"', stream)
        self.assertIn('"name": "get_weather"', stream)
        self.assertIn('"partial_json": "{\\"city\\":\\"Paris\\"}"', stream)
        self.assertIn('"stop_reason": "tool_use"', stream)


class CodexProviderTests(unittest.TestCase):
    def test_codex_provider_request_shape(self):
        import talaria.codex as codex

        captured = {}

        class FakeResp:
            headers = {"Content-Type": "text/event-stream"}

            def __init__(self):
                self._chunks = [
                    b'data: {"type":"response.output_text.delta","delta":"ok"}\n\n',
                    b'data: {"type":"response.completed","response":{"usage":{"input_tokens":2,"output_tokens":3}}}\n\n',
                ]

            def read(self, _n):
                return self._chunks.pop(0) if self._chunks else b""

        def fake_urlopen(req, timeout):
            captured["body"] = json.loads(req.data.decode("utf-8"))
            captured["headers"] = dict(req.headers)
            return FakeResp()

        with mock.patch.object(codex, "access_token", return_value="header.payload.sig"):
            with mock.patch.object(codex.urllib.request, "urlopen", side_effect=fake_urlopen):
                events = list(
                    codex.stream_events(
                        payload={
                            "instructions": "",
                            "input": [{"type": "message", "role": "user", "content": [{"type": "input_text", "text": "hi"}]}],
                            "tools": [],
                        },
                        model="gpt-5.5",
                        reasoning_effort="high",
                        service_tier="priority",
                    )
                )

        self.assertEqual(captured["body"]["model"], "gpt-5.5")
        self.assertIs(captured["body"]["store"], False)
        self.assertIs(captured["body"]["parallel_tool_calls"], False)
        self.assertEqual(captured["body"]["reasoning"], {"effort": "high"})
        self.assertEqual(captured["body"]["service_tier"], "priority")
        self.assertIn({"type": "text_delta", "text": "ok"}, events)

    def test_codex_backend_is_pinned_to_chatgpt(self):
        import talaria.codex as codex

        self.assertEqual(codex.RESPONSES_URL, "https://chatgpt.com/backend-api/codex/responses")


class ServerTests(unittest.TestCase):
    def test_server_models_and_streaming_response(self):
        from talaria.catalog import CodexModel
        from talaria.server import TalariaApp

        app = TalariaApp(
            [
                CodexModel("gpt-5.5", "claude-gpt-5.5", "GPT-5.5", "medium"),
                CodexModel("gpt-5.4-mini", "claude-gpt-5.4-mini", "GPT-5.4-Mini", "low"),
            ],
            event_stream=lambda **_kwargs: iter(
                [
                    {"type": "text_delta", "text": "Hello "},
                    {"type": "tool_call", "id": "call_1", "name": "get_weather", "arguments": '{"city":"Paris"}'},
                ]
            ),
        )

        models_status, _headers, models_body = app.handle("GET", "/v1/models", {}, b"")
        self.assertEqual(models_status, 200)
        self.assertEqual([m["id"] for m in json.loads(models_body)["data"]], ["claude-gpt-5.5", "claude-gpt-5.4-mini"])

        body = json.dumps(
            {
                "model": "claude-gpt-5.5",
                "stream": True,
                "messages": [{"role": "user", "content": "weather?"}],
                "tools": [{"name": "get_weather", "input_schema": {"type": "object", "properties": {}}}],
            }
        ).encode("utf-8")
        status, headers, out = app.handle("POST", "/v1/messages", {"Content-Type": "application/json"}, body)
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "text/event-stream")
        self.assertIn(b'"type": "tool_use"', out)
        self.assertIn(b"Paris", out)

    def test_unknown_model_is_local_error(self):
        from talaria.catalog import CodexModel
        from talaria.server import TalariaApp

        app = TalariaApp([CodexModel("gpt-5.5", "claude-gpt-5.5", "GPT-5.5", "medium")])
        status, _headers, body = app.handle(
            "POST",
            "/v1/messages",
            {"Content-Type": "application/json"},
            b'{"model":"claude-missing","messages":[]}',
        )

        self.assertEqual(status, 400)
        self.assertIn("unknown Codex model alias", body.decode("utf-8"))

    def test_rejects_browser_origin_posts(self):
        from talaria.catalog import CodexModel
        from talaria.server import TalariaApp

        app = TalariaApp([CodexModel("gpt-5.5", "claude-gpt-5.5", "GPT-5.5", "medium")])
        status, _headers, body = app.handle(
            "POST",
            "/v1/messages",
            {"Content-Type": "application/json", "Origin": "https://evil.example"},
            b'{"model":"claude-gpt-5.5","messages":[]}',
        )

        self.assertEqual(status, 403)
        self.assertIn("browser-origin requests are not accepted", body.decode("utf-8"))

    def test_rejects_non_json_message_posts(self):
        from talaria.catalog import CodexModel
        from talaria.server import TalariaApp

        app = TalariaApp([CodexModel("gpt-5.5", "claude-gpt-5.5", "GPT-5.5", "medium")])
        status, _headers, body = app.handle(
            "POST",
            "/v1/messages",
            {"Content-Type": "text/plain"},
            b'{"model":"claude-gpt-5.5","messages":[]}',
        )

        self.assertEqual(status, 415)
        self.assertIn("application/json", body.decode("utf-8"))

    def test_rejects_oversized_message_body(self):
        from talaria.catalog import CodexModel
        from talaria.server import TalariaApp, MAX_BODY_BYTES

        app = TalariaApp([CodexModel("gpt-5.5", "claude-gpt-5.5", "GPT-5.5", "medium")])
        status, _headers, body = app.handle(
            "POST",
            "/v1/messages",
            {"Content-Type": "application/json"},
            b"{" + (b'"x":' + b'"a"' * (MAX_BODY_BYTES // 2)) + b"}",
        )

        self.assertEqual(status, 413)
        self.assertIn("request body too large", body.decode("utf-8"))


class CliTests(unittest.TestCase):
    def test_gateway_cache_shape(self):
        from talaria.cli import gateway_cache_payload

        payload = gateway_cache_payload(
            "http://127.0.0.1:8141",
            [
                {"id": "claude-gpt-5.5", "display_name": "GPT-5.5"},
                {"id": "claude-gpt-5.4-mini", "display_name": "GPT-5.4-Mini"},
            ],
            now_ms=123,
        )

        self.assertEqual(payload["baseUrl"], "http://127.0.0.1:8141")
        self.assertEqual(payload["fetchedAt"], 123)
        self.assertEqual(payload["models"][0]["id"], "claude-gpt-5.5")


if __name__ == "__main__":
    unittest.main()
