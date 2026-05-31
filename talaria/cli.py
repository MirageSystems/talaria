"""Talaria command-line entrypoint."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
import urllib.request
from pathlib import Path

from .catalog import discover_catalog, CodexCatalogError
from .doctor import run as run_doctor
from .server import run_server


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except Exception:
        return default


def gateway_cache_payload(base_url: str, models: list[dict], now_ms: int | None = None) -> dict:
    payload_models = []
    for model in models:
        model_id = model.get("id") if isinstance(model, dict) else None
        if not model_id:
            continue
        payload_models.append(
            {
                "id": model_id,
                "display_name": model.get("display_name", model_id),
            }
        )
    return {
        "baseUrl": base_url,
        "fetchedAt": int(time.time() * 1000) if now_ms is None else int(now_ms),
        "models": payload_models,
    }


def _write_gateway_cache(base_url: str, models: list[dict]) -> None:
    path = Path(os.environ.get("TALARIA_GATEWAY_CACHE", str(Path.home() / ".claude/cache/gateway-models.json")))
    cache_path = path.expanduser()
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    payload = gateway_cache_payload(base_url, models)
    cache_path.write_text(json.dumps(payload), encoding="utf-8")


def _parse_host_port_args(argv: list[str]) -> tuple[str, int, list[str]]:
    host = os.environ.get("TALARIA_HOST", "127.0.0.1")
    port = _env_int("TALARIA_PORT", 8141)
    remaining: list[str] = []
    i = 0
    while i < len(argv):
        token = argv[i]
        if token == "--host" and i + 1 < len(argv):
            host = argv[i + 1]
            i += 2
            continue
        if token == "--port" and i + 1 < len(argv):
            try:
                port = int(argv[i + 1])
            except Exception:
                pass
            i += 2
            continue
        remaining.append(token)
        i += 1
    return host, port, remaining


def claude_launch_args(args: list[str]) -> list[str]:
    out: list[str] = []
    skip_permissions = os.environ.get("TALARIA_DANGEROUSLY_SKIP_PERMISSIONS", "").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    for arg in args:
        if arg in ("--dangerously-skip-permission", "--dangerously-skip-permissions"):
            skip_permissions = True
            continue
        out.append(arg)
    if skip_permissions and "--dangerously-skip-permissions" not in out:
        out.append("--dangerously-skip-permissions")
    return out


def _wait_for_server(base_url: str, timeout: float = 4.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(base_url.rstrip("/") + "/healthz", timeout=0.5) as response:
                if response.getcode() == 200:
                    return
        except Exception:
            time.sleep(0.05)
    raise RuntimeError(f"server did not become healthy at {base_url}")


def _catalog_model_payloads(catalog) -> list[dict]:
    return [{"id": m.alias, "display_name": m.display_name} for m in catalog]


def run_server_mode(host: str, port: int) -> int:
    try:
        catalog = discover_catalog()
    except CodexCatalogError as exc:
        print(f"talaria server: {exc}")
        return 1

    httpd, _app = run_server(host=host, port=port, catalog=catalog)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://{host}:{port}"

    try:
        _wait_for_server(base_url)
        _write_gateway_cache(base_url, _catalog_model_payloads(catalog))
    except Exception as exc:
        print(f"talaria server: {exc}")
        httpd.shutdown()
        thread.join(timeout=2)
        return 1

    print(f"Talaria server running at {base_url}")
    print("Press Ctrl-C to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        httpd.shutdown()
        thread.join(timeout=2)
    return 0


def run_launch(cli_args: list[str]) -> int:
    host, port, remaining = _parse_host_port_args(cli_args)
    remaining = claude_launch_args(remaining)
    base_url = f"http://{host}:{port}"

    if shutil.which("claude") is None:
        print("claude CLI not found. Install with: npm i -g @anthropic-ai/claude-code")
        return 1

    try:
        catalog = discover_catalog()
    except CodexCatalogError as exc:
        print(f"talaria: {exc}")
        return 1

    httpd, _app = run_server(host=host, port=port, catalog=catalog)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()

    try:
        _wait_for_server(base_url)
        _write_gateway_cache(base_url, _catalog_model_payloads(catalog))

        env = os.environ.copy()
        env.update(
            {
                "ANTHROPIC_BASE_URL": base_url,
                "CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY": "1",
                "CLAUDE_CODE_WORKFLOWS": "1",
            }
        )
        print("Launching Claude Code with Talaria gateway at", base_url)
        proc = subprocess.run(["claude", *remaining], env=env, check=False)
        return proc.returncode
    finally:
        httpd.shutdown()
        thread.join(timeout=2)


def run(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else __import__("sys").argv[1:])
    if args and args[0] == "doctor":
        return run_doctor()
    if args and args[0] == "serve":
        host, port, remaining = _parse_host_port_args(args[1:])
        return run_server_mode(host=host, port=port)

    return run_launch(args)


if __name__ == "__main__":
    raise SystemExit(run())
