"""Official-validator scoring, extracted out of the CLI runners.

  score_cloning  — in-silico assembly vs reference (labbench2.cloning.cloning_reward)
  score_seqqa    — extract <answer> per the question regex, feed to labbench2.seqqa2 validators

LabBench2 modules are imported lazily (after wiring its path) so this module stays importable
even without a LabBench2 checkout present.
"""
import ast
import asyncio
import json
import re

from . import config


def score_cloning(q, answer, base_dir):
    """Return ``(score, reason)`` for a CloningQA answer via the official cloning_reward."""
    config.ensure_labbench_on_path()
    from evals.utils import resolve_file_path
    from labbench2.cloning.rewards import cloning_reward

    gt = resolve_file_path(f"{q['id']}_assembled.fa", None)
    if gt is None:
        return 0.0, "no_ground_truth"
    vp = None
    if q.get("validator_params"):
        try:
            vp = ast.literal_eval(q["validator_params"])
        except (ValueError, SyntaxError):
            vp = None
    try:
        s, reason = asyncio.run(cloning_reward(answer=answer, base_dir=base_dir,
                                               reference_path=gt, validator_params=vp))
        return float(s), str(reason)[:160]
    except Exception as e:  # noqa: BLE001 — any reward failure scores 0 with a reason
        return 0.0, f"reward_error:{type(e).__name__}:{e}"


def score_seqqa(q, output, files_path):
    """Return ``(score, reason)`` for a SeqQA2 answer. Replicates the official scoring:
    extract ``<answer>`` per the question's regex, feed named groups + validator_params
    into ``VALIDATORS[type].func``."""
    config.ensure_labbench_on_path()
    from evals.utils import resolve_file_path
    from labbench2.seqqa2.registry import VALIDATORS

    val = VALIDATORS.get(q["type"])
    if val is None:
        return 0.0, "no_validator"
    m = re.search(f"<answer>{q['answer_regex']}</answer>", output or "", re.IGNORECASE)
    if not m:
        return 0.0, "no_answer_extracted"
    kwargs = {**(json.loads(q["validator_params"]) if q.get("validator_params") else {}), **m.groupdict()}
    # The question regex always names its capture group "answer", but some validators expect a
    # differently-named param (codon_optimization -> "optimized_dna", cds_oligo/oligo_design ->
    # "oligo"). The official registry encodes this as Validator.answer_param; replicate the rename.
    answer_param = getattr(val, "answer_param", "answer")
    if answer_param != "answer" and "answer" in kwargs:
        kwargs[answer_param] = kwargs.pop("answer")
    for k, v in list(kwargs.items()):
        if k.endswith("_path") and isinstance(v, str):
            r = resolve_file_path(v, files_path)
            if r is None:
                return 0.0, f"file_not_found:{v}"
            kwargs[k] = r
    try:
        return float(val.func(**kwargs)), "ok"
    except Exception as e:  # noqa: BLE001 — any validator failure scores 0 with a reason
        return 0.0, f"validator_error:{type(e).__name__}"
