"""HTTP adapter for Codex Responses API via local `codex` CLI credentials."""

from __future__ import annotations

import base64
import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path


CODEX_HOME = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
AUTH_FILE = CODEX_HOME / "auth.json"
RESPONSES_URL = "https://chatgpt.com/backend-api/codex/responses"
DEFAULT_REASONING_EFFORT = os.environ.get("TALARIA_REASONING_EFFORT", "medium")
DEFAULT_SERVICE_TIER = os.environ.get("TALARIA_SERVICE_TIER", "").strip()


class CodexAuthError(RuntimeError):
    """Raised when local Codex auth material cannot be read."""


def _decode_jwt_claims(token: str) -> dict:
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload).decode("utf-8"))
    except Exception:
        return {}


def _is_expired(token: str, skew_seconds: int = 120) -> bool:
    claims = _decode_jwt_claims(token)
    exp = claims.get("exp")
    if not isinstance(exp, (int, float)):
        return False
    return time.time() >= (exp - skew_seconds)


def _account_id(token: str) -> str | None:
    claims = _decode_jwt_claims(token)
    auth_block = claims.get("https://api.openai.com/auth") or {}
    if isinstance(auth_block, dict):
        account = auth_block.get("chatgpt_account_id")
        if isinstance(account, str) and account:
            return account
    return None


def _best_effort_refresh() -> None:
    try:
        subprocess.run(["codex", "login", "status"], capture_output=True, timeout=20, check=False)
    except Exception:
        pass


def _load_auth_file() -> dict:
    if not AUTH_FILE.is_file():
        raise CodexAuthError(f"No auth file at {AUTH_FILE}; run `codex login` first.")
    try:
        return json.loads(AUTH_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        raise CodexAuthError(f"Could not read {AUTH_FILE}: {exc}") from exc


def _extract_access_token(state: dict) -> str:
    tokens = state.get("tokens")
    if isinstance(tokens, dict):
        token = tokens.get("access_token")
        if isinstance(token, str) and token:
            return token
    token = state.get("access_token")
    if isinstance(token, str) and token:
        return token
    raise CodexAuthError(f"Could not find access_token in {AUTH_FILE}.")


def access_token() -> str:
    state = _load_auth_file()
    token = _extract_access_token(state)
    if _is_expired(token):
        _best_effort_refresh()
        state = _load_auth_file()
        token = _extract_access_token(state)
        if _is_expired(token):
            raise CodexAuthError("Codex token expired; run `codex login`.")
    return token


def _request_headers(token: str) -> dict[str, str]:
    headers = {
        "Authorization": "Bearer " + token,
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
        "User-Agent": "codex_cli_rs/0.0.0",
        "originator": "codex_cli_rs",
        "OpenAI-Beta": "responses=experimental",
    }
    account = _account_id(token)
    if account:
        headers["ChatGPT-Account-ID"] = account
    return headers


def _as_int(value: str) -> int | None:
    try:
        parsed = int(str(value).strip())
    except Exception:
        return None
    return parsed if parsed > 0 else None


def _iter_sse_events(response):
    buffer = b""
    while True:
        chunk = response.read(4096)
        if not chunk:
            break
        buffer += chunk
        while True:
            split_at = buffer.find(b"\n\n")
            if split_at < 0:
                break
            raw, buffer = buffer[:split_at], buffer[split_at + 2 :]
            raw_lines = raw.splitlines()
            event_name = ""
            payloads = []
            for line in raw_lines:
                if line.startswith(b":"):
                    continue
                if line.startswith(b"event:"):
                    event_name = line[6:].strip().decode("utf-8", "replace")
                elif line.startswith(b"data:"):
                    payloads.append(line[5:].decode("utf-8", "replace").strip())
            if not payloads:
                continue
            for payload in payloads:
                if payload == "[DONE]":
                    continue
                try:
                    obj = json.loads(payload)
                except Exception:
                    continue
                yield event_name, obj


def stream_events(
    payload: dict,
    model: str,
    reasoning_effort: str | None = None,
    service_tier: str | None = None,
):
    """Yield internal Talaria events from Codex streaming responses."""
    try:
        token = access_token()
    except Exception as exc:
        yield {"type": "error", "message": str(exc), "status": 401}
        return

    body = {
        "model": model,
        "input": payload.get("input", []),
        "instructions": payload.get("instructions", ""),
        "store": False,
        "stream": True,
        "parallel_tool_calls": False,
        "reasoning": {"effort": reasoning_effort or DEFAULT_REASONING_EFFORT},
    }
    tools = payload.get("tools")
    if isinstance(tools, list) and tools:
        body["tools"] = tools
    if payload.get("tool_choice") is not None:
        body["tool_choice"] = payload["tool_choice"]

    tier = service_tier or DEFAULT_SERVICE_TIER
    if tier:
        body["service_tier"] = tier
    max_output = _as_int(os.environ.get("TALARIA_MAX_OUTPUT_TOKENS", ""))
    if max_output is not None:
        body["max_output_tokens"] = max_output

    data = json.dumps(body).encode("utf-8")
    headers = _request_headers(token)
    headers["Content-Length"] = str(len(data))
    request = urllib.request.Request(RESPONSES_URL, data=data, headers=headers, method="POST")

    try:
        response = urllib.request.urlopen(request, timeout=600)
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", "replace")[:500]
        except Exception:
            pass
        yield {
            "type": "error",
            "message": f"Codex API HTTP {exc.code}: {detail}",
            "status": exc.code,
        }
        return
    except Exception as exc:
        yield {"type": "error", "message": f"Codex API error: {exc}", "status": 502}
        return

    ctype = response.headers.get("Content-Type", "")
    if "text/event-stream" not in ctype:
        raw = response.read().decode("utf-8", "replace")
        if raw.strip():
            try:
                parsed = json.loads(raw)
            except Exception as exc:
                yield {"type": "error", "message": f"Bad Codex JSON payload: {exc}", "status": 502}
                return
            usage = parsed.get("usage") or {}
            if usage:
                yield {
                    "type": "usage",
                    "input_tokens": int(usage.get("input_tokens", usage.get("prompt_tokens", 0)) or 0),
                    "output_tokens": int(usage.get("output_tokens", usage.get("completion_tokens", 0)) or 0),
                }
        return

    pending: dict[str, dict[str, str]] = {}
    usage = None
    emitted_tool_calls: set[str] = set()

    for event_name, obj in _iter_sse_events(response):
        event_type = (event_name or obj.get("type") or "").strip()
        if event_type == "response.output_text.delta":
            text = obj.get("delta")
            if text is not None:
                yield {"type": "text_delta", "text": str(text)}
            continue

        if event_type == "response.output_item.added":
            output_item = obj.get("output_item") or obj.get("item") or {}
            if isinstance(output_item, dict) and output_item.get("type") in ("function_call", "function"):
                call_id = output_item.get("id") or output_item.get("call_id") or output_item.get("tool_call_id")
                if isinstance(call_id, str) and call_id:
                    name = str(output_item.get("name") or "")
                    raw_args = output_item.get("arguments", "")
                    if not isinstance(raw_args, str):
                        raw_args = json.dumps(raw_args)
                    pending[str(call_id)] = {"id": str(call_id), "name": name, "arguments": str(raw_args)}
            continue

        if event_type == "response.function_call_arguments.delta":
            call_id = obj.get("output_item_id") or obj.get("item_id") or obj.get("call_id") or obj.get("id")
            if not isinstance(call_id, str) or not call_id:
                continue
            delta = obj.get("delta", "")
            slot = pending.setdefault(str(call_id), {"id": str(call_id), "name": "", "arguments": ""})
            slot["arguments"] += str(delta or "")
            continue

        if event_type == "response.function_call_arguments.done":
            output_item_id = obj.get("output_item_id") or obj.get("item_id") or obj.get("call_id") or obj.get("id")
            if not isinstance(output_item_id, str) or not output_item_id:
                continue
            slot = pending.setdefault(str(output_item_id), {"id": str(output_item_id), "name": "", "arguments": ""})
            args = obj.get("arguments")
            if isinstance(args, str):
                slot["arguments"] = args
            elif args is not None:
                slot["arguments"] = json.dumps(args)
            name = obj.get("name")
            if isinstance(name, str):
                slot["name"] = name
            continue

        if event_type == "response.output_item.done":
            output_item = obj.get("output_item") or obj.get("item") or {}
            if not isinstance(output_item, dict):
                continue
            if output_item.get("type") in ("function_call", "function"):
                call_id = output_item.get("id") or output_item.get("call_id") or output_item.get("tool_call_id")
                if not isinstance(call_id, str) or not call_id:
                    continue
                slot = pending.setdefault(
                    str(call_id),
                    {
                        "id": str(call_id),
                        "name": str(output_item.get("name") or ""),
                        "arguments": "",
                    },
                )
                args = output_item.get("arguments")
                if isinstance(args, str):
                    slot["arguments"] = args
                elif args is not None:
                    slot["arguments"] = json.dumps(args)

                if str(call_id) not in emitted_tool_calls and (slot["name"] or slot["arguments"]):
                    yield {
                        "type": "tool_call",
                        "id": slot["id"],
                        "name": slot["name"],
                        "arguments": slot["arguments"] or "{}",
                    }
                    emitted_tool_calls.add(str(call_id))
            continue

        if event_type in ("response.completed", "response.done"):
            src = obj.get("response") if isinstance(obj.get("response"), dict) else obj
            event_usage = src.get("usage") if isinstance(src, dict) else None
            if isinstance(event_usage, dict):
                usage = {
                    "input_tokens": int(event_usage.get("input_tokens", event_usage.get("prompt_tokens", 0)) or 0),
                    "output_tokens": int(event_usage.get("output_tokens", event_usage.get("completion_tokens", 0)) or 0),
                }
            continue

        if event_type == "response.failed":
            yield {
                "type": "error",
                "message": obj.get("error", obj.get("message", "Codex stream failed")),
                "status": 502,
            }
            return

        if event_type == "error":
            yield {"type": "error", "message": obj.get("message", "Codex stream error"), "status": 502}
            return

    for call_id, slot in pending.items():
        if call_id in emitted_tool_calls:
            continue
        if slot.get("id") and (slot.get("name") or slot.get("arguments")):
            yield {
                "type": "tool_call",
                "id": slot["id"],
                "name": slot["name"],
                "arguments": slot["arguments"] or "{}",
            }

    if usage is not None:
        yield {"type": "usage", **usage}
