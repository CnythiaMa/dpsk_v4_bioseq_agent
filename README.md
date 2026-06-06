# dpsk_v4_bioseq_agent

A minimal **code-execution agent** that lets a tool-less LLM (here: **DeepSeek-V4-flash / -pro**
via Volcengine Ark) solve **LabBench2** sequence/cloning tasks by *writing and running its own
Python* in a sandbox, instead of doing error-prone nucleotide bookkeeping in its head.

The whole "tool environment" is **one Python sandbox + one in-silico assembly self-check**. There is
**no routing layer and no output-formatting layer** — every question goes straight into the agent loop.

> 完整的研究思路与方法学(中文)见 [`docs/methodology.md`](docs/methodology.md)。

## Why

DeepSeek-V4 is strong in general, but on long-sequence tasks (complementary pairing, base counting,
feature location) it gets stuck in long, error-prone chain-of-thought "counting". Those are
deterministic, numerically-exact tasks — exactly what code solves cleanly. So we give the model a
sandbox and let it offload the mechanical work, keeping the *design/decision* in the model.

## Results (official LabBench2 validators)

**CloningQA** (14 tasks, design-heavy) — full table in [`docs/cloning_comparison.md`](docs/cloning_comparison.md):

| config | score |
|---|---:|
| v4-flash · no tools | 3/14 (21%) |
| v4-flash · code-agent | 4/14 (29%) |
| v4-pro · no tools | 3/14 (21%) |
| **v4-pro · code-agent** | **5/14 (36%)** |
| GPT-5.5 codex (full tools) | 8/14 (57%) |
| Opus 4.8 (full tools) | 10/14 (71%) |

**SeqQA2** (400 tasks, compute-heavy) — full table in [`docs/seqqa_comparison.md`](docs/seqqa_comparison.md):

| config | raw | **answered-only** |
|---|---:|---:|
| flash · no tools (sequence injected) | 42.8% | 44.8% |
| flash · code-agent | 38.8% | **66.8%** |
| **pro · code-agent** | **50.7%** | **79.9%** |

The tool nearly doubles *compute* accuracy (answered-only ≈45% → 67–80%, near-perfect on long-sequence
types like `gc_content`/`restriction_counts` 4→20), but the raw score is dragged down by questions where
the model computed correctly yet didn't emit `<answer>` (no format layer — an engineering gap, not a
model-capability one).

## Install

```bash
pip install -e .            # or: pip install -e ".[test]"
cp .env.example .env        # fill in ARK_API_KEY, LABBENCH_ROOT, LABBENCH_DATA_ROOT
```

Requires a local checkout of the **external** [LabBench2 eval repo](https://github.com/EdisonScientific/labbench2)
(official scorers / in-silico assembly engine / question-file downloader); point `LABBENCH_ROOT` and
`LABBENCH_DATA_ROOT` at it.

## Run

```bash
dpsk-bioseq-cloning --model pro                 # 14 CloningQA tasks
dpsk-bioseq-seqqa   --model flash --type gc_content
# or as modules:
python -m dpsk_v4_bioseq_agent.run_cloning --model flash
# optional live dashboard (separate terminal):
dpsk-bioseq-dashboard --progress runs/cloning_pro/progress.json --port 8765 --title CloningQA
```
Each run writes `runs/<task>_<model>/`: `results.json` (per-question score/reason) and
`transcripts/*.json` (the **complete raw model I/O**: system+user prompt, every assistant turn with
tool_calls/reasoning, every tool result, final answer).

## Repository layout

```
src/dpsk_v4_bioseq_agent/
├── sandbox.py            # the tool substrate: run_python + dry_run_protocol (NO biology logic)
├── agent.py             # the code-agent loop: design_cloning() / solve_seqqa()
├── scoring.py           # official cloning_reward + seqqa-validator scoring
├── llm.py               # Ark client + 429/5xx retry-backoff + thinking toggle
├── adaptive.py          # AIMD adaptive concurrency limiter
├── config.py            # env-driven settings + external LabBench2 wiring
├── run_cloning.py / run_seqqa.py   # CLI drivers (also console entry points)
├── monitor/             # optional: progress tracker + zero-dep web dashboard
└── prompt_injection/    # a recorded dead end: inject structured summaries into the prompt
                         #   (dnacode.py for SeqQA, restructure_prompt.py for CloningQA)
docs/      # methodology (中文) + result comparisons + baseline
results/   # per-question result JSONs
tests/     # unit tests for the no-API modules (sandbox, adaptive, dnacode)
```

## How one round works

The model emits a `run_python` tool call whose argument is Python *it wrote*:
```python
from Bio import SeqIO
rec = SeqIO.read("plvx-egfp-ires-puro.gb", "genbank")
egfp = next(f for f in rec.features if "EGFP" in (f.qualifiers.get("label") or [""])[0])
print(int(egfp.location.start), int(egfp.location.end))
```
`sandbox.run_python` just executes it in a subprocess and returns stdout — it never knows what "EGFP"
is. All domain logic lives in the model-written code.

## License

MIT — see [LICENSE](LICENSE).
