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

from . import codex
from .checks import (
    Check,
    check_binary,
    check_python,
    check_codex_login,
    check_gateway_cache,
    check_loopback_bind,
    check_model_catalog,
    check_tls,
    is_loopback_host,
    run_local_gateway_smoke,
)
from .doctor import run as run_doctor
from .smoke import run_smoke
from .catalog import discover_catalog, CodexCatalogError
from .server import run_server


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except Exception:
        return default


def _cli_gateway_cache_path() -> Path:
    return Path(os.environ.get("TALARIA_GATEWAY_CACHE", str(Path.home() / ".claude/cache/gateway-models.json"))).expanduser()


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
    cache_path = _cli_gateway_cache_path()
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    payload = gateway_cache_payload(base_url, models)
    cache_path.write_text(json.dumps(payload), encoding="utf-8")


def _print_security_summary(base_url: str, catalog: list, gateway_cache: str) -> None:
    models = ", ".join(model.alias for model in catalog)
    print(f"Talaria listening on {base_url}")
    print(f"Codex backend: {codex.RESPONSES_URL}")
    print("Browser-origin requests: blocked")
    print("Message content type: application/json required")
    print("Request body cap: 8 MiB")
    print(f"Gateway cache: {gateway_cache}")
    print(f"Models: {models}")


def _format_check(check: Check) -> str:
    return f"{check.name}: {'ok' if check.ok else 'fail'} ({check.message})"


def _run_launch_checks(host: str, port: int) -> tuple[bool, list[Check], list]:
    checks: list[Check] = [
        check_python(),
        check_binary("claude"),
        check_binary("codex"),
        check_codex_login(),
    ]

    catalog_check, catalog = check_model_catalog()
    checks.append(catalog_check)
    checks.append(check_tls())
    checks.append(check_loopback_bind(host, port))
    checks.append(check_gateway_cache(str(_cli_gateway_cache_path())))

    for check in checks:
        print(_format_check(check))

    failures = [item for item in checks if item.required and not item.ok]
    return len(failures) == 0, checks, catalog or []


def _print_setup_help(failures: list[Check]) -> None:
    print("Talaria cannot start yet.")
    for failure in failures:
        if failure.name == "claude":
            print("- Missing: Claude Code CLI")
            print("  Install: npm install -g @anthropic-ai/claude-code")
        elif failure.name == "codex":
            print("- Missing: Codex CLI")
            print("  Install: official Codex CLI")
        elif failure.name == "codex login":
            print("- Codex not logged in with ChatGPT")
            print("  Run: codex login")
        elif failure.name == "model catalog":
            print("- No visible Codex models")
            print("  Check with: codex debug models")
        elif failure.name == "tls":
            print("- TLS verification failed")
            print("  Run: talaria doctor")
        elif failure.name == "loopback bind":
            print("- Cannot bind loopback host")
            print("  Use 127.0.0.1 or localhost")

    print("Then run: talaria doctor")


def run_server_mode(host: str, port: int) -> int:
    if not is_loopback_host(host):
        print(f"talaria serve: non-loopback host {host} is blocked in v1")
        print("Use --host 127.0.0.1")
        return 1

    try:
        catalog = discover_catalog()
    except CodexCatalogError as exc:
        print(f"talaria serve: {exc}")
        return 1

    httpd, app = run_server(host=host, port=port, catalog=catalog)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()

    base_url = f"http://{host}:{httpd.server_address[1]}"
    try:
        _wait_for_server(base_url)
        _write_gateway_cache(base_url, _catalog_model_payloads(catalog))
        _print_security_summary(base_url, catalog, str(_cli_gateway_cache_path()))

        print("Press Ctrl-C to stop.")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        httpd.shutdown()
        thread.join(timeout=2)
        try:
            httpd.server_close()
        except Exception:
            pass
    return 0


def _run_setup_or_launch_checks(host: str, port: int, command: str) -> tuple[bool, list[Check], list]:
    ok, checks, catalog = _run_launch_checks(host, port)

    failed = [item for item in checks if item.required and not item.ok]
    if failed:
        if command == "setup":
            _print_setup_help(failed)
            return False, checks, catalog
        if command == "launch":
            _print_setup_help(failed)
            return False, checks, catalog
    return ok, checks, catalog


def run_setup(argv: list[str]) -> int:
    host, port, _ = _parse_host_port_args(argv)

    if not is_loopback_host(host):
        print(f"talaria setup: non-loopback host {host} is blocked in v1")
        print("Use --host 127.0.0.1")
        return 1

    if not _run_setup_or_launch_checks(host, port, "setup")[0]:
        return 1

    print("Talaria setup: pass")
    return 0


def run_launch(argv: list[str]) -> int:
    host, port, remaining = _parse_host_port_args(argv)
    remaining = claude_launch_args(remaining)

    if not is_loopback_host(host):
        print(f"Talaria refuses non-loopback host: {host}")
        print("Use --host 127.0.0.1")
        return 1

    if shutil.which("claude") is None:
        print("claude CLI not found. Install with: npm i -g @anthropic-ai/claude-code")
        return 1

    passed, _checks, catalog = _run_setup_or_launch_checks(host, port, "launch")
    if not passed:
        return 1

    try:
        httpd, _app = run_server(host=host, port=port, catalog=catalog)
    except Exception as exc:
        print(f"talaria: server start failed ({exc})")
        return 1

    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()

    try:
        actual_url = f"http://{host}:{httpd.server_address[1]}"
        _wait_for_server(actual_url)
        _write_gateway_cache(actual_url, _catalog_model_payloads(catalog))
        _print_security_summary(actual_url, catalog, str(_cli_gateway_cache_path()))

        env = os.environ.copy()
        env.update(
            {
                "ANTHROPIC_BASE_URL": actual_url,
                "CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY": "1",
                "CLAUDE_CODE_WORKFLOWS": "1",
            }
        )
        print(f"Launching Claude Code with Talaria gateway at {actual_url}")
        proc = subprocess.run(["claude", *remaining], env=env, check=False)
        return proc.returncode
    finally:
        httpd.shutdown()
        thread.join(timeout=2)
        try:
            httpd.server_close()
        except Exception:
            pass


def run(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else __import__("sys").argv[1:])

    if args and args[0] == "doctor":
        return run_doctor(args[1:])
    if args and args[0] == "smoke":
        return run_smoke(args[1:])
    if args and args[0] == "setup":
        return run_setup(args[1:])
    if args and args[0] == "serve":
        host, port, _ = _parse_host_port_args(args[1:])
        return run_server_mode(host=host, port=port)

    return run_launch(args)


if __name__ == "__main__":
    raise SystemExit(run())
