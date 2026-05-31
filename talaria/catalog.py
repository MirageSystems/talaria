"""Catalog discovery from the local `codex` CLI."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import Any, Iterable, List


class CodexCatalogError(Exception):
    """Raised when the Codex model catalog cannot be read."""


@dataclass(frozen=True)
class CodexModel:
    """Canonical local representation of a visible Codex model."""

    slug: str
    alias: str
    display_name: str
    reasoning_effort: str = "medium"

    def anthropic_model(self) -> dict[str, object]:
        return {
            "type": "language_model",
            "id": self.alias,
            "display_name": self.display_name,
            "created_at": "2026-01-01T00:00:00Z",
        }


def _extract_json(text: str) -> dict[str, Any]:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        raise CodexCatalogError("Could not parse Codex JSON payload.")
    payload = text[start : end + 1]
    try:
        return json.loads(payload)
    except json.JSONDecodeError as exc:
        raise CodexCatalogError(f"Could not parse Codex JSON payload: {exc}") from exc


def _run_codex(args: list[str]) -> str:
    executable = shutil.which("codex")
    if not executable:
        raise CodexCatalogError("`codex` CLI is not installed or not on PATH.")
    try:
        proc = subprocess.run(
            [executable, *args],
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception as exc:
        raise CodexCatalogError(f"Failed to run `{executable} {' '.join(args)}`: {exc}") from exc
    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        if not stderr:
            stderr = "unknown error"
        raise CodexCatalogError(f"`{executable} {' '.join(args)}` failed: {stderr}")
    return "\n".join(part for part in (proc.stdout, proc.stderr) if part)


def catalog_from_debug_json(raw: dict[str, object]) -> List[CodexModel]:
    """Build visible Codex models from `codex debug models` output."""
    if not isinstance(raw, dict):
        raise CodexCatalogError("Invalid catalog payload: expected a JSON object.")

    models: list[CodexModel] = []
    seen: set[str] = set()
    for item in raw.get("models", []):
        if not isinstance(item, dict):
            continue
        if item.get("visibility") != "list":
            continue
        slug = item.get("slug")
        if not isinstance(slug, str) or not slug.strip():
            continue
        canonical = slug.strip()
        if canonical in seen:
            continue
        alias = f"claude-{slug.strip()}"
        display_name = item.get("display_name") or slug
        if not isinstance(display_name, str):
            display_name = slug
        reasoning = item.get("default_reasoning_level") or item.get("reasoning_effort") or "medium"
        if not isinstance(reasoning, str):
            reasoning = "medium"
        seen.add(canonical)
        models.append(
            CodexModel(
                slug=canonical,
                alias=alias,
                display_name=display_name.strip() if isinstance(display_name, str) else slug,
                reasoning_effort=reasoning.strip() or "medium",
            )
        )

    if not models:
        raise CodexCatalogError("No visible Codex models are available for this account.")
    return models


def discover_catalog() -> List[CodexModel]:
    """Read logged-in Codex account model catalog.

    Uses the local `codex` CLI auth context only and never accepts any
    OpenAI API key.
    """
    status = _run_codex(["login", "status"])
    if "Logged in using ChatGPT" not in status:
        raise CodexCatalogError(
            "codex CLI is not logged in with ChatGPT subscription."
        )

    raw = _run_codex(["debug", "models"])
    parsed = _extract_json(raw)
    return catalog_from_debug_json(parsed)
