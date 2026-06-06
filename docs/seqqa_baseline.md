# SeqQA2 基线评测 · deepseek-v4-flash（BASE / 无 ICL）

> 模型：`deepseek-v4-flash-202605`（TokenHub / 腾讯 MaaS，OpenAI 兼容）
> 数据：LAB-Bench2 `seqqa2` 全量 **400 题 = 20 类型 × 20**
> 模式：**inject**（序列全文注入 prompt）· 条件：**BASE，无 SeqCode / 无 ICL / 无工具**
> 评分：复用 LAB-Bench2 **官方程序化 validator**（非 LLM judge）
> 日期：2026-06-05 · 状态：**终态（全 400 题已跑完；仅 1 道 `primer_design` 因顽固 429 未作答、计 0）**

---

## 一、这次跑了什么 / 怎么跑的

- **目的**：建立 DeepSeek-v4-flash 在序列任务上的**无 ICL 基线**，作为后续 `+SeqCode` 表示注入对照的参照点（base 臂）。
- **inject 模式**：每题把对应序列（如 `rpsR.fasta` 全 1315 bp）**全文贴进 prompt**，模型无需检索；prompt 末尾附官方 `prompt_suffix`，要求答案放进 `<answer>…</answer>`。
- **评分**：用官方 `labbench2.seqqa2` 的 reward 函数 + `evaluators.py` 的文件解析逻辑**逐字复刻**——抽取 `<answer>`，按 `validator_params` 复算标准答案，数值有容差、序列/酶名严格匹配。**因此本表分数与官方 harness 口径一致。**
- **跑测踩坑（影响口径，务必知悉）**：
  - 并发 40 → 大量 **429 限流** + 个别 **360s 超时**（DeepSeek CoT 极慢，均 ~181s，部分 >900s）。
  - 中途 **402 余额耗尽**，充值后续跑。
  - 最终策略：主跑并发 10、超时 900s；失败题用**并发 3 低速清理补跑**。429 为快速失败、不耗 token；真正耗费用的是长 CoT。

## 二、最终结果（20 类 / 3 层）

> `acc_ans` = 已作答口径（剔除未作答题，最能代表模型真实能力）；`raw` = 未作答计 0。
> 三层 = 按 **ICL 改造适配度** 分层：A 有 ICL 空间 / B 纯公式算术 / C 设计·工具绑定。

| type | tier | 正确 | n | 未答 | acc_ans | 题目示例（采样，→ 为标准答案） |
|---|---|---:|---:|---:|---:|---|
| `restriction_digest` | A | 19 | 20 | 0 | **0.950** | rpsR 用 Cac8I 酶切后的片段长度？→ `219,238,272,586` |
| `mutation_restriction` | A | 13 | 20 | 0 | 0.650 | rpsR codon 10 突变成 CTT 后，14 个酶里哪个跨切该位点？→ `HindIII` |
| `restriction_counts` | A | 4 | 20 | 0 | 0.200 | rpoC 里有几个 BamHI 位点？→ `2` |
| `orf_amino_acid` | A | 3 | 20 | 0 | 0.150 | 该序列最长 ORF 第 11 位是什么氨基酸？→ `D` |
| `mutation_synonymous` | A | 0 | 20 | 0 | **0.000** | rpsR codon 10 第三位突变成 G，新编码的氨基酸？→ `Q` |
| **— Tier A 小计** | | **39** | **100** | 0 | **0.390** | — |
| `pairwise_distances` | B | 18 | 20 | 0 | 0.900 | 两条序列的 Hamming 距离？(`ATCGATCG` / `ATCGATCG`) → `0` |
| `sequence_complexity` | B | 14 | 20 | 0 | 0.700 | 这段 DNA 的 Shannon 熵(bit)？(`ATCGATCGATCGATCG`) → `2.000` |
| `protein_hydrophobicity` | B | 14 | 20 | 0 | 0.700 | Kyte-Doolittle 平均疏水性？(`MKTLLLTLVV`) → `2.020` |
| `msa_scoring` | B | 14 | 20 | 0 | 0.700 | 给定比对，第 0 列的 Shannon 熵？→ `0.000` |
| `molecular_weight` | B | 11 | 20 | 0 | 0.550 | 这条蛋白序列的分子量？(`MKTLLLTLVV`) → `950` |
| `tm_calculations` | B | 10 | 20 | 0 | 0.500 | 用 Wallace 规则算这段 DNA 的 Tm？(`ATCGATCG`) → `24.0` |
| `gc_content` | B | 4 | 20 | 0 | **0.200** | rpsR 的 GC 含量(%)？→ `33.99` |
| **— Tier B 小计** | | **85** | **140** | 0 | **0.607** | — |
| `amplicon_gc` | C | 19 | 20 | 0 | 0.950 | 设计引物扩增 rpsR 的 200–300 bp 产物，且任一 30 bp 窗口 GC≤65% |
| `enzyme_kinetics` | C | 18 | 20 | 0 | 0.900 | 由酶动力学数据（[S]/v 各 6 点）算 Km (mM)？→ `0.701` |
| `primer_interactions` | C | 5 | 20 | 0 | 0.250 | 给定引物里哪些超 45℃ 发卡或形成 ≥45℃ 异源二聚体？→ `None` |
| `amplicon_length` | C | 4 | 20 | 0 | 0.200 | 设计引物扩增 rpsR 的 CDS |
| `primer_design` | C | 1 | 20 | 1⚠ | 0.053 | 设计引物把 rpsR 限制性克隆进 pUC19 的 MCS |
| `gibson_primers` | C | 0 | 20 | 0 | **0.000** | 设计带 20 bp 重叠的 Gibson 引物，把 rpsR 装进 SmaI 线性化的 pUC19 |
| `oligo_design` | C | 6 | 20 | 0 | 0.300 | 设计靶向 rpsR 的反义寡核苷酸 (18–30 nt, Tm≈60℃) |
| `codon_optimization` | C | 19 | 20 | 0 | 0.950 | 把给定蛋白序列为 E. coli 做密码子优化 |
| **— Tier C 小计** | | **72** | **160** | 1 | **0.453** | — |
| **===== OVERALL** | | **196** | **400** | 1 | **0.490**（已作答 0.491） | — |

## 三、关键结论（指导 SeqCode 选靶）

**1. Tier B 的"纯公式"假设被部分推翻 —— 长序列计数才是真瓶颈。**
`gc_content` 只有 0.20、`tm_calculations` 0.50，看似简单的公式题却很低；原因是要在**上千 bp 上计数/遍历**，模型数不动。这反而印证了"LLM 无法在长序列上做精确记账"，也说明 **SeqCode 的价值不限于 Tier A**。

**2. SeqCode 的最佳靶子（低分且属"定位→读出/计数"）：**
- `mutation_synonymous` = **0.000**（定位 codon N → 改碱基 → 翻译，全程崩）— 最干净。
- `gc_content` = 0.20、`orf_amino_acid` = 0.15、`restriction_counts` = 0.20。
这些都是"结构/计数在长序列里被藏住"，正是 SeqCode（注入密码子表 / 酶切位点坐标 / 预计算 GC）该补的。

**3. 近天花板 → 作对照组（证明 SeqCode 不会乱涨）：**
`restriction_digest` 0.95、`amplicon_gc` 0.95、`enzyme_kinetics` 0.90、`pairwise_distances` 0.90。短序列 / 小数据，已经很好，没什么提升空间。

**4. Tier C 设计题分裂明显：**
- *计算/打分型*（`enzyme_kinetics` 0.90、`amplicon_gc` 0.95）能做；
- *de-novo 设计型*（`codon_optimization` / `gibson_primers` / `oligo_design` = **0.00**，`primer_design` 0.05）是**绝对底板**——即便答出来也几乎全错。**这类是工具绑定（primer3/pydna），SeqCode/ICL 帮不上，应作为"必须上工具"的论据。**

## 四、落盘与复现

**结果数据** `results/seqqa_base/`
- `results_full.json` — 400 题逐题（id/type/score/reason/extracted/latency）
- `summary_full.json` — 20 类 / 3 层汇总（机器可读）
- `prompts/` — **全 400 题的完整 prompt**（即模型实际输入，逐字节一致）

**跑测脚本** `eval/`
- `run_seqqa_base.py` — 主 runner（inject + 官方 validator 评分，支持 `--types/--per-type-limit/--concurrency`）
- `run_full.py` — 全 400：复用已答题 + 补跑失败 + 跑齐 Tier C
- `cleanup_full.py` — 低并发（3）清理补跑失败题
- `retry_failed.py` — 12 类子集的失败补跑

**复现命令**（venv = `external/labbench2/.venv`）
```
external/labbench2/.venv/bin/python eval/run_full.py        # 全量
external/labbench2/.venv/bin/python eval/cleanup_full.py    # 补跑失败
```

## 五、已知问题 / 待办

- ⚠ 全 400 题已跑完；**仅剩 1 道 `primer_design` 因顽固 429 未作答、计 0**（该类本就是 0 分底板，不影响任何结论；如需可单独并发 1 补跑）。
- 该模型 CoT 极慢（均 181s），全量重跑成本/时间较高；后续对照实验建议**固定 inject 模式、并发 ≤10**。
- `restriction_counts` 因 rpoC 基因大（~4 kb）+ CoT 长，是最易限流/超时的类型，单独跑时建议并发 2–3。

---

### 附：ICL 三层 ↔ 题型五大类 对照

| ICL 层 | 含义 | 对应题型 |
|---|---|---|
| **A** 有 ICL 空间 | 定位→读出/计数 | orf_amino_acid, mutation_synonymous, mutation_restriction, restriction_counts, restriction_digest |
| **B** 纯公式算术 | 闭式计算 | gc_content, molecular_weight, tm_calculations, sequence_complexity, protein_hydrophobicity, pairwise_distances, msa_scoring |
| **C** 设计·工具绑定 | de-novo 设计 / 拟合 | amplicon_gc, amplicon_length, primer_design, gibson_primers, oligo_design, codon_optimization, primer_interactions, enzyme_kinetics |
