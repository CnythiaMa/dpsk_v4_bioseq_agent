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
SEQQA_MAX_ROUNDS: int = int(os.environ.get("SEQQA_MAX_ROUNDS", "14"))    # seqqa compute agent
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


def require_data_file(path: Path) -> Path:
    """Return ``path`` if it exists, else raise a clear, actionable error.

    Used by the runners to fail early (instead of a bare ``FileNotFoundError``) when the
    LabBench2 dataset has not been downloaded into ``LABBENCH_DATA_ROOT`` yet.
    """
    if path.exists():
        return path
    raise RuntimeError(
        f"Dataset file not found: {path}\n"
        f"LABBENCH_DATA_ROOT is currently: {LABBENCH_DATA_ROOT}\n"
        "Download the LabBench2 dataset (question manifests) from the HuggingFace dataset\n"
        "EdisonScientific/labbench2 so that these files exist:\n"
        f"  {LABBENCH_DATA_ROOT}/labbench2/seqqa2/train-00000-of-00001.parquet\n"
        f"  {LABBENCH_DATA_ROOT}/labbench2/cloning/train-00000-of-00001.parquet\n"
        "e.g.  huggingface-cli download EdisonScientific/labbench2 \\\n"
        f"        --repo-type dataset --local-dir {LABBENCH_DATA_ROOT}/labbench2\n"
        "See README.md (安装与准备, step 3) and .env.example."
    )
