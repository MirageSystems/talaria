"""Anthropic Messages <-> Codex Responses event conversion."""

from __future__ import annotations

import json
import uuid
from typing import Iterable


def _stringify(value) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def _system_to_instructions(system) -> str:
    if not system:
        return ""
    if isinstance(system, str):
        return system
    if not isinstance(system, Iterable) or isinstance(system, dict):
        return ""

    parts: list[str] = []
    for entry in system:
        if not isinstance(entry, dict):
            continue
        if entry.get("type") == "text":
            text = entry.get("text")
            if isinstance(text, str):
                parts.append(text)
    return "\n".join(parts)


def _coerce_content(content):
    if content is None:
        return []
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    if isinstance(content, list):
        return [item for item in content if isinstance(item, dict) and item.get("type")]
    return []


def _normalize_tool_arguments(content):
    if isinstance(content, str):
        return content
    if content is None:
        return ""
    if isinstance(content, (dict, list, int, float, bool)):
        return json.dumps(content, ensure_ascii=False)
    return _stringify(content)


def anthropic_request_to_responses(body: dict) -> dict:
    if not isinstance(body, dict):
        raise TypeError("body must be a dict")

    inputs = []
    for msg in body.get("messages") or []:
        if not isinstance(msg, dict):
            continue
        role = msg.get("role")
        content = _coerce_content(msg.get("content"))
        if role == "assistant":
            for block in content:
                btype = block.get("type")
                if btype == "text":
                    text = block.get("text")
                    if text is not None:
                        inputs.append(
                            {
                                "type": "message",
                                "role": "assistant",
                                "content": [{"type": "output_text", "text": str(text)}],
                            }
                        )
                elif btype == "tool_use":
                    inputs.append(
                        {
                            "type": "function_call",
                            "call_id": block.get("id") or "call_unknown",
                            "name": str(block.get("name") or ""),
                            "arguments": _normalize_tool_arguments(block.get("input")),
                        }
                    )
            continue

        if role == "tool":
            for block in content:
                if block.get("type") != "tool_result":
                    continue
                inputs.append(
                    {
                        "type": "function_call_output",
                        "call_id": str(block.get("tool_use_id") or block.get("tool_call_id") or "call_unknown"),
                        "output": _normalize_tool_arguments(block.get("content")),
                    }
                )
            continue

        # role == "user" and any other roles
        for block in content:
            if block.get("type") == "text":
                text = block.get("text")
                if text is not None:
                    inputs.append(
                        {
                            "type": "message",
                            "role": "user",
                            "content": [{"type": "input_text", "text": str(text)}],
                        }
                    )
            elif block.get("type") == "tool_result":
                inputs.append(
                    {
                        "type": "function_call_output",
                        "call_id": str(block.get("tool_use_id") or block.get("tool_call_id") or "call_unknown"),
                        "output": _normalize_tool_arguments(block.get("content")),
                    }
                )

    tools = []
    for tool in body.get("tools") or []:
        if not isinstance(tool, dict):
            continue
        name = tool.get("name")
        if not isinstance(name, str) or not name:
            continue
        schema = tool.get("input_schema")
        if not isinstance(schema, dict):
            schema = {"type": "object", "properties": {}}
        tools.append(
            {
                "type": "function",
                "name": name,
                "description": str(tool.get("description") or ""),
                "parameters": schema,
                "strict": False,
            }
        )

    tool_choice = body.get("tool_choice")
    if isinstance(tool_choice, dict):
        choice_type = tool_choice.get("type")
        if choice_type == "auto":
            tool_choice = "auto"
        elif choice_type == "any":
            tool_choice = "required"
        elif choice_type == "tool":
            tname = tool_choice.get("name")
            if isinstance(tname, str) and tname:
                tool_choice = {"type": "function", "name": tname}
            else:
                tool_choice = "auto"
        else:
            tool_choice = "auto"

    body_out = {"input": inputs}
    instructions = _system_to_instructions(body.get("system"))
    if instructions:
        body_out["instructions"] = instructions
    if tools:
        body_out["tools"] = tools
    if tool_choice is not None:
        body_out["tool_choice"] = tool_choice

    return body_out


def _sse(event: str, data: dict) -> bytes:
    return ("event: %s\ndata: %s\n\n" % (event, json.dumps(data))).encode("utf-8")


def _next_block_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def events_to_anthropic_json(events: Iterable[dict], model_alias: str) -> bytes:
    messages_content = []
    usage = {"input_tokens": 0, "output_tokens": 0}
    saw_tool = False

    for event in events:
        if not isinstance(event, dict):
            continue
        etype = event.get("type")
        if etype == "text_delta":
            text = event.get("text")
            if text:
                messages_content.append({"type": "text", "text": str(text)})
        elif etype == "tool_call":
            saw_tool = True
            args = event.get("arguments")
            if args is None:
                args_obj = {}
            elif isinstance(args, str):
                try:
                    args_obj = json.loads(args)
                except Exception:
                    args_obj = args
            else:
                args_obj = args
            messages_content.append(
                {
                    "type": "tool_use",
                    "id": str(event.get("id") or ""),
                    "name": str(event.get("name") or ""),
                    "input": args_obj,
                }
            )
        elif etype == "usage":
            usage = {
                "input_tokens": int(event.get("input_tokens", 0) or 0),
                "output_tokens": int(event.get("output_tokens", 0) or 0),
            }

    stop_reason = "tool_use" if saw_tool else "end_turn"
    payload = {
        "id": _next_block_id("msg"),
        "type": "message",
        "role": "assistant",
        "model": model_alias,
        "content": messages_content,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": usage,
    }
    return json.dumps(payload).encode("utf-8")


def events_to_anthropic_sse(events: Iterable[dict], model_alias: str):
    msg_id = _next_block_id("msg")
    usage = {"input_tokens": 0, "output_tokens": 0}
    saw_tool = False

    yield _sse(
        "message_start",
        {
            "type": "message_start",
            "message": {
                "id": msg_id,
                "type": "message",
                "role": "assistant",
                "model": model_alias,
                "content": [],
                "stop_reason": None,
                "stop_sequence": None,
                "usage": {"input_tokens": 0, "output_tokens": 0},
            },
        },
    )

    open_index = None
    open_block_type = None
    next_block_index = 0

    for event in events:
        if not isinstance(event, dict):
            continue
        etype = event.get("type")
        if etype == "text_delta":
            text = event.get("text")
            if text is None:
                continue
            if open_block_type != "text":
                if open_index is not None:
                    yield _sse("content_block_stop", {"type": "content_block_stop", "index": open_index})
                open_index = next_block_index
                next_block_index += 1
                open_block_type = "text"
                yield _sse(
                    "content_block_start",
                    {
                        "type": "content_block_start",
                        "index": open_index,
                        "content_block": {
                            "type": "text",
                            "text": "",
                            "id": _next_block_id("txt"),
                        },
                    },
                )
            yield _sse(
                "content_block_delta",
                {
                    "type": "content_block_delta",
                    "index": open_index,
                    "delta": {"type": "text_delta", "text": str(text)},
                },
            )
            continue

        if etype == "tool_call":
            args = event.get("arguments", "{}")
            if isinstance(args, str):
                try:
                    parsed_args = json.loads(args)
                except Exception:
                    parsed_args = args
            else:
                parsed_args = args
            if open_index is not None:
                yield _sse("content_block_stop", {"type": "content_block_stop", "index": open_index})
                open_index = None
                open_block_type = None
            block_id = str(event.get("id") or _next_block_id("tool"))
            block_index = next_block_index
            next_block_index += 1
            yield _sse(
                "content_block_start",
                {
                    "type": "content_block_start",
                    "index": block_index,
                    "content_block": {
                        "type": "tool_use",
                        "id": block_id,
                        "name": str(event.get("name") or ""),
                        "input": parsed_args if isinstance(parsed_args, dict) else {},
                    },
                },
            )
            if args is not None:
                yield _sse(
                    "content_block_delta",
                    {
                        "type": "content_block_delta",
                        "index": block_index,
                        "delta": {
                            "type": "input_json_delta",
                            "partial_json": str(args),
                        },
                    },
                )
            yield _sse("content_block_stop", {"type": "content_block_stop", "index": block_index})
            saw_tool = True
            continue

        if etype == "usage":
            usage = {
                "input_tokens": int(event.get("input_tokens", 0) or 0),
                "output_tokens": int(event.get("output_tokens", 0) or 0),
            }

    if open_index is not None:
        yield _sse("content_block_stop", {"type": "content_block_stop", "index": open_index})

    stop_reason = "tool_use" if saw_tool else "end_turn"
    yield _sse(
        "message_delta",
        {
            "type": "message_delta",
            "delta": {"stop_reason": stop_reason},
            "usage": usage,
        },
    )
    yield _sse(
        "message_stop",
        {"type": "message_stop", "message": {"id": msg_id, "stop_reason": stop_reason}},
    )
