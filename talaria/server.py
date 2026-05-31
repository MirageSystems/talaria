"""Talaria HTTP shim for Claude Code's Anthropic Messages API."""

from __future__ import annotations

import os
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable, Iterable
from urllib.parse import urlparse

from . import codex
from .catalog import CodexModel
from . import translate


EventStream = Callable[..., Iterable[dict]]


class TalariaApp:
    """Pure request handler logic used in tests and in the HTTP runner."""

    def __init__(self, catalog: Iterable[CodexModel], event_stream: EventStream = codex.stream_events):
        self.catalog = list(catalog)
        self.event_stream = event_stream

    def _model_by_alias(self, alias: str) -> CodexModel | None:
        for model in self.catalog:
            if model.alias == alias:
                return model
        return None

    def _json_error(self, status: int, message: str, details: str | None = None) -> tuple[int, dict, bytes]:
        payload = {"error": {"type": "invalid_request_error", "message": message}}
        if details:
            payload["error"]["details"] = details
        return status, {"Content-Type": "application/json"}, json.dumps(payload).encode("utf-8")

    def handle(self, method: str, path: str, headers: dict, body: bytes) -> tuple[int, dict[str, str], bytes]:
        parsed = urlparse(path or "/")
        target = parsed.path
        if method == "GET" and target == "/healthz":
            return (
                200,
                {"Content-Type": "application/json"},
                json.dumps({"ok": True, "models": len(self.catalog)}).encode("utf-8"),
            )

        if method == "GET" and target == "/v1/models":
            payload = {
                "data": [m.anthropic_model() for m in self.catalog],
                "has_more": False,
                "first_id": self.catalog[0].alias if self.catalog else None,
                "last_id": self.catalog[-1].alias if self.catalog else None,
            }
            return 200, {"Content-Type": "application/json"}, json.dumps(payload).encode("utf-8")

        if method != "POST" or target != "/v1/messages":
            return self._json_error(404, f"Unsupported path: {target}")

        try:
            req = json.loads(body.decode("utf-8"))
        except Exception as exc:
            return self._json_error(400, "Invalid JSON body", str(exc))

        model_alias = req.get("model")
        if not isinstance(model_alias, str) or not model_alias:
            return self._json_error(400, "missing model in request")
        model = self._model_by_alias(model_alias)
        if not model:
            return self._json_error(
                400,
                "unknown Codex model alias",
                f'model "{model_alias}" is not in catalog',
            )

        try:
            responses = translate.anthropic_request_to_responses(req)
        except Exception as exc:
            return self._json_error(400, f"invalid request body: {exc}")

        stream = bool(req.get("stream", False))
        try:
            events = self.event_stream(
                payload=responses,
                model=model.slug,
                reasoning_effort=model.reasoning_effort,
                service_tier=os.environ.get("TALARIA_SERVICE_TIER") or None,
            )
        except Exception as exc:
            return self._json_error(502, f"upstream stream init failed: {exc}")

        if stream:
            out = b"".join(translate.events_to_anthropic_sse(events, model.alias))
            headers = {"Content-Type": "text/event-stream", "Cache-Control": "no-cache"}
            return 200, headers, out

        non_stream_events = list(events)
        return (
            200,
            {"Content-Type": "application/json"},
            translate.events_to_anthropic_json(non_stream_events, model.alias),
        )


def create_http_handler(app: TalariaApp):
    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            status, headers, body = app.handle("GET", self.path, dict(self.headers), b"")
            self._write_response(status, headers, body)

        def do_POST(self):
            length = self.headers.get("Content-Length")
            body = b""
            if length:
                try:
                    body = self.rfile.read(int(length))
                except Exception:
                    body = b""
            status, headers, body = app.handle("POST", self.path, dict(self.headers), body)
            self._write_response(status, headers, body)

        def _write_response(self, status: int, headers: dict[str, str], body: bytes):
            self.send_response(status)
            for key, value in headers.items():
                self.send_header(key, value)
            if isinstance(body, (bytes, bytearray)):
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self.end_headers()

        def log_message(self, format: str, *args):  # pragma: no cover - silent
            return

    return _Handler


def run_server(host: str, port: int, catalog: Iterable[CodexModel], event_stream: EventStream = codex.stream_events):
    app = TalariaApp(catalog, event_stream=event_stream)
    handler = create_http_handler(app)
    httpd = ThreadingHTTPServer((host, port), handler)
    return httpd, app
