"""Shared helpers for the PGD tests (stdlib only, offline)."""
import json, os, subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures"
sys.path.insert(0, str(ROOT))


def run(*args, env=None, timeout=600):
    """python <args> in the repo root; PGD_HOME unset unless env sets it."""
    e = {k: v for k, v in os.environ.items() if k != "PGD_HOME"}
    e["PYTHONIOENCODING"] = "utf-8"
    e.update(env or {})
    return subprocess.run([sys.executable, *map(str, args)], cwd=ROOT, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env=e, timeout=timeout)


def load_json(p, tries=3):
    """Read JSON, retrying a file another process is writing right now."""
    for i in range(tries):
        try:
            return json.loads(Path(p).read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError, PermissionError):
            if i == tries - 1:
                raise
            time.sleep(2)


def card_files():
    return sorted((ROOT / "cards").glob("*.json"))
