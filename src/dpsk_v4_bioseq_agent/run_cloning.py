"""CloningQA (LabBench2, 14 tasks) via the code-agent. Straight to the agent — no routing,
no compose. Scored by the official ``cloning_reward`` (in-silico assembly vs reference).
Saves the FULL model transcript per question.

  python -m dpsk_v4_bioseq_agent.run_cloning --model flash          # deepseek-v4-flash
  python -m dpsk_v4_bioseq_agent.run_cloning --model pro --conc 8    # deepseek-v4-pro
  (or the console entry point:  dpsk-bioseq-cloning --model pro)
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
from .scoring import score_cloning

config.ensure_labbench_on_path()
from evals.utils import GCS_BUCKET, download_question_files  # noqa: E402

PARQUET = config.LABBENCH_DATA_ROOT / "labbench2/cloning/train-00000-of-00001.parquet"
_print_lock = threading.Lock()


def main():
    ap = argparse.ArgumentParser(description="Run CloningQA through the code-agent.")
    ap.add_argument("--model", default=config.MODEL, help="flash | pro | full Ark model id")
    ap.add_argument("--conc", type=int, default=8, help="max concurrency")
    ap.add_argument("--limit", type=int, default=None, help="only the first N tasks")
    ap.add_argument("--outdir", default="runs", help="output root")
    args = ap.parse_args()
    config.MODEL = config.MODEL_ALIASES.get(args.model, args.model)
    tag = config.MODEL.replace("deepseek-v4-", "")

    outdir = Path(args.outdir) / f"cloning_{tag}"
    (outdir / "transcripts").mkdir(parents=True, exist_ok=True)
    limiter = AdaptiveLimiter(init=min(args.conc, 8), lo=3, hi=args.conc)
    rows = pd.read_parquet(PARQUET).to_dict("records")
    if args.limit:
        rows = rows[: args.limit]

    t0 = time.time()
    prog = Progress(str(outdir / "progress.json"), f"CloningQA · {config.MODEL}", t0, total=len(rows))
    stop = threading.Event()
    threading.Thread(target=heartbeat_loop, args=(prog, limiter, stop), daemon=True).start()
    print(f"CloningQA · {config.MODEL} · n={len(rows)} conc={args.conc} -> {outdir}", flush=True)

    def work(i, q):
        t = time.time()
        try:
            bd = Path(download_question_files(GCS_BUCKET, q["files"]))
            res = agent.design_cloning(str(q["question"]), bd,
                                       str(q.get("prompt_suffix") or ""), limiter=limiter)
            sc, reason = score_cloning(q, res["output"], bd)
            (outdir / "transcripts" / f"{i + 1:02d}_{q['id']}.json").write_text(json.dumps(
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
            print(f"  [{prog.state['done']}/{len(rows)}] {'PASS' if item['score'] == 1.0 else 'fail'} "
                  f"{item['type']:<11} lim={limiter.limit} {item['reason'][:48]}", flush=True)
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
          f"wall={round(time.time() - t0, 1)}s -> {outdir}/results.json", flush=True)


if __name__ == "__main__":
    main()
