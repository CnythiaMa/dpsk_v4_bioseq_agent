# dpsk_v4_bioseq_agent

> 📊 **[在线结果总览 →](https://cnythiama.github.io/dpsk_v4_bioseq_agent/web/overview.html#overview)** —— 交互式网页,一眼看全 SeqQA / CloningQA 各配置成绩与逐题对比。

一个极简的**代码执行 Agent：**让本身没有工具的大模型(**DeepSeek-V4-flash / -pro**)
通过**自己写并运行 Python**(在沙箱里)来解 **LabBench2** 的序列 / 克隆题——而不是在思维链里硬数碱基、易出错。

整套"工具环境"只有 **一个 Python 沙箱 + 一个 in-silico 装配自检**。**没有路由层、也没有输出格式对齐层**——每道题直接进 Agent 循环。

> 完整的研究思路与方法学见 [`docs/methodology.md`](docs/methodology.md)。

## 为什么需要它

DeepSeek-V4 总体很强,但在长序列任务(互补配对、碱基计数、特征定位)上容易**陷入冗长、易错的"反复计数"思维链**。
而这些是**确定性、对数值敏感**的任务——恰好是代码能一击解决的。所以给模型一个沙箱,把机械计算卸载出去,
**设计与决策仍留在模型**。

## 结果(官方 LabBench2 验证器评分)

**CloningQA**(14 题,设计密集)—— 完整表见 [`docs/cloning_comparison.md`](docs/cloning_comparison.md):

| 配置                           |                 成绩 |
| ------------------------------ | -------------------: |
| v4-flash · 无工具             |           3/14 (21%) |
| **v4-flash · 代码 Agent**    |      **4/14 (29%)** |
| v4-pro · 无工具               |           3/14 (21%) |
| **v4-pro · 代码 Agent** | **5/14 (36%)** |
| GPT-5.5 codex(全工具)          |           8/14 (57%) |
| Opus 4.8(全工具)               |          10/14 (71%) |

**SeqQA2**(400 题,计算密集)—— 完整表见 [`docs/seqqa_comparison.md`](docs/seqqa_comparison.md):

| 配置                             | **已作答准确率** |
| -------------------------------- | ---------------------: |
| flash · 无工具(序列注入 prompt) |                  49% |
| flash · 代码 Agent              |        **73.7%** |
| **pro · 代码 Agent**      |        **79.9%** |

## 安装与准备

完整复现需要三样东西,对应下面三步:**本包** + **官方 LabBench2 代码仓库**(打分器 / 装配引擎 / 题目文件下载器)+ **LabBench2 数据集**(题目 parquet)。
注意:代码仓库和数据集是**两个独立的来源**,数据集**不随代码仓库一起下载**。

**第 1 步 · 安装本包**

```bash
pip install -e .            # 或:pip install -e ".[test]"
cp .env.example .env        # 填入 ARK_API_KEY,以及下面两步得到的路径
```

**第 2 步 · 克隆官方 LabBench2 代码仓库 → `LABBENCH_ROOT`**

提供官方打分器 / in-silico 装配引擎 / 题目文件下载器(`evals.utils`):

```bash
git clone https://github.com/EdisonScientific/labbench2
# 然后在 .env 里设:LABBENCH_ROOT=/abs/path/to/labbench2
```

**第 3 步 · 下载 LabBench2 数据集 → `LABBENCH_DATA_ROOT`**

题目清单(parquet)来自 HuggingFace 数据集
[`EdisonScientific/labbench2`](https://huggingface.co/datasets/EdisonScientific/labbench2),需单独拉取:

```bash
# 把数据集下到 $LABBENCH_DATA_ROOT/labbench2/ 下(下例假设 LABBENCH_DATA_ROOT=/abs/path/to/benchmarks)
huggingface-cli download EdisonScientific/labbench2 \
  --repo-type dataset --local-dir /abs/path/to/benchmarks/labbench2
# 然后在 .env 里设:LABBENCH_DATA_ROOT=/abs/path/to/benchmarks
```

下完后,目录必须满足以下结构(runner 直接读这两个文件,缺了会报错并提示本步骤):

```
$LABBENCH_DATA_ROOT/
└── labbench2/
    ├── seqqa2/train-00000-of-00001.parquet
    └── cloning/train-00000-of-00001.parquet
```

> 每道题的**原始序列文件**(`.gb` 等)无需手动准备——runner 运行时会通过官方 `download_question_files` 自动从 GCS 拉取。
> 你手动准备的只有上面这两个题目清单 parquet。

## 运行

```bash
dpsk-bioseq-cloning --model pro                 # 14 道 CloningQA
dpsk-bioseq-seqqa   --model flash --type gc_content
# 或以模块运行:
python -m dpsk_v4_bioseq_agent.run_cloning --model flash
# 可选的实时看板(另开一个终端):
dpsk-bioseq-dashboard --progress runs/cloning_pro/progress.json --port 8765 --title CloningQA
```

每次运行写到 `runs/<任务>_<模型>/`:`results.json`(逐题 score/reason)和
`transcripts/*.json`(**完整的原始模型 I/O**:system+user prompt、每个 assistant 轮含 tool_calls/reasoning、
每个 tool 返回、最终答案)。

## 仓库结构

```
src/dpsk_v4_bioseq_agent/
├── sandbox.py            # 工具本体:run_python + dry_run_protocol(不含任何生物学逻辑)
├── agent.py             # 代码 Agent 循环:design_cloning() / solve_seqqa()
├── scoring.py           # 官方 cloning_reward + seqqa-validator 打分
├── llm.py               # Ark 请求层 + 429/5xx 重试退避 + thinking 开关
├── adaptive.py          # API 自适应动态调度并发限流器
├── config.py            # env 驱动的配置 + 外部 LabBench2 接入
├── run_cloning.py / run_seqqa.py   # CLI 驱动(同时是 console 入口)
├── monitor/             # 可选:进度追踪 + 零依赖网页看板
└── prompt_injection/    # 一条记录在案的弯路:把结构化摘要注进 prompt
                         #   (SeqQA 用 dnacode.py,CloningQA 用 restructure_prompt.py)
docs/      # 方法学(中文)+ 结果对比
results/   # 逐题结果 JSON
tests/     # 无 API 模块的单元测试(sandbox、adaptive、dnacode)
```

## 一轮长什么样

模型发出一个 `run_python` 工具调用,参数是**它自己写的** Python:

```python
from Bio import SeqIO
rec = SeqIO.read("plvx-egfp-ires-puro.gb", "genbank")
egfp = next(f for f in rec.features if "EGFP" in (f.qualifiers.get("label") or [""])[0])
print(int(egfp.location.start), int(egfp.location.end))
```

`sandbox.run_python` 只是把它丢进子进程执行、返回 stdout——它从不知道 "EGFP" 是什么。
所有领域逻辑都在模型现写的代码里。

## 许可

MIT —— 见 [LICENSE](LICENSE)。
