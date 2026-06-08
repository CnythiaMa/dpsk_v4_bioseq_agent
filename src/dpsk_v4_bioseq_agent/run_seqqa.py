"""SeqQA2 (LabBench2, 400 tasks) via the SAME code-agent — but tools = run_python only
(no assembly self-check). Straight to the agent; no routing, no compose. Scored by the
official SeqQA2 validators. Saves the FULL model transcript per question.

  python -m dpsk_v4_bioseq_agent.run_seqqa --model flash --type gc_content
  python -m dpsk_v4_bioseq_agent.run_seqqa --model pro                       # all 400
  (or the console entry point:  dpsk-bioseq-seqqa --model pro)

NOTE: there is NO output-format (compose) step, so questions where the model doesn't emit
<answer> score ``no_answer_extracted`` — the honest behavior of this minimal setup.
"""
import argparse
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

from . import agent, config
from .adaptive import AdaptiveLimiter
from .monitor.progress import Progress, heartbeat_loop
from .scoring import score_seqqa

PARQUET = config.LABBENCH_DATA_ROOT / "labbench2/seqqa2/train-00000-of-00001.parquet"
_print_lock = threading.Lock()


def _has_files(q):
    return str(q.get("files")) not in ("", "None", "nan")


def main():
    ap = argparse.ArgumentParser(description="Run SeqQA2 through the code-agent.")
    ap.add_argument("--model", default=config.MODEL, help="flash | pro | full Ark model id")
    ap.add_argument("--type", default=None, help="comma-separated SeqQA types")
    ap.add_argument("--limit", type=int, default=None, help="only the first N tasks")
    ap.add_argument("--conc", type=int, default=12, help="max concurrency")
    ap.add_argument("--outdir", default="runs", help="output root")
    args = ap.parse_args()
    config.ensure_labbench_on_path()
    from evals.utils import GCS_BUCKET, download_question_files
    config.MODEL = config.MODEL_ALIASES.get(args.model, args.model)
    tag = config.MODEL.replace("deepseek-v4-", "")

    rows = pd.read_parquet(config.require_data_file(PARQUET)).to_dict("records")
    if args.type:
        keep = {x.strip() for x in args.type.split(",")}
        rows = [q for q in rows if q["type"] in keep]
    if args.limit:
        rows = rows[: args.limit]
    outdir = Path(args.outdir) / f"seqqa_{tag}"
    (outdir / "transcripts").mkdir(parents=True, exist_ok=True)
    limiter = AdaptiveLimiter(init=8, lo=3, hi=args.conc)

    t0 = time.time()
    prog = Progress(str(outdir / "progress.json"), f"SeqQA2 · {config.MODEL}", t0, total=len(rows))
    stop = threading.Event()
    threading.Thread(target=heartbeat_loop, args=(prog, limiter, stop), daemon=True).start()
    print(f"SeqQA2 · {config.MODEL} · n={len(rows)} conc={args.conc} -> {outdir}", flush=True)

    def work(i, q):
        t = time.time()
        try:
            bd = Path(download_question_files(GCS_BUCKET, q["files"])) if _has_files(q) else None
            res = agent.solve_seqqa(str(q["question"]), bd, str(q.get("prompt_suffix") or ""), limiter=limiter)
            sc, reason = score_seqqa(q, res["output"], bd)
            (outdir / "transcripts" / f"{i + 1:03d}_{q['type']}_{q['id']}.json").write_text(json.dumps(
                {"id": q["id"], "type": q["type"], "model": config.MODEL, "score": sc, "reason": reason,
                 "question": str(q["question"]), "final_answer": res["output"],
                 "transcript": res["transcript"]}, ensure_ascii=False, indent=2))
            item = {"idx": i + 1, "id": q["id"], "type": q["type"], "score": sc, "reason": reason,
                    "n_tool_calls": res["n_tool_calls"], "latency_s": round(time.time() - t, 1)}
        except Exception as e:  # noqa: BLE001 — isolate per-task failure into a 0-score result
            item = {"idx": i + 1, "id": q["id"], "type": q["type"], "score": 0.0,
                    "reason": f"run_error:{type(e).__name__}:{e}", "latency_s": round(time.time() - t, 1)}
        prog.add_item(item, time.time(), limiter.snapshot())
        with _print_lock:
            if prog.state["done"] % 10 == 0:
                print(f"  [{prog.state['done']}/{len(rows)}] passed={prog.state['passed']} "
                      f"lim={limiter.limit} thr={limiter.stats['throttles']}", flush=True)
        return item

    results = []
    with ThreadPoolExecutor(max_workers=args.conc) as ex:
        for fut in as_completed([ex.submit(work, i, q) for i, q in enumerate(rows)]):
            results.append(fut.result())
    stop.set()
    results.sort(key=lambda r: r["idx"])
    (outdir / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2))
    prog.set_status("done", time.time())
    passed = sum(1 for r in results if r["score"] == 1.0)
    print(f"\nDONE {config.MODEL}: {passed}/{len(results)} = {passed / len(results) * 100:.1f}% | "
          f"wall={round(time.time() - t0, 1)}s", flush=True)


if __name__ == "__main__":
    main()
