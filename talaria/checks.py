"""Shared diagnostics and local smoke helpers for Talaria."""

from __future__ import annotations

from contextlib import contextmanager
import ipaddress
import json
import os
import shutil
import socket
import ssl
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from . import codex
from .catalog import CodexCatalogError, CodexModel, discover_catalog
from .server import run_server


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    message: str
    required: bool = True


def is_loopback_host(host: str) -> bool:
    if host in ("127.0.0.1", "localhost", "::1"):
        return True
    cleaned = host.strip("[]")
    try:
        return ipaddress.ip_address(cleaned).is_loopback
    except Exception:
        return False


def check_python() -> Check:
    import sys

    version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    return Check("python", True, version)


def check_binary(name: str, version_args: list[str] | tuple[str, ...] = ("--version",), required: bool = True) -> Check:
    path = shutil.which(name)
    if not path:
        return Check(name, False, "NOT FOUND", required=required)

    try:
        proc = subprocess.run([name, *version_args], capture_output=True, text=True, timeout=4, check=False)
        output = ((proc.stdout or proc.stderr or "").strip().splitlines()[:1] + [""])[0]
        if output:
            return Check(name, True, output)
        if proc.returncode != 0:
            return Check(name, False, "version unavailable", required=required)
    except Exception:
        return Check(name, False, "failed to run version check", required=required)

    return Check(name, True, "ok")


def check_codex_login() -> Check:
    try:
        proc = subprocess.run(
            ["codex", "login", "status"],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        output = "\n".join(part for part in (proc.stdout, proc.stderr) if part).strip()
    except FileNotFoundError:
        return Check("codex login", False, "codex not installed", required=True)
    except Exception as exc:
        return Check("codex login", False, f"codex login status failed: {exc}", required=True)

    if proc.returncode != 0:
        return Check("codex login", False, "codex login status failed", required=True)
    if "Logged in using ChatGPT" not in output:
        return Check("codex login", False, "codex is not logged in with ChatGPT", required=True)
    return Check("codex login", True, "ok")


def check_model_catalog() -> tuple[Check, list[CodexModel] | None]:
    try:
        catalog = discover_catalog()
        return Check("model catalog", True, f"{len(catalog)} visible"), catalog
    except CodexCatalogError as exc:
        return Check("model catalog", False, str(exc)), None
    except Exception as exc:
        return Check("model catalog", False, str(exc)), None


def check_tls() -> Check:
    cert_paths = ssl.get_default_verify_paths()
    candidate = cert_paths.cafile
    fallback = str(codex.SYSTEM_CERT_FILE)
    cert_label = "system"
    candidate_file = bool(candidate and Path(candidate).is_file())
    context = ssl.create_default_context()

    if candidate_file:
        context = ssl.create_default_context(cafile=candidate)
        cert_label = candidate
    elif Path(fallback).is_file():
        context = ssl.create_default_context(cafile=fallback)
        cert_label = fallback

    try:
        request = urllib.request.Request("https://chatgpt.com", method="HEAD")
        request.add_header("User-Agent", "talaria-doctor")
        with urllib.request.urlopen(request, timeout=4, context=context) as response:
            _ = response.status
            return Check("tls", True, cert_label)
    except urllib.error.URLError as exc:
        detail = str(exc)
        if candidate_file:
            return Check("tls", False, f"Python SSL issue using {candidate}: {detail}")
        return Check("tls", False, f"TLS check failed: {detail}")
    except Exception as exc:
        return Check("tls", False, f"TLS check failed: {exc}")


def check_gateway_cache(cache_path: str | None = None) -> Check:
    path = Path(
        cache_path
        if cache_path is not None
        else os.environ.get("TALARIA_GATEWAY_CACHE", str(Path.home() / ".claude/cache/gateway-models.json"))
    ).expanduser()

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, prefix=".talaria-cache-test-", delete=True) as handle:
            handle.write(str(int(time.time() * 1000)))
            handle.flush()
        return Check("gateway cache", True, str(path))
    except Exception as exc:
        return Check("gateway cache", False, str(exc))


def check_loopback_bind(host: str, port: int) -> Check:
    if not is_loopback_host(host):
        return Check("loopback bind", False, f"{host} is not loopback")

    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    sock = socket.socket(family, socket.SOCK_STREAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((host, port))
        actual = sock.getsockname()[1]
        return Check("loopback bind", True, f"{host}:{actual}")
    except Exception as exc:
        return Check("loopback bind", False, str(exc))
    finally:
        try:
            sock.close()
        except Exception:
            pass


def _http_json(url: str, timeout: float = 1.5):
    request = urllib.request.Request(url, method="GET")
    request.add_header("Accept", "application/json")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.getcode(), json.loads(response.read().decode("utf-8"))


@contextmanager
def run_local_gateway(
    host: str,
    port: int,
    catalog: Iterable[CodexModel],
    event_stream: Callable[..., Iterable[dict]] = codex.stream_events,
):
    httpd, app = run_server(host=host, port=port, catalog=list(catalog), event_stream=event_stream)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://{host}:{httpd.server_address[1]}"

    try:
        yield base_url, app
    finally:
        httpd.shutdown()
        thread.join(timeout=2)
        try:
            httpd.server_close()
        except Exception:
            pass


def run_local_gateway_smoke(
    host: str,
    port: int,
    catalog: Iterable[CodexModel],
    event_stream=codex.stream_events,
    request_timeout: float = 1.5,
) -> tuple[list[Check], str]:
    checks: list[Check] = []

    with run_local_gateway(host, port, catalog, event_stream=event_stream) as (base_url, app):
        try:
            status, payload = _http_json(f"{base_url}/healthz", timeout=request_timeout)
            checks.append(
                Check("healthz", status == 200 and isinstance(payload, dict) and bool(payload.get("ok", False)), "ok")
            )
        except Exception as exc:
            checks.append(Check("healthz", False, str(exc)))

        try:
            status, payload = _http_json(f"{base_url}/v1/models", timeout=request_timeout)
            models = (payload.get("data") if isinstance(payload, dict) else None)
            has_models = bool(models)
            checks.append(Check("models", status == 200 and has_models, "ok" if has_models else "none"))
        except Exception as exc:
            checks.append(Check("models", False, str(exc)))

        browser_ok = False
        json_ok = False
        try:
            status, _, _ = app.handle(
                "POST",
                "/v1/messages",
                {"Content-Type": "application/json", "Origin": "https://evil.example"},
                b'{"model":""}',
            )
            browser_ok = status == 403
        except Exception:
            browser_ok = False

        try:
            status, _, _ = app.handle(
                "POST",
                "/v1/messages",
                {"Content-Type": "text/plain"},
                b'{"model":""}',
            )
            json_ok = status == 415
        except Exception:
            json_ok = False

        checks.append(Check("security controls", browser_ok and json_ok, "ok" if browser_ok and json_ok else "failed"))

    return checks, base_url
