"""Pre-flight diagnostics for Talaria."""

from __future__ import annotations

import shutil
import subprocess

from .catalog import discover_catalog, CodexCatalogError


def _check_binary(name: str) -> bool:
    return shutil.which(name) is not None


def _check_codex_login() -> tuple[bool, str]:
    try:
        out = subprocess.run(
            ["codex", "login", "status"],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        stdout = (out.stdout or "").strip()
        if out.returncode != 0:
            return False, "codex login status failed."
        if "Logged in using ChatGPT" not in stdout:
            return False, "codex is not logged in with ChatGPT."
        return True, "codex login present."
    except Exception as exc:
        return False, f"codex check failed: {exc}"


def run() -> int:
    ok = True

    if not _check_binary("python3"):
        print("python3: NOT FOUND")
        ok = False
    else:
        print("python3: ok")

    if not _check_binary("claude"):
        print("claude: NOT FOUND")
        ok = False
    else:
        print("claude: ok")

    if not _check_binary("codex"):
        print("codex: NOT FOUND")
        ok = False
    else:
        print("codex: ok")

    codex_ok, codex_msg = _check_codex_login()
    print(f"codex login: {'ok' if codex_ok else 'fail'} ({codex_msg})")
    if not codex_ok:
        ok = False

    if not ok:
        print("talaria doctor: FAILED")
        return 1

    try:
        discover_catalog()
        print("codex model catalog: ok")
    except CodexCatalogError as exc:
        print(f"codex model catalog: fail ({exc})")
        ok = False
    except Exception as exc:
        print(f"codex model catalog: fail ({exc})")
        ok = False

    if ok:
        print("talaria doctor: pass")
        return 0
    print("talaria doctor: FAILED")
    return 1


if __name__ == "__main__":
    raise SystemExit(run())
