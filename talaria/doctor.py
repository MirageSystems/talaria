"""Diagnostic command for Talaria."""

from __future__ import annotations

from .checks import (
    Check,
    check_binary,
    check_codex_login,
    check_gateway_cache,
    check_loopback_bind,
    check_model_catalog,
    check_python,
    check_tls,
    run_local_gateway,
    run_local_gateway_smoke,
)
from .smoke import run_live_check


def _parse_doctor_args(args: list[str]) -> tuple[bool, str | None, str, int]:
    live = False
    model = None
    host = "127.0.0.1"
    port = 8141

    i = 0
    while i < len(args):
        token = args[i]
        if token == "--live":
            live = True
            i += 1
            continue
        if token == "--model" and i + 1 < len(args):
            model = args[i + 1]
            i += 2
            continue
        if token == "--host" and i + 1 < len(args):
            host = args[i + 1]
            i += 2
            continue
        if token == "--port" and i + 1 < len(args):
            try:
                port = int(args[i + 1])
            except Exception:
                pass
            i += 2
            continue
        i += 1

    return live, model, host, port


def _format(check: Check) -> str:
    return f"{check.name}: {'ok' if check.ok else 'fail'} ({check.message})"


def _print_checks(checks: list[Check]) -> bool:
    ok = True
    for item in checks:
        print(_format(item))
        if item.required and not item.ok:
            ok = False
    return ok


def run(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else [])
    live, model, host, port = _parse_doctor_args(args)

    print("Talaria doctor")

    checks: list[Check] = [
        check_python(),
        check_binary("node", required=False),
        check_binary("npm", required=False),
        check_binary("claude"),
        check_binary("codex"),
        check_codex_login(),
    ]

    catalog_check, catalog = check_model_catalog()
    checks.append(catalog_check)
    checks.append(check_tls())
    checks.append(check_loopback_bind(host, port))
    checks.append(check_gateway_cache())

    all_ok = _print_checks(checks)

    server_url = ""
    server_checks: list[Check] = []
    if all_ok and catalog:
        server_checks, server_url = run_local_gateway_smoke(host, port, catalog)
    elif all_ok and catalog is not None:
        server_checks, server_url = run_local_gateway_smoke(host, 0, catalog)

    if server_checks:
        all_ok = _print_checks(server_checks) and all_ok

    live_checks: list[Check] = []
    if live:
        if not server_url:
            live_checks.append(Check("live", False, "No successful local server started"))
        elif catalog:
            selected = model or catalog[0].alias
            if model and not any(m.alias == model for m in catalog):
                live_checks.append(Check("live", False, f"requested model {model} not in catalog"))
            else:
                with run_local_gateway(host, port, catalog) as (live_url, _):
                    live_checks = [
                        run_live_check(live_url, selected, stream=False),
                        run_live_check(live_url, selected, stream=True),
                    ]
        _print_checks(live_checks)
        all_ok = all_ok and all(item.ok for item in live_checks)
    else:
        print("live: skipped")

    print(f"result: {'pass' if all_ok else 'fail'}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(run())
