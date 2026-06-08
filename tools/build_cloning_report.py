#!/usr/bin/env python3
"""Build a static, self-contained HTML report for ONE CloningQA code-agent run.

Renders, per question, the COMPLETE API interaction reconstructed from the run's raw
request/response log (``raw/NN_<id>.jsonl`` — one HTTP call per line, with usage and
finish_reason) plus the official validator verdict from ``transcripts/NN_<id>.json``.
Style matches docs/web/flash-tool-vs-notool.html.

  python tools/build_cloning_report.py \
      --run runs/flash_maxr20/cloning_flash \
      --out docs/web/cloning-flash-maxr20.html \
      --title "v4-flash · CloningQA · 代码 Agent (max_rounds=20)"
"""
import argparse
import html
import json
from pathlib import Path

CSS = """
 body{font:14px/1.55 -apple-system,Segoe UI,Roboto,sans-serif;margin:0;background:#0f1117;color:#e6e6e6}
 .wrap{max-width:1100px;margin:0 auto;padding:24px}
 h1{font-size:21px} h2{font-size:18px;margin:26px 0 10px;border-bottom:1px solid #2c3550;padding-bottom:6px}
 h3{font-size:15px;margin:0 0 8px}
 .note{color:#8b93a7;font-size:13px;margin-bottom:8px}
 table{border-collapse:collapse;width:100%;font-size:13px;margin-bottom:16px}
 th,td{border:1px solid #232838;padding:6px 9px;text-align:left;vertical-align:top}
 th{color:#8b93a7}
 .rrow{cursor:pointer} .rrow:hover{background:#1b2233}
 details.qcard{background:#171a23;border:1px solid #232838;border-radius:12px;margin-bottom:12px}
 details.qcard>summary.qsum{font-size:15px;font-weight:600;padding:13px 18px;color:#e6e6e6}
 details.qcard[open]>summary.qsum{border-bottom:1px solid #232838}
 details.qcard>*:not(summary){margin-left:18px;margin-right:18px}
 details.qcard>.q{margin-top:10px}
 details.qcard:target{outline:2px solid #3b82f6}
 .q{color:#9fb0c8;font-size:12.5px;margin-bottom:10px}
 .meta{color:#8b93a7;font-size:12px}
 .badge{padding:1px 9px;border-radius:20px;font-size:12px;margin-left:6px}
 .ok{color:#6ee7a8} .bad{color:#f3a3a3}
 .badge.ok{background:#16351f;color:#6ee7a8} .badge.bad{background:#3a1d1d;color:#f3a3a3}
 details{border:1px solid #232838;border-radius:8px;margin:6px 0;background:#10131b}
 summary{cursor:pointer;padding:7px 10px;color:#9fb0c8;font-size:12.5px;user-select:none}
 details[open]>summary{border-bottom:1px solid #232838;color:#cfe}
 pre{margin:0;padding:10px 12px;white-space:pre-wrap;word-break:break-word;font:12px/1.5 ui-monospace,Menlo,monospace;max-height:460px;overflow:auto}
 details.round{background:#141824} details.round>summary{color:#c4a3ff}
 .official{border:1px solid #2c3550;border-radius:8px;margin:8px 0;background:#101626}
 .official .oh{padding:6px 10px;color:#7cc4ff;font-weight:600;border-bottom:1px solid #2c3550}
 .official table{margin:0} .official td:first-child{color:#8b93a7;width:170px;white-space:nowrap}
 .finalout{margin:8px 0;font-size:12.5px} code{background:#0c0f16;padding:1px 5px;border-radius:4px}
 .vtag{font-size:11px;color:#f5b971;background:#3a2e1a;padding:1px 7px;border-radius:20px}
 .statrow{display:flex;gap:10px;flex-wrap:wrap;margin:10px 0}
 .stat{background:#10131b;border:1px solid #232838;border-radius:10px;padding:8px 13px;min-width:90px}
 .stat .v{font-size:19px;font-weight:600}.stat .k{color:#8b93a7;font-size:10.5px;text-transform:uppercase;letter-spacing:.04em}
"""

E = lambda s: html.escape(str(s if s is not None else ""))


def usage_bits(usage):
    u = usage or {}
    ctd = u.get("completion_tokens_details") or {}
    return (u.get("prompt_tokens", "?"), u.get("completion_tokens", "?"),
            ctd.get("reasoning_tokens", "?"))


def load_rounds(raw_path):
    """Successful API calls only (each = one round), in order, from the raw JSONL."""
    rounds = []
    if not raw_path.exists():
        return rounds
    for line in raw_path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        if "response" in e:
            rounds.append(e)
    return rounds


def tool_results_after(rounds, k):
    """The tool-role messages appended to the conversation between round k and k+1
    (i.e. exactly what the sandbox returned for round k's tool calls)."""
    if k + 1 >= len(rounds):
        return []
    prev = rounds[k]["request"]["messages"]
    nxt = rounds[k + 1]["request"]["messages"]
    tail = nxt[len(prev):]
    return [m for m in tail if isinstance(m, dict) and m.get("role") == "tool"]


def render_round(idx, rnd, tool_outs):
    msg = rnd["response"]["choices"][0]["message"]
    fr = rnd["response"]["choices"][0].get("finish_reason", "?")
    pt, ct, rt = usage_bits(rnd["response"].get("usage"))
    reasoning = msg.get("reasoning_content") or ""
    content = msg.get("content") or ""
    tcs = msg.get("tool_calls") or []
    head = (f"轮 {idx} · finish_reason=<b>{E(fr)}</b> · prompt_tok={pt} · completion_tok={ct} · "
            f"reasoning_tok={rt} · reasoning_chars={len(reasoning)} · tool_calls={len(tcs)}")
    parts = [f'<details class="round"><summary>{head}</summary>']
    if reasoning:
        parts.append(f'<details><summary>  └ assistant reasoning ({len(reasoning)} chars)</summary>'
                     f'<pre>{E(reasoning)}</pre></details>')
    for j, tc in enumerate(tcs, 1):
        fn = tc.get("function", {}).get("name", "?")
        try:
            args = json.loads(tc.get("function", {}).get("arguments") or "{}")
        except json.JSONDecodeError:
            args = {}
        if fn == "run_python":
            body = args.get("code", "")
            label = f"  └ run_python #{j} — 代码 ({len(body)} chars)"
        elif fn == "dry_run_protocol":
            body = args.get("protocol", "")
            label = f"  └ dry_run_protocol #{j} — 提交协议自检"
        else:
            body = json.dumps(args, ensure_ascii=False, indent=2)
            label = f"  └ {fn} #{j}"
        parts.append(f'<details><summary>{E(label)}</summary><pre>{E(body)}</pre></details>')
    # tool outputs (what the sandbox returned, exactly as fed back to the model)
    for to in tool_outs:
        out = to.get("content", "")
        parts.append(f'<details><summary>     └ 工具返回 stdout/result</summary><pre>{E(out)}</pre></details>')
    if content.strip():
        parts.append(f'<details><summary>  └ assistant content ({len(content)} chars)</summary>'
                     f'<pre>{E(content)}</pre></details>')
    parts.append("</details>")
    return "".join(parts)


def render_card(card_id, idx, rec, rounds):
    typ = rec.get("type", "?")
    score = rec.get("score", 0.0)
    ok = score == 1.0
    reason = rec.get("reason", "")
    question = rec.get("question", "")
    final = rec.get("final_answer", "") or ""
    badge = '<span class="badge ok">PASS</span>' if ok else '<span class="badge bad">FAIL</span>'
    n_tool = sum(len(r["response"]["choices"][0]["message"].get("tool_calls") or []) for r in rounds)
    tot_pt = sum((r["response"].get("usage") or {}).get("prompt_tokens", 0) for r in rounds)
    tot_ct = sum((r["response"].get("usage") or {}).get("completion_tokens", 0) for r in rounds)
    tot_rt = sum(((r["response"].get("usage") or {}).get("completion_tokens_details") or {})
                 .get("reasoning_tokens", 0) for r in rounds)
    last_fr = rounds[-1]["response"]["choices"][0].get("finish_reason", "?") if rounds else "—"

    h = [f'<details class="qcard" id="{card_id}"><summary class="qsum">Q{idx} · {E(typ)} {badge} '
         f'<span class="meta">{rec.get("latency_s","?")}s · {n_tool} tool calls · {E(reason)[:60]}</span></summary>']
    h.append(f'<div class="q">{E(question)}</div>')
    # official validator box
    h.append('<div class="official"><div class="oh">官方验证器 · CloningQA (in-silico 装配)</div><table>'
             f'<tr><td>提交 &lt;protocol&gt;</td><td><pre style="max-height:240px">{E(final)}</pre></td></tr>'
             f'<tr><td>官方 cloning_reward</td><td><b class="{ "ok" if ok else "bad" }">'
             f'{"PASS (1.0)" if ok else "FAIL (0.0)"}</b> &nbsp; {E(reason)}</td></tr></table></div>')
    # aggregate stats
    h.append('<div class="statrow">'
             f'<div class="stat"><div class="k">rounds</div><div class="v">{len(rounds)}</div></div>'
             f'<div class="stat"><div class="k">tool calls</div><div class="v">{n_tool}</div></div>'
             f'<div class="stat"><div class="k">last finish</div><div class="v">{E(last_fr)}</div></div>'
             f'<div class="stat"><div class="k">prompt tok Σ</div><div class="v">{tot_pt}</div></div>'
             f'<div class="stat"><div class="k">completion tok Σ</div><div class="v">{tot_ct}</div></div>'
             f'<div class="stat"><div class="k">reasoning tok Σ</div><div class="v">{tot_rt}</div></div>'
             '</div>')
    # input prompt (system+user from the first request)
    if rounds:
        msgs0 = rounds[0]["request"]["messages"]
        sysu = "\n\n".join(f"[{m.get('role')}]\n{m.get('content','')}" for m in msgs0
                           if m.get("role") in ("system", "user"))
        h.append(f'<details><summary>输入 prompt (system + user · {len(sysu)} chars)</summary>'
                 f'<pre>{E(sysu)}</pre></details>')
    # rounds
    for k, rnd in enumerate(rounds):
        h.append(render_round(k, rnd, tool_results_after(rounds, k)))
    # final output
    h.append(f'<details open><summary>最终输出 final_answer ({len(final)} chars)</summary>'
             f'<pre>{E(final)}</pre></details>')
    h.append('</details>')
    return "".join(h)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True, help="run dir, e.g. runs/flash_maxr20/cloning_flash")
    ap.add_argument("--out", required=True)
    ap.add_argument("--title", default="CloningQA · 代码 Agent")
    args = ap.parse_args()
    run = Path(args.run)
    tdir, rdir = run / "transcripts", run / "raw"

    # order by the NN prefix on the transcript filenames
    tfiles = sorted(tdir.glob("*.json"), key=lambda p: p.name)
    cards, table_rows = [], []
    n_pass = 0
    for ci, tf in enumerate(tfiles):
        rec = json.loads(tf.read_text())
        idx = int(tf.name.split("_", 1)[0])
        raw_path = rdir / (tf.stem + ".jsonl")
        rounds = load_rounds(raw_path)
        ok = rec.get("score") == 1.0
        n_pass += ok
        card_id = f"card-{ci}"
        cls = "ok" if ok else "bad"
        table_rows.append(
            f'<tr class="rrow" onclick="jump(\'{card_id}\')"><td>Q{idx}</td><td>{E(rec.get("type"))}</td>'
            f'<td class="{cls}">{"PASS" if ok else "FAIL"}</td><td>{len(rounds)}</td>'
            f'<td>{rec.get("latency_s","?")}s</td><td>{E(rec.get("reason",""))[:64]}</td></tr>')
        cards.append(render_card(card_id, idx, rec, rounds))

    note = (f"模型: deepseek-v4-flash · 代码 Agent (run_python + dry_run_protocol) · "
            f"<b>AGENT_MAX_ROUNDS=20</b> · 每题只跑一次。"
            f"每个轮次 = 一次真实 API 调用,数据直接来自 <code>raw/NN_id.jsonl</code>"
            f"(完整 request/response · usage · finish_reason)。官方 cloning_reward 做 in-silico 装配判分。<br>"
            f"<b>点击汇总表任意一行可跳转并展开对应题目;每个题目卡片、每个轮次均可折叠。</b>")
    summary = (f"<b>{n_pass}/{len(tfiles)}</b> 通过官方验证器")
    page = (f'<!doctype html><html><head><meta charset="utf-8"><title>{E(args.title)}</title>'
            f'<style>{CSS}</style></head><body><div class="wrap">'
            f'<h1>{E(args.title)}</h1><div class="note">{note}</div>'
            f'<h2>CloningQA · {summary}</h2>'
            f'<table><thead><tr><th>#</th><th>题型</th><th>结果</th><th>轮数</th><th>耗时</th><th>reason</th></tr></thead>'
            f'<tbody>{"".join(table_rows)}</tbody></table>'
            f'<div class="cards">{"".join(cards)}</div>'
            f'</div><script>function jump(id){{var el=document.getElementById(id);el.open=true;'
            f'el.scrollIntoView({{behavior:"smooth",block:"start"}});}}</script></body></html>')
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    print(f"wrote {out}  ({len(tfiles)} questions, {n_pass} pass, {out.stat().st_size//1024} KB)")


if __name__ == "__main__":
    main()
