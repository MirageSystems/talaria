"""Talaria smoke validation command logic."""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from .checks import (
    Check,
    check_codex_login,
    check_gateway_cache,
    check_loopback_bind,
    check_model_catalog,
    check_python,
    run_local_gateway,
    run_local_gateway_smoke,
)


def parse_smoke_args(argv: list[str]) -> tuple[bool, str | None]:
    live = False
    model = None

    i = 0
    while i < len(argv):
        token = argv[i]
        if token == "--live":
            live = True
            i += 1
            continue
        if token == "--model" and i + 1 < len(argv):
            model = argv[i + 1]
            i += 2
            continue
        i += 1

    return live, model


def _request_json(url: str, body: dict, timeout: float = 10.0):
    payload = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        method="POST",
        headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        status = response.getcode()
        data = response.read()
    return status, data


def _sse_has_text(body: bytes) -> bool:
    text = body.decode("utf-8", "replace")
    return ("message_start" in text and "text_delta" in text) or "message_stop" in text


def _json_has_text(body: bytes) -> bool:
    try:
        payload = json.loads(body.decode("utf-8", "replace"))
    except Exception:
        return False

    content = payload.get("content") if isinstance(payload, dict) else None
    if not isinstance(content, list):
        return False
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text" and block.get("text"):
            return True
    return False


def _format_status(check: Check) -> str:
    return f"{check.name}: {'ok' if check.ok else 'fail'} ({check.message})"


def run_live_check(base_url: str, model_alias: str, stream: bool) -> Check:
    endpoint = f"{base_url}/v1/messages"
    body = {
        "model": model_alias,
        "messages": [{"role": "user", "content": "Reply exactly OK."}],
        "stream": stream,
    }

    try:
        status, data = _request_json(endpoint, body, timeout=30.0)
        if status != 200:
            return Check("live stream" if stream else "live non-stream", False, f"HTTP {status}")
        if stream:
            return Check("live stream", _sse_has_text(data), "ok" if _sse_has_text(data) else "missing stream text")
        return Check("live non-stream", _json_has_text(data), "ok" if _json_has_text(data) else "missing message text")
    except urllib.error.URLError as exc:
        return Check("live stream" if stream else "live non-stream", False, str(exc))
    except Exception as exc:
        return Check("live stream" if stream else "live non-stream", False, str(exc))


def run_smoke(argv: list[str]) -> int:
    live, model = parse_smoke_args(argv)

    print("Talaria smoke")

    checks = [
        check_python(),
        check_codex_login(),
    ]
    catalog_check, catalog = check_model_catalog()
    checks.append(catalog_check)

    if not catalog:
        for check in checks:
            print(_format_status(check))
        print("live non-stream: skipped")
        print("live stream: skipped")
        print("result: fail")
        return 1

    loop_check = check_loopback_bind("127.0.0.1", 0)
    cache_check = check_gateway_cache()
    checks.extend([loop_check, cache_check])

    server_checks, base_url = run_local_gateway_smoke(
        "127.0.0.1",
        0,
        catalog,
        event_stream=lambda **_kwargs: iter(()),
    )
    checks.append(Check("server", bool(base_url), base_url))
    checks.extend(server_checks)

    for check in checks:
        print(_format_status(check))

    live_checks: list[Check] = []
    if live and catalog:
        selected = model or catalog[0].alias
        if model is not None and all(m.alias != model for m in catalog):
            live_checks = [
                Check("live non-stream", False, f"requested model {model} not in catalog"),
                Check("live stream", False, "requested model not found"),
            ]
        else:
            with run_local_gateway("127.0.0.1", 0, catalog) as (live_base_url, _):
                live_checks = [
                    run_live_check(live_base_url, selected, stream=False),
                    run_live_check(live_base_url, selected, stream=True),
                ]

    if live and not live_checks:
        live_checks = [Check("live non-stream", False, "skipped"), Check("live stream", False, "skipped")]

    for check in live_checks:
        print(_format_status(check))

    if not live:
        print("live non-stream: skipped")
        print("live stream: skipped")

    if any(not check.ok for check in checks + live_checks):
        print("result: fail")
        return 1

    print("result: pass")
    return 0
