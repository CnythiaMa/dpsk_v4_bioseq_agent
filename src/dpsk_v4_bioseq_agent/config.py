"""Settings (environment-driven) + the single place that wires in the external LabBench2 checkout.

No hardcoded paths or keys: everything comes from environment variables (see ``.env.example``).
LabBench2 is an *external* dependency (the official eval repo). It is not pip-installable as a
normal package, so we add a local checkout to ``sys.path`` on demand via
:func:`ensure_labbench_on_path` — call it before importing any ``labbench2.*`` / ``evals.*`` module.
"""
import os
import sys
from pathlib import Path

# --- Volcengine Ark (OpenAI-compatible) ---
BASE_URL: str = os.environ.get("ARK_BASE_URL", "https://ark.cn-beijing.volces.com/api/coding/v3").rstrip("/")
API_KEY: str = os.environ.get("ARK_API_KEY", "")
MODEL: str = os.environ.get("ARK_MODEL", "deepseek-v4-flash")
# Deep-thinking toggle for the /api/v3 endpoint: "disabled" | "enabled" | None (omit field).
THINKING: str | None = os.environ.get("ARK_THINKING") or None
MODEL_ALIASES = {"flash": "deepseek-v4-flash", "pro": "deepseek-v4-pro"}

# --- agent loop / HTTP ---
AGENT_MAX_ROUNDS: int = int(os.environ.get("AGENT_MAX_ROUNDS", "14"))   # cloning design agent
SEQQA_MAX_ROUNDS: int = int(os.environ.get("SEQQA_MAX_ROUNDS", "6"))     # seqqa compute agent
HTTP_TIMEOUT: int = int(os.environ.get("HTTP_TIMEOUT", "180"))

# --- external LabBench2 eval repo (scorers / assembly engine / question-file downloader) ---
LABBENCH_ROOT = Path(os.environ.get("LABBENCH_ROOT", "path/to/labbench2"))
LABBENCH_DATA_ROOT = Path(os.environ.get("LABBENCH_DATA_ROOT", "path/to/benchmarks"))

_labbench_wired = False


def ensure_labbench_on_path() -> None:
    """Idempotently add the external LabBench2 checkout to ``sys.path``.

    Call this before importing ``labbench2.*`` / ``evals.*``. Raises a clear error if
    ``LABBENCH_ROOT`` is unset or does not exist.
    """
    global _labbench_wired
    if _labbench_wired:
        return
    if not LABBENCH_ROOT.exists():
        raise RuntimeError(
            f"LABBENCH_ROOT does not exist: {LABBENCH_ROOT}\n"
            "Set the LABBENCH_ROOT environment variable to a local checkout of the LabBench2 "
            "eval repo (https://github.com/EdisonScientific/labbench2). See .env.example."
        )
    for p in (LABBENCH_ROOT, LABBENCH_ROOT / "src"):
        if p.exists() and str(p) not in sys.path:
            sys.path.insert(0, str(p))
    _labbench_wired = True
