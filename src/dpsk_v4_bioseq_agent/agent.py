"""The code-agent loop. The DESIGN/REASONING lives in the LLM; the sandbox is the
substrate it uses to do mechanical sequence work and to verify.

There is NO routing classifier and NO output-formatting/compose step — every question
goes straight into this loop.

Two entry points share one loop:
  design_cloning(...)  -> CloningQA: tools = run_python + dry_run_protocol; emits a <protocol>
  solve_seqqa(...)     -> SeqQA2:    tools = run_python only;               emits an <answer>

Both return ``{output, transcript, n_tool_calls}``. ``transcript`` is the COMPLETE list of
messages exchanged with the model (system, user, every assistant turn incl. tool_calls and
reasoning_content, every tool result) — i.e. the raw model I/O for that question.
"""
import json
import re
from pathlib import Path

import httpx

from . import config, llm, sandbox

_PROTO_RE = re.compile(r"<protocol>(.*?)</protocol>", re.S | re.I)
_ANS_RE = re.compile(r"<answer>.*?</answer>", re.S | re.I)

CLONING_SYSTEM = """You are an expert molecular-cloning designer with a PYTHON SANDBOX. THE DESIGN IS YOUR JOB —
reason it out yourself. Use the sandbox only to do the mechanical sequence work and to VERIFY. Never
count bases, reverse-complement, or build sequences by hand — write Python.

TOOLS:
- run_python(code): runs Python in the question's directory (cwd holds the input files; BASE_DIR points
  to it). `from Bio import SeqIO` and `from Bio.Seq import Seq` are available. STATE PERSISTS across calls
  (like a notebook). PRINT what you need to inspect.
- dry_run_protocol(protocol): execute a <protocol> and report whether it parses, the primers anneal, and
  it assembles into one (ideally circular) product. Verify before you finalize.

HOW TO WORK:
1. Explore: parse the files (SeqIO), see what features/sequences exist and their coordinates.
2. Design the construct YOURSELF — choose junctions; preserve reading frame / Kozak / a single stop where
   relevant; for Golden Gate pick the Type-IIS enzyme (BsaI/Esp3I) and design the 4-nt overhangs and any
   fusion linkers; for a point mutant, edit the residue; for multi-fragment assembly, order the overlaps.
3. Build primers/fragments IN PYTHON. If an insert is NOT a plain file region — a point mutant, a
   UTR-included transcript, a codon-optimized ORF, tandem repeats — COMPUTE the exact sequence in Python
   and use it as a quoted literal DNA string inside pcr(...).
4. dry_run_protocol your draft; iterate until ok:true and a single (circular) product.

PROTOCOL DSL (what you output): pcr(seq, "FWD", "REV"), gibson(s1, s2, ...),
goldengate(s1, s2, ..., enzymes="Esp3I"), restriction_assemble(a, b), enzyme_cut(seq, "EnzymeName").
Operations may nest. `seq` is a BARE filename (no quotes) OR a quoted literal DNA string OR a nested op.
Primers and computed inserts are quoted literal strings.

OUTPUT: end with exactly ONE <protocol> </protocol> expression."""

SEQQA_SYSTEM = """You are a sequence-analysis assistant with a PYTHON SANDBOX. Your working directory contains
the input file(s). In run_python, `from Bio import SeqIO` and `from Bio.Seq import Seq` are available and
state persists across calls.

RULES:
- NEVER guess or hand-compute. Use run_python to READ the file(s) and COMPUTE the exact answer (GC%, Tm,
  molecular weight, counts, ORF translation, Hamming/edit distance, Shannon entropy, restriction digests).
  PRINT the computed value.
- If the question is about a NAMED gene inside a genome file, locate that gene by its feature label, extract
  its sequence, then compute on that. (Do NOT ingest a whole 1.5MB genome into your reasoning — read it in Python.)
- Once you have the value, STOP calling tools and reply with ONLY the final answer, EXACTLY in the format the
  task specifies (e.g. a single value inside <answer>...</answer>). No explanation, no extra text."""


def _loop(messages, tools_spec, base_dir, limiter, max_rounds, want_protocol, verbose=False):
    base_dir = Path(base_dir)
    transcript = [dict(m) for m in messages]          # full raw model I/O for this question
    py_history: list[str] = []
    content, last_protocol, last_answer, nudged = "", None, None, False

    with httpx.Client(timeout=config.HTTP_TIMEOUT) as client:
        for rnd in range(max_rounds + 1):
            force_final = rnd == max_rounds
            if force_final:
                fm = {"role": "user", "content":
                      ("Output your final answer now — ONLY the value in the required format "
                       "(e.g. <answer>...</answer>). No more tool calls." if not want_protocol else
                       "Round limit reached. Output your final answer now: exactly one "
                       "<protocol>...</protocol>. No more tool calls.")}
                messages.append(fm)
                transcript.append(fm)
            elif want_protocol and rnd >= max_rounds - 3 and not nudged:
                nudged = True
                nm = {"role": "user", "content":
                      f"You are at round {rnd} of {max_rounds}. Stop exploring — commit to your design: "
                      "call dry_run_protocol once to verify, then output one <protocol>...</protocol>."}
                messages.append(nm)
                transcript.append(nm)
            elif not want_protocol and rnd >= max_rounds - 3 and not nudged:   # near-limit: wrap up
                nudged = True
                nm = {"role": "user", "content":
                      f"You are at round {rnd}/{max_rounds}. Stop exploring — you should already have what "
                      "you need. In your NEXT message output ONLY the final <answer>...</answer>, no more "
                      "tool calls."}
                messages.append(nm)
                transcript.append(nm)

            payload = {"model": config.MODEL, "messages": messages, "stream": False}
            if not force_final:
                payload["tools"] = tools_spec
                payload["tool_choice"] = "auto"
            msg = llm._request(client, payload, limiter=limiter)
            tool_calls = msg.get("tool_calls") or []
            content = msg.get("content") or ""

            arec = {"role": "assistant", "content": content}
            if msg.get("reasoning_content"):
                arec["reasoning_content"] = msg["reasoning_content"]
            if tool_calls:
                arec["tool_calls"] = tool_calls
            transcript.append(arec)
            # fallback 1 (seqqa): if the model returned no content, the answer may sit in the CoT
            if not want_protocol and not content.strip() and msg.get("reasoning_content"):
                content = msg["reasoning_content"].strip()
            if verbose:
                print(f"    [r{rnd}] " + (", ".join(tc["function"]["name"] for tc in tool_calls)
                                          if tool_calls else f"final ({len(content)} chars)"))
            if not tool_calls:
                break
            messages.append({"role": "assistant", "content": content, "tool_calls": tool_calls})

            for tc in tool_calls:
                fn = tc["function"]["name"]
                try:
                    args = json.loads(tc["function"].get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                try:
                    if fn == "run_python":
                        code = args.get("code", "")
                        result = sandbox.run_python(base_dir, code, py_history)
                        py_history.append(code)
                        stdout = result.get("stdout", "") if isinstance(result, dict) else ""
                        if want_protocol:
                            m = _PROTO_RE.search(stdout)
                            if m and not last_protocol:
                                last_protocol = m.group(1).strip()
                        else:
                            # fallback 2 (seqqa): capture an <answer> the model printed in the sandbox
                            m = _ANS_RE.search(stdout)
                            if m:
                                last_answer = m.group(0)
                    elif fn == "dry_run_protocol":
                        result = sandbox.dry_run_protocol(base_dir, args.get("protocol", ""))
                        if want_protocol and isinstance(result, dict) and result.get("ok") and args.get("protocol"):
                            last_protocol = args["protocol"]
                    else:
                        result = {"error": f"unknown tool {fn}"}
                except Exception as e:  # noqa: BLE001 — feed any tool error back to the model
                    result = {"error": f"{type(e).__name__}: {e}"}
                tmsg = {"role": "tool", "tool_call_id": tc["id"],
                        "content": json.dumps(result, ensure_ascii=False)[:6000]}
                messages.append(tmsg)
                transcript.append(tmsg)

    if want_protocol and "<protocol>" not in (content or "").lower() and last_protocol:
        content = (content or "") + f"\n\n<protocol>\n{last_protocol}\n</protocol>"
        transcript.append({"role": "harness_note",
                           "content": "appended last tool-verified <protocol> (model omitted the tags)"})
    # fallback 3 (seqqa): model never emitted <answer> but printed one in the sandbox -> use it
    elif not want_protocol and "<answer>" not in (content or "").lower() and last_answer:
        content = (content + "\n" + last_answer) if content else last_answer
        transcript.append({"role": "harness_note",
                           "content": "appended last <answer> printed in the sandbox (model omitted the tags)"})
    return {"output": content, "transcript": transcript,
            "n_tool_calls": sum(1 for m in transcript if m.get("role") == "tool")}


def design_cloning(question, base_dir, prompt_suffix="", limiter=None, verbose=False):
    files = sandbox.ensure_dsl_safe_files(base_dir)
    user = (str(question)
            + "\n\nInput files in the working directory (use the exact names below in your protocol):\n"
            + "\n".join(f"- {n}" for n in files))
    if prompt_suffix:
        user += "\n\n" + str(prompt_suffix)
    user += "\n\nStart by exploring the files with run_python, then design, then dry_run_protocol, then output."
    messages = [{"role": "system", "content": CLONING_SYSTEM}, {"role": "user", "content": user}]
    return _loop(messages, sandbox.CLONING_TOOLS, base_dir, limiter,
                 config.AGENT_MAX_ROUNDS, want_protocol=True, verbose=verbose)


def solve_seqqa(question, base_dir, prompt_suffix="", limiter=None, verbose=False):
    files = sorted(f.name for f in Path(base_dir).iterdir() if f.is_file()) if base_dir else []
    user = str(question) + (("\n\n" + str(prompt_suffix)) if prompt_suffix else "")
    if files:
        user += ("\n\nFiles in your working directory (read them with run_python — the sequence may be "
                 "large):\n" + "\n".join(f"- {n}" for n in files))
    messages = [{"role": "system", "content": SEQQA_SYSTEM}, {"role": "user", "content": user}]
    return _loop(messages, sandbox.SEQQA_TOOLS, base_dir, limiter,
                 config.SEQQA_MAX_ROUNDS, want_protocol=False, verbose=verbose)
