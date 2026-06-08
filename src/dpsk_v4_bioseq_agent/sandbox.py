"""The tool substrate — a general Python sandbox + an in-silico assembly self-check.

This module contains NO domain/biology logic: the actual sequence work is Python the
*model* writes at run time, which we simply execute. Two tools are exposed to the LLM:

  run_python(code)       — run model-written Python in the question's directory, with
                           Biopython available and STATE PERSISTING across calls.
  dry_run_protocol(...)  — execute a CloningQA <protocol> in silico and report whether
                           it parses / primers anneal / it assembles (no answer leak).

Plus one helper, :func:`ensure_dsl_safe_files`, because the cloning DSL uses BARE
filenames and Addgene downloads like ``x (1).gbk`` (spaces/parens) are unparseable.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from . import config

_DSL_UNSAFE = re.compile(r"[^A-Za-z0-9._-]")


def dsl_safe_name(name: str) -> str:
    return _DSL_UNSAFE.sub("_", name)


def ensure_dsl_safe_files(base_dir) -> list[str]:
    """Make a parser-safe copy of any file whose name has spaces/parens; return the
    list of safe names to show the model (so every generated <protocol> parses)."""
    base_dir = Path(base_dir)
    out: list[str] = []
    for f in [x for x in sorted(base_dir.iterdir()) if x.is_file()]:
        safe = dsl_safe_name(f.name)
        if safe != f.name:
            tgt = base_dir / safe
            if not tgt.exists():
                try:
                    shutil.copy2(f, tgt)
                except OSError:
                    pass
            out.append(safe)
        else:
            out.append(f.name)
    seen: set[str] = set()
    res: list[str] = []
    for n in out:
        if n not in seen:
            seen.add(n)
            res.append(n)
    return res


# ------------------------------------------------------------------ run_python
def run_python(base_dir, code, prior_cells, timeout=60):
    """Execute ``code`` in a fresh subprocess whose cwd is the question dir. Prior cells
    are re-run with their stdout suppressed (so state persists, like a notebook) and only
    the new cell's stdout is returned. Returns ``{ok, stdout[, stderr]}`` or a timeout dict.
    The harness is a dumb executor — all domain logic is in ``code``, written by the LLM."""
    base_dir = Path(base_dir)
    cells = list(prior_cells) + [str(code)]
    fd, cells_path = tempfile.mkstemp(suffix=".json")   # system tmp; keep the work dir clean
    with os.fdopen(fd, "w") as f:
        json.dump(cells, f)
    lab = config.LABBENCH_ROOT
    driver = (
        "import sys, os, io, json, re\n"
        "from pathlib import Path\n"
        f"sys.path.insert(0, {str(lab)!r}); sys.path.insert(0, {str(lab / 'src')!r})\n"
        "BASE_DIR = Path(os.environ['SANDBOX_BASE_DIR']); os.chdir(str(BASE_DIR))\n"
        "from Bio import SeqIO\n"
        "from Bio.Seq import Seq\n"
        "_CELLS = json.loads(open(os.environ['SANDBOX_CELLS_PATH']).read())\n"
        "_ns = dict(globals())\n"
        "for _i, _c in enumerate(_CELLS):\n"
        "    _last = _i == len(_CELLS) - 1\n"
        "    _buf = io.StringIO(); _o = sys.stdout; sys.stdout = _buf\n"
        "    try:\n"
        "        exec(compile(_c, '<cell%d>' % _i, 'exec'), _ns)\n"
        "    except SystemExit:\n"
        "        pass\n"
        "    except Exception:\n"
        "        if _last:\n"
        "            sys.stdout = _o; import traceback\n"
        "            sys.stdout.write(_buf.getvalue()); traceback.print_exc(); sys.exit(1)\n"
        "        # an earlier (replayed) cell raised — often it depends on state that has since\n"
        "        # changed. SKIP it and keep going; never abort the whole session for a prior cell.\n"
        "        continue\n"
        "    finally:\n"
        "        sys.stdout = _o\n"
        "    if _last:\n"
        "        sys.stdout.write(_buf.getvalue())\n"
    )
    env = dict(os.environ, SANDBOX_BASE_DIR=str(base_dir), SANDBOX_CELLS_PATH=cells_path)
    try:
        p = subprocess.run([sys.executable, "-c", driver], env=env,
                           capture_output=True, text=True, timeout=timeout)
        out = p.stdout or ""
        if len(out) > 6000:
            out = out[:3000] + "\n...[truncated]...\n" + out[-3000:]
        res = {"ok": p.returncode == 0, "stdout": out}
        if p.stderr and p.stderr.strip() and not res["ok"]:
            res["stderr"] = p.stderr[-1500:]
        return res
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"timeout after {timeout}s (infinite loop?)"}
    finally:
        try:
            os.unlink(cells_path)
        except OSError:
            pass


# ------------------------------------------------------ dry_run_protocol (self-check)
def dry_run_protocol(base_dir, protocol):
    """Execute a <protocol> against the question files; report assembly ONLY (never
    compared to the reference, so no answer leak). Catches parse errors, non-annealing
    primers, fragments that don't join. Does NOT prove biological correctness."""
    import asyncio

    config.ensure_labbench_on_path()
    from labbench2.cloning.cloning_protocol import CloningProtocol  # noqa: E402

    try:
        cp = CloningProtocol(str(protocol))
        seqs = asyncio.run(cp.run(base_dir))
        if not seqs:
            return {"ok": False, "error": "produced no sequence"}
        s = seqs[0]
        return {"ok": True, "n_products": len(seqs), "product_length": len(s.sequence),
                "is_circular": bool(s.is_circular),
                "note": "assembles; verify frame/Kozak/single-stop yourself"}
    except Exception as e:  # noqa: BLE001 — surface any assembly/parse failure to the model
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


# ---------------------------------------------------------- tool schemas (what the LLM sees)
_RUN_PYTHON = {"type": "function", "function": {
    "name": "run_python",
    "description": "Run Python in the question's directory (cwd holds the input files; BASE_DIR points to "
                   "it). Biopython is available (from Bio import SeqIO; from Bio.Seq import Seq). STATE "
                   "PERSISTS across calls like a notebook. Use this for ALL sequence work: parse files, "
                   "locate features by name, extract & reverse-complement subsequences, INTRODUCE "
                   "MUTATIONS, compute GC/Tm/MW/counts/entropy, design overlaps / Golden-Gate overhangs, "
                   "build primers, and assemble/simulate. PRINT what you need to see.",
    "parameters": {"type": "object", "properties": {
        "code": {"type": "string", "description": "Python source to execute"}}, "required": ["code"]}}}

_DRY_RUN = {"type": "function", "function": {
    "name": "dry_run_protocol",
    "description": "Execute a <protocol> expression against the input files and report whether it parses, "
                   "the primers anneal, and it assembles into one (circular) product. Use to verify before "
                   "you give the final answer. Returns ok / product_length / is_circular, or the error.",
    "parameters": {"type": "object", "properties": {
        "protocol": {"type": "string"}}, "required": ["protocol"]}}}

CLONING_TOOLS = [_RUN_PYTHON, _DRY_RUN]   # design + verify
SEQQA_TOOLS = [_RUN_PYTHON]               # pure compute, no assembly
