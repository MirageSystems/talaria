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
MAX_BODY_BYTES = 8 * 1024 * 1024
MAX_RESPONSE_EVENTS = 4096
MAX_RESPONSE_CHARS = 4 * 1024 * 1024


def _header_value(headers: dict, name: str) -> str:
    target = name.lower()
    for key, value in (headers or {}).items():
        if str(key).lower() == target:
            return str(value)
    return ""


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

    def _upstream_error(self, status: int) -> tuple[int, dict, bytes]:
        if status == 401:
            return self._json_error(401, "Codex authentication failed; run `codex login`.")
        return self._json_error(status, "Codex upstream request failed")

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

        origin = _header_value(headers, "origin")
        fetch_site = _header_value(headers, "sec-fetch-site").lower()
        if origin or (fetch_site and fetch_site not in ("none", "same-origin")):
            return self._json_error(403, "browser-origin requests are not accepted")

        content_type = _header_value(headers, "content-type").split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            return self._json_error(415, "POST /v1/messages requires application/json")

        if len(body) > MAX_BODY_BYTES:
            return self._json_error(413, "request body too large")

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
        except Exception:
            return self._upstream_error(502)

        if stream:
            event_list = list(_bounded_events(events))
            error = _first_error(event_list)
            if error:
                return self._upstream_error(int(error.get("status", 502) or 502))
            out = b"".join(translate.events_to_anthropic_sse(event_list, model.alias))
            headers = {"Content-Type": "text/event-stream", "Cache-Control": "no-cache"}
            return 200, headers, out

        non_stream_events = list(_bounded_events(events))
        error = _first_error(non_stream_events)
        if error:
            return self._upstream_error(int(error.get("status", 502) or 502))
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
                    body_len = int(length)
                except Exception:
                    body_len = 0
                if body_len > MAX_BODY_BYTES:
                    status, headers, body = app._json_error(413, "request body too large")
                    self._write_response(status, headers, body)
                    return
                body = self.rfile.read(body_len) if body_len > 0 else b""
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


def _first_error(events: Iterable[dict]) -> dict | None:
    for event in events:
        if isinstance(event, dict) and event.get("type") == "error":
            return event
    return None


def _event_chars(event) -> int:
    if isinstance(event, str):
        return len(event)
    if isinstance(event, dict):
        return sum(_event_chars(key) + _event_chars(value) for key, value in event.items())
    if isinstance(event, list):
        return sum(_event_chars(item) for item in event)
    return 0


def _bounded_events(events: Iterable[dict]) -> Iterable[dict]:
    count = 0
    chars = 0
    for event in events:
        count += 1
        chars += _event_chars(event)
        if count > MAX_RESPONSE_EVENTS or chars > MAX_RESPONSE_CHARS:
            yield {"type": "error", "message": "upstream response exceeded Talaria limits", "status": 502}
            return
        yield event


def run_server(host: str, port: int, catalog: Iterable[CodexModel], event_stream: EventStream = codex.stream_events):
    app = TalariaApp(catalog, event_stream=event_stream)
    handler = create_http_handler(app)
    httpd = ThreadingHTTPServer((host, port), handler)
    return httpd, app
