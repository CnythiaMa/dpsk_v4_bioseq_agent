# DeepSeek-V4 生物序列能力评测 + 代码 Agent 优化

> **评估发现 DeepSeek-V4 在生物序列任务上的短板,并用一个"代码执行 Agent"(让模型自己写 Python 在沙箱里算)把它补上。** 在纯计算的 SeqQA 上准确率近乎翻倍(~19% → 50.7%);在多步设计的 Cloning 上有提升但受限于模型本身的 agent 编排能力。

本文是**完整研究思路**;仓库其余部分:

- **[`../README.md`](../README.md)** — 仓库首页(精简概览 + 安装运行)
- **[`../src/dpsk_v4_bioseq_agent/`](../src/dpsk_v4_bioseq_agent/)** — 代码 Agent 的最小内核(可 `pip install`)
- **[`cloning_comparison.md`](cloning_comparison.md) / [`seqqa_comparison.md`](seqqa_comparison.md)** — 逐题结果对比;原始数据在 [`../results/`](../results/)

---

## 1. 背景与目标:评估 DeepSeek-V4 的生物能力

我们想评估 **DeepSeek-V4 在生物领域的表现**。参照 OpenAI 的 **gpt-rosalind**([https://openai.com/zh-Hans-CN/index/introducing-gpt-rosalind/](https://openai.com/zh-Hans-CN/index/introducing-gpt-rosalind/)),选用它评测时用到的两个开源榜单:

| 榜单                | HuggingFace 数据集                                                                    | 代码仓库                                                                            |
| ------------------- | ------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------- |
| **LabBench2** | [EdisonScientific/labbench2](https://huggingface.co/datasets/EdisonScientific/labbench2) | [github.com/EdisonScientific/labbench2](https://github.com/EdisonScientific/labbench2) |
| **BixBench**  | [futurehouse/BixBench](https://huggingface.co/datasets/futurehouse/BixBench)             | [github.com/Future-House/BixBench](https://github.com/Future-House/BixBench)           |

> gpt-rosalind 评测整理:`bio/docs/gpt-rosalind-评测整理.md`

### 为什么选 LabBench

在两者之间,我们选了**更偏序列任务的 LabBench**:

- **BioXBench 已经把 Agent 作为评测的内置元素**(给模型工具/notebook 环境),优化空间相对有限;
- **LabBench(SeqQA / CloningQA)是"裸模型"序列任务**——正是能清楚暴露模型短板、且有明确优化抓手的地方。

---

## 2. 基线评测:发现明显差距

对 DeepSeek-V4 在 LabBench 上做了基线评测:

- SeqQA(含无工具 inject 基线):[`seqqa_comparison.md`](seqqa_comparison.md)
- CloningQA(含无工具基线):[`cloning_comparison.md`](cloning_comparison.md)

**结论:DeepSeek-V4 在生物序列任务上与 SOTA(GPT-5.5 / Opus 4.8)有较大差距。**

### 关键观察:失败模式

在涉及**较长序列**的任务上——比如需要**核苷酸互补配对**或**核苷酸计数**——模型很容易**陷入思维链上冗长、反复的计数**,而且数着数着就错(我们在多个案例里看到它编造序列、数错碱基、反向互补出错)。

> 而这些**对数值敏感、靠规则可精确求解**的任务,**恰恰是工具一击即中的**。
> 于是思路自然导向:**用 Agent / 工具辅助来补这个短板。**

---

## 3. 思路一(走过的弯路):把 Agent 能力"外置"进 Prompt

LabBench 的题目**限制使用 in-context learning** 类方法,直接挂一个 Agent 未必符合题意。所以我们先尝试**把 Agent 能力外置**:用脚本预先算好**核酸序列的结构化摘要信息**,塞进 prompt 里,让模型"读现成的摘要"而不是自己数。

> 脚本已放进:**[`../src/dpsk_v4_bioseq_agent/prompt_injection/`](../src/dpsk_v4_bioseq_agent/prompt_injection/)**:
>
> - `dnacode.py`(SeqQA 注入,556 行纯 Biopython)——把裸序列改写成**读框/翻译/坐标外显**的文本
> - `restructure_prompt.py`(CloningQA 注入,342 行)——把每个质粒的**全部特征 + 每个特征两端 45bp 边序列**预先算好放在 prompt 最前面
>
> 共同点:都是**纯函数地把"模型本来要在 ORIGIN 里数"的东西预先确定性算好、外显出来**,对所有题一视同仁(无答案特异逻辑、不过拟合)。

**示例 A —— SeqQA 注入(`dnacode`,读框/翻译/坐标全外显;真实输出):**

```
%% [asserted] id=demo  organism="synthetic"  gene=demoG  molecule=DNA  topology=linear
%% [computed] length=40bp  GC=0.45  MW=12423.9  codon_table=1

Seq demo [1..40] 5'->3'
└─ Region CDS [9..32] demoG -> 8 aa   %% GC=0.4167 Tm=55.5C
    c1 ATG (M) [9..11] START
    c2 GCT (A) [12..14]
    c3 GAA (E) [15..17]
    c4 AAG (K) [18..20]
    c5 CTG (L) [21..23]
    c6 ATC (I) [24..26]
    c7 GCA (A) [27..29]
    c8 TAA (*) [30..32] STOP
%% complement strand implicit (A:T, G:C); reverse_complement on request
```

每个密码子的碱基、氨基酸、坐标、起止都外显;GC/Tm 也算好——模型不必再在思维链里数到第几位、翻译成什么。

**示例 B —— CloningQA 注入(`restructure_prompt`,真实跑自 `pLVX-EGFP-IRES-puro`):**

```
*** 你唯一的工作数据是下面的 STRUCTURED SUMMARIES。不要去原始 GenBank 里手数坐标——
    在 ORIGIN dump 里手数位置是错引物的最大来源。每个特征的两端 45bp 边序列已预先算好。***

==================  STRUCTURED SUMMARIES (your data)  ==================
### FILE: plvx-egfp-ires-puro.gb
LOCUS: pLVX-EGFP-IRES-puro  |  8911 bp  |  circular
DESCRIPTION: mammalian expression of EGFP with puromycin selection

FEATURE INDEX  (type | label | start..end | strand | length):
  promoter       CMV promoter      2505..2708   + len=204
  protein_bind   attB1             2824..2848   + len=25
  CDS            EGFP              2869..3588   + len=720
  protein_bind   attB2             3605..3629   - len=25
  misc_feature   IRES2             3661..4247   + len=587
  CDS            PuroR             4267..4866   + len=600
  CDS            AmpR              7597..8457   - len=861
  …  (全 40+ 个特征,每个带 类型/标签/坐标/链/长度)

FEATURE JUNCTIONS  (each feature's two edges, top strand 5'->3', 45 bp):
  [CDS | EGFP | strand +]
    left   2869..2913 (GC 64%): ATGGTGAGCAAGGGCGAGGAGCTGTTCACCGGGGTGGTGCCCATC   ← ATG 起始
    right  3544..3588 (GC 60%): ACCGCCGCCGGGATCACTCTCGGCATGGACGAGCTGTACAAGTAA   ← …TAA 终止
  [protein_bind | attB1 | strand +]
    left   2824..2868 (GC 58%): ACAAGTTTGTACAAAAAAGCAGGCTCCGCGGCCGCCCCCTTCACC
  [protein_bind | attB2 | strand -]
    right  3585..3629 (GC 56%): GTAAAAGGGTGGGCGCGCCGACCCAGCTTTCTTGTACAAAGTGGT

CONSTRUCT ENDS:
    head 1..45    (top): TGGAAGGGCTAATTCACTCCCAAAGAAGACAAGATATCCTTGATC
    tail 8867..8911 (top, 与 head 相邻;质粒为环状): TTAAAGAAATTGTATTTGTTAAATATGTACTACAAACTTAGTAGT
```

**克隆只关心"特征的边"**(CDS 起止、载体切点、重组位点……),所以把每个特征两端各 45bp 的**确切边序列 + 坐标 + GC** 直接铺在前面——引物设计要的片段直接抄,不用再去 8911bp 的 ORIGIN 里数。

**但测试发现这条路不行:**

- **SeqQA**:把这种摘要塞进 prompt,等于**直接泄露了答案**(摘要里就含 GC/Tm/翻译等要算的量),失去评测意义;
- **CloningQA**:边序列都铺好了,但复杂的多步克隆设计**还是要模型自己做装配设计**(选接头、保读框、多片段定序),光给静态摘要**效果并不好**。

→ 证伪后,转向思路二:真正给模型工具调用能力。

---

## 4. 思路二(最终方案):给模型"工具调用 / 代码执行"能力

于是回到正路——**给模型真正的工具调用能力,走 Agent 路线**:不预先算好喂给它,而是给它一个**沙箱**,让它**自己写代码、自己算、自己验证**。核心文件:

> **[`../src/dpsk_v4_bioseq_agent/sandbox.py`](../src/dpsk_v4_bioseq_agent/sandbox.py)**

### 工具环境 = 一个沙箱 + 一个自检

| 工具                                     | 作用                                                                                                                                                                |
| ---------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **`run_python(code)`**           | 在题目目录起一个**带状态的 Python 子进程**(Biopython 可用,状态跨调用持久)。模型用它读文件、定位 feature、抠序列、做突变、算 GC/Tm/计数、设计引物/overhang…… |
| **`dry_run_protocol(protocol)`** | 把模型设计的克隆**协议在硅基里模拟装配**(PCR 退火、Gibson/GoldenGate/酶切),返回"能不能装配 / 错在哪"——**交卷前的自检,不泄露标准答案**                 |

**沙箱本体不含任何生物学逻辑——它只是个执行器,真正的领域代码是模型每一轮现场写出来、当场执行、用完即弃的。** 智能在模型,算法在 Biopython,沙箱只提供"把模型写的代码跑起来"的轨道。

---

## 5. 架构演进:从三层路由到"最小内核"

最初搭了一个三层 `routed_pipeline`(分类路由 → solver/agent → 格式对齐),但复盘发现对本任务**大部分是冗余的**,GitHub 上传的代码已**精简为最小内核**:

| 层                            | 原设计                                | 本轮是否使用                        |
| ----------------------------- | ------------------------------------- | ----------------------------------- |
| **L1 路由分类器**       | 判断"纯计算走 solver / 还是要 LLM"    | ❌ 去掉——每题直接进 Agent         |
| **L2 solver 分流**      | 命中确定性函数(gc/酶切计数)就直接算   | ❌ 去掉——**纯靠模型写代码** |
| **L2 代码 Agent**       | `run_python` + `dry_run` 多轮循环 | ✅**核心**                    |
| **L3 compose 格式对齐** | 把答案套进 `<answer>` 格式          | ❌ 去掉                             |

**最终最小内核**(`src/dpsk_v4_bioseq_agent/`):

```
sandbox.py   ← run_python 沙箱 + dry_run 自检(工具本体)
agent.py     ← 多轮 tool-calling 循环(design_cloning / solve_seqqa),记录完整 transcript
run_cloning.py / run_seqqa.py  ← 驱动 + 官方打分 + 落盘
llm.py / adaptive.py / config.py  ← 请求层(429 重试)/ 自适应并发 / 配置
```

---

## 6. 结果

### Cloning(14 题,设计密集)— [cloning_comparison.md](cloning_comparison.md)

| 配置                            |                 成绩 |
| ------------------------------- | -------------------: |
| v4-flash 无工具                 |           3/14 (21%) |
| **v4-flash + 代码 Agent** | **4/14 (29%)** |
| v4-pro 无工具                   |           3/14 (21%) |
| **v4-pro + 代码 Agent**   | **5/14 (36%)** |
| GPT-5.5 codex(全工具)           |           8/14 (57%) |
| Opus 4.8(全工具)                |          10/14 (71%) |

### SeqQA(400 题,计算密集)— [seqqa_comparison.md](seqqa_comparison.md)

| 配置                           |          当前正确数 | CoT 截断强制返回 | Agent 截断(待补刷) | 未作答·无数据(待补刷) |    已作答准确率 |
| ------------------------------ | ------------------: | ---------------: | -----------------: | ---------------------: | --------------: |
| flash · 无工具(inject)        |           196 / 400 |               18 |                 — |                     — |           49% |
| **flash · 代码 Agent**  | **278 / 400** |               — |                  4 |                     — | **70.2%** |
| pro · 无工具 ⚠️(残缺)       |            63 / 324 |               — |                 — |                    211 |           55.8% |
| pro · 代码 Agent ⚠️(未补刷) |           203 / 400 |               — |                146 |                     — | **79.9%** |

---

## 7. 核心结论

1. **工具是必要条件,不是充分条件。**

   - **SeqQA(算得准就行)**:工具把**"算得准"几乎翻倍**(已作答准确率 ~45% → 67%/80%),尤其长序列类(`gc_content`、`restriction_counts` 4→20)。但因本轮去掉 compose 格式层,~150 题算对却没按格式输出,**原始分被拉低、增益被掩盖**——这块是工程可补的(预计补完 flash≈67%/pro≈80%)。
   - **Cloning(要多步装配设计)**:工具增益**温和**(flash +1 / pro +2)。瓶颈从"算不对"变成了"设计不对"——后者卡在**模型自身的 agent 编排能力**,而非工具。
2. **失败模式随能力升级而上移。** 同一套工具下,flash 多是"拼不出可运行协议",pro 多是"拼得出但设计不对";Opus 才能把"生成→模拟→修正"的验证回路吃满、做对难题。**给弱编排模型同款工具,补不上和 Opus 的差距。**

---

## 8. 目录导览 & 复现

```
dpsk_v4_bioseq_agent/
├── README.md                 ← 仓库首页(精简)
├── pyproject.toml            ← 打包 + console 入口
├── src/dpsk_v4_bioseq_agent/ ← 代码 Agent 内核(可 pip install)
│   ├── sandbox.py            ← run_python 沙箱 + dry_run 自检(工具本体)
│   ├── agent.py              ← 多轮 tool-calling 循环(design_cloning / solve_seqqa,记录完整 transcript)
│   ├── scoring.py            ← 官方打分;llm/adaptive/config ← 请求层(429 重试)/ 自适应并发 / 配置
│   ├── run_cloning.py / run_seqqa.py  ← CLI 驱动 + 落盘
│   ├── monitor/              ← 可选:进度追踪 + 网页看板
│   └── prompt_injection/     ← 思路一(弯路):dnacode.py + restructure_prompt.py
├── docs/                     ← 本文(methodology)+ 结果对比
├── results/*.json            ← 逐题 score/reason 数据
└── tests/                    ← 无 API 模块单测(sandbox / adaptive / dnacode)
```

**复现**(需一个 LabBench2 checkout + Ark API key):

```bash
pip install -e .
export LABBENCH_ROOT=/path/to/labbench2  LABBENCH_DATA_ROOT=/path/to/benchmarks
export ARK_API_KEY=...
dpsk-bioseq-cloning --model pro      # 14 题 cloning,逐题完整 transcript 落盘
dpsk-bioseq-seqqa   --model pro      # 400 题 seqqa
```

> 注:完整逐轮 transcript 由 runner 自动落盘到 `runs/<task>_<model>/transcripts/`(system+user、每轮 tool_calls/reasoning、tool 返回、最终答案)。
