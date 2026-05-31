import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
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

    def test_catalog_deduplicates_duplicate_slugs(self):
        from talaria.catalog import catalog_from_debug_json

        raw = {
            "models": [
                {"slug": "gpt-5.5", "display_name": "GPT-5.5", "visibility": "list"},
                {"slug": "gpt-5.5", "display_name": "GPT-5.5 duplicate", "visibility": "list"},
            ]
        }

        catalog = catalog_from_debug_json(raw)

        self.assertEqual([m.slug for m in catalog], ["gpt-5.5"])
        self.assertEqual([m.alias for m in catalog], ["claude-gpt-5.5"])

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

        def fake_urlopen(req, timeout, **_kwargs):
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

    def test_upstream_error_is_http_error_not_empty_message(self):
        from talaria.catalog import CodexModel
        from talaria.server import TalariaApp

        app = TalariaApp(
            [CodexModel("gpt-5.5", "claude-gpt-5.5", "GPT-5.5", "medium")],
            event_stream=lambda **_kwargs: iter([{"type": "error", "message": "upstream failed", "status": 502}]),
        )

        status, _headers, body = app.handle(
            "POST",
            "/v1/messages",
            {"Content-Type": "application/json"},
            b'{"model":"claude-gpt-5.5","messages":[]}',
        )

        self.assertEqual(status, 502)
        self.assertIn("upstream failed", body.decode("utf-8"))

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
    def test_print_setup_help_includes_next_actions(self):
        from talaria.checks import Check
        import talaria.cli as cli

        output = io.StringIO()
        with redirect_stdout(output):
            cli._print_setup_help(
                [
                    Check("claude", False, "NOT FOUND"),
                    Check("tls", False, "TLS check failed: cert issue"),
                ]
            )
        text = output.getvalue()
        self.assertIn("Talaria cannot start yet.", text)
        self.assertIn("Install: npm install -g @anthropic-ai/claude-code", text)
        self.assertIn("Run: talaria doctor", text)

    def test_setup_uses_python_version_check(self):
        from talaria.checks import Check
        from talaria.catalog import CodexModel
        import talaria.cli as cli

        output = io.StringIO()
        with mock.patch.object(cli, "check_python", return_value=Check("python", False, "3.9.0 (minimum 3.10 required)")), mock.patch(
            "talaria.cli.check_binary", return_value=Check("ok", True, "ok")
        ), mock.patch(
            "talaria.cli.check_codex_login", return_value=Check("codex login", True, "ok")
        ), mock.patch(
            "talaria.cli.check_model_catalog",
            return_value=(
                Check("model catalog", True, "1 visible"),
                [CodexModel("gpt-5.5", "claude-gpt-5.5", "GPT-5.5", "medium")],
            ),
        ), mock.patch(
            "talaria.cli.check_tls", return_value=Check("tls", True, "ok")
        ), mock.patch(
            "talaria.cli.check_loopback_bind", return_value=Check("loopback bind", True, "127.0.0.1:0")
        ), mock.patch(
            "talaria.cli.check_gateway_cache", return_value=Check("gateway cache", True, "/tmp/.claude/cache/gateway-models.json")
        ):
            with redirect_stdout(output):
                rc = cli.run_setup([])

        self.assertEqual(rc, 1)
        self.assertIn("python: fail (3.9.0 (minimum 3.10 required))", output.getvalue())

    def test_print_security_summary_does_not_log_tokens(self):
        from talaria.catalog import CodexModel
        from talaria.cli import _print_security_summary

        output = io.StringIO()
        with redirect_stdout(output):
            _print_security_summary(
                "http://127.0.0.1:8141",
                [CodexModel("gpt-5.5", "claude-gpt-5.5", "GPT-5.5", "medium")],
                "/tmp/.claude/cache/gateway-models.json",
            )
        text = output.getvalue()
        self.assertIn("Talaria listening on http://127.0.0.1:8141", text)
        self.assertIn("Codex backend: https://chatgpt.com/backend-api/codex/responses", text)
        self.assertNotIn("Bearer", text)
        self.assertNotIn("access_token", text)

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

    def test_dangerously_skip_permission_alias_maps_to_claude_flag(self):
        from talaria.cli import claude_launch_args

        args = claude_launch_args(["--dangerously-skip-permission", "--model", "claude-gpt-5.5"])

        self.assertEqual(args, ["--model", "claude-gpt-5.5", "--dangerously-skip-permissions"])

    def test_talaria_launch_rejects_non_loopback_host(self):
        import talaria.cli as cli

        rc = cli.run(["--host", "0.0.0.0"])  # still uses preflight path before launch

        self.assertEqual(rc, 1)

    def test_parse_smoke_args_uses_model(self):
        from talaria.smoke import parse_smoke_args

        live, model = parse_smoke_args(["--live", "--model", "claude-gpt-5.5"])

        self.assertTrue(live)
        self.assertEqual(model, "claude-gpt-5.5")


class ChecksTests(unittest.TestCase):
    def test_is_loopback_host(self):
        from talaria.checks import is_loopback_host

        self.assertTrue(is_loopback_host("127.0.0.1"))
        self.assertTrue(is_loopback_host("::1"))
        self.assertTrue(is_loopback_host("localhost"))
        self.assertFalse(is_loopback_host("0.0.0.1"))

    def test_run_local_gateway_smoke_offline(self):
        from talaria.catalog import CodexModel
        from talaria.checks import run_local_gateway_smoke

        checks, base_url = run_local_gateway_smoke(
            host="127.0.0.1",
            port=0,
            catalog=[
                CodexModel("gpt-5.5", "claude-gpt-5.5", "GPT-5.5", "medium"),
            ],
            event_stream=lambda **_kwargs: iter([]),
        )

        self.assertEqual(base_url.split(":")[-1] != "", True)
        self.assertTrue(all(item.ok for item in checks))

    def test_check_python_requires_minimum_version(self):
        import talaria.checks as checks_mod

        fake_version = mock.Mock(major=3, minor=9, micro=0)
        with mock.patch.object(checks_mod.sys, "version_info", fake_version):
            result = checks_mod.check_python()
        self.assertFalse(result.ok)
        self.assertIn("minimum 3.10 required", result.message)


class SmokeTests(unittest.TestCase):
    def test_smoke_offline_default_invocation(self):
        import talaria.cli as cli

        with mock.patch.object(cli, "run_smoke") as run_smoke:
            run_smoke.return_value = 0
            rc = cli.run(["smoke"])

        self.assertEqual(rc, 0)
        run_smoke.assert_called_once()

    def test_smoke_prints_server_line(self):
        from talaria.smoke import Check, run_smoke
        from talaria.catalog import CodexModel

        with mock.patch("talaria.smoke.check_python", return_value=Check("python", True, "3.14.2")), mock.patch(
            "talaria.smoke.check_codex_login", return_value=Check("codex login", True, "ok")
        ), mock.patch(
            "talaria.smoke.check_model_catalog",
            return_value=(Check("model catalog", True, "1 visible"), [CodexModel("gpt-5.5", "claude-gpt-5.5", "GPT-5.5", "medium")]),
        ), mock.patch(
            "talaria.smoke.check_loopback_bind", return_value=Check("loopback bind", True, "127.0.0.1:0")
        ), mock.patch(
            "talaria.smoke.check_gateway_cache", return_value=Check("gateway cache", True, "/tmp/.claude/cache/gateway-models.json")
        ), mock.patch(
            "talaria.smoke.run_local_gateway_smoke",
            return_value=(
                [
                    Check("healthz", True, "ok"),
                    Check("models", True, "ok"),
                    Check("security controls", True, "ok"),
                ],
                "http://127.0.0.1:12345",
            ),
        ):
            output = io.StringIO()
            with redirect_stdout(output):
                rc = run_smoke([])

        self.assertEqual(rc, 0)
        self.assertIn("server: ok (http://127.0.0.1:12345)", output.getvalue())

    def test_smoke_live_unknown_model_fails(self):
        from talaria.catalog import CodexModel
        from talaria.smoke import Check, run_smoke

        with mock.patch("talaria.smoke.check_python", return_value=Check("python", True, "3.14.2")), mock.patch(
            "talaria.smoke.check_codex_login", return_value=Check("codex login", True, "ok")
        ), mock.patch(
            "talaria.smoke.check_model_catalog",
            return_value=(
                Check("model catalog", True, "1 visible"),
                [CodexModel("gpt-5.5", "claude-gpt-5.5", "GPT-5.5", "medium")],
            ),
        ):
            with mock.patch("talaria.smoke.check_loopback_bind"), mock.patch("talaria.smoke.check_gateway_cache"), mock.patch(
                "talaria.smoke.run_local_gateway_smoke",
                return_value=([Check("healthz", True, "ok"), Check("models", True, "ok"), Check("security controls", True, "ok")], "http://127.0.0.1:1"),
            ), mock.patch(
                "talaria.smoke.run_local_gateway", return_value=mock.MagicMock()
            ):
                output = io.StringIO()
                with redirect_stdout(output):
                    rc = run_smoke(["--live", "--model", "claude-missing"])

        self.assertEqual(rc, 1)
        self.assertIn("live non-stream: fail", output.getvalue())


class DoctorTests(unittest.TestCase):
    def test_doctor_runs_setup_command_checks(self):
        import talaria.cli as cli

        with mock.patch.object(cli, "run_doctor") as run_doctor:
            run_doctor.return_value = 0
            rc = cli.run(["doctor"])

        self.assertEqual(rc, 0)
        run_doctor.assert_called_once()

    def test_dangerously_skip_permissions_env_adds_claude_flag(self):
        from talaria.cli import claude_launch_args

        with mock.patch.dict(os.environ, {"TALARIA_DANGEROUSLY_SKIP_PERMISSIONS": "1"}):
            args = claude_launch_args([])

        self.assertEqual(args, ["--dangerously-skip-permissions"])


if __name__ == "__main__":
    unittest.main()
