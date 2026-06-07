# Web reports (static, self-contained)

Self-contained HTML pages (all CSS/JS/data inlined — no external assets). Served via
GitHub Pages from `/docs` once Pages is enabled (Settings → Pages → Branch: `main`, Folder: `/docs`).

| File | What it is |
|------|------------|
| `index.html` | Benchmark introduction page (LAB-Bench2 SeqQA2 / CloningQA overview). |
| `flash-tool-vs-notool.html` | v4-flash 有工具 vs 无工具 的逐题完整 API 交互留痕(prompt / reasoning + finish_reason / 每轮 run_python 代码+输出 / dry_run 装配 / 官方验证器判定),含 3 对「无工具❌ → 有工具✅」对照(gc_content / primer_design / restriction-ligation,后者对齐原始 14 轮设定)。 |

After Pages is enabled, the public URLs are:
- `https://cnythiama.github.io/dpsk_v4_bioseq_agent/web/index.html`
- `https://cnythiama.github.io/dpsk_v4_bioseq_agent/web/flash-tool-vs-notool.html`

`docs/.nojekyll` is present so files are served verbatim (no Jekyll processing of the `.md` reports).
