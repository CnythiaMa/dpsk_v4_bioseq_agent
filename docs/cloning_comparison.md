# CloningQA 对比（六次实验）

> 数据集：LABBench2 `cloning`（14 题）· mode=`file` · 官方程序化验证器评分（in-silico 执行 DSL 并与标准答案比对，统一用 `cloning_reward` 独立重评，不采信模型自评）
> 所有配置均带同一段显式指令（必须给真实引物序列 + 文件名不加引号）
> 日期：2026-06-06

本表把 4 方对比扩成 **6 次实验**：在原有「DeepSeek 无工具 / GPT-5.5 / Opus」基础上，新增 **给 DeepSeek（flash 与 pro）装上同款"通用代码执行 agent"** 后的结果，用来回答一个问题——*把 Opus 同款工具给 DeepSeek，它能不能追上来？*

---

## 总榜

| # | 配置 | 工具 | 成绩 | 准确率 | restriction (4) | gibson (6) | golden-gate (4) |
|---|---|---|---:|---:|:--:|:--:|:--:|
| 1 | DeepSeek v4-**flash** · 无工具 | 无 | 3/14 | 21.4% | 3 | 0 | 0 |
| 2 | DeepSeek v4-**flash** · +代码 agent | 通用 | 4/14 | 28.6% | 3 | 1 | 0 |
| 3 | DeepSeek v4-**pro** · 无工具 | 无 | 3/14 | 21.4% | 3 | 0 | 0 |
| 4 | DeepSeek v4-**pro** · +代码 agent | 通用 | **5/14** | **35.7%** | 4 | 1 | 0 |
| 5 | GPT-5.5 · codex（完全放开） | 完全 | **8/14** | **57.1%** | 4 | 3 | 1 |
| 6 | Opus 4.8 · 全工具 | 完全 | **10/14** | **71.4%** | 4 | 4 | 2 |

> 「+代码 agent」= 本仓库 `routed_pipeline` 的通用代码执行 agent（`run_python` 沙箱：Biopython + 装配模拟器自检 `dry_run_protocol`，LLM 自己写代码做定位/提取/突变/设计/模拟，设计推理留在模型）。

---

## 逐题表现（✅ 通过官方验证器 / ❌ 未通过）

| 题 | id | 题型 | flash<br>无 | flash<br>+工具 | pro<br>无 | pro<br>+工具 | GPT-5.5<br>codex | Opus 4.8 |
|---:|---|---|:--:|:--:|:--:|:--:|:--:|:--:|
| 1 | `fb8fc27d` | gibson | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| 2 | `dff28bd4` | gibson | ❌ | ❌ | ❌ | ✅ | ✅ | ✅ |
| 3 | `61e4b666` | gibson | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |
| 4 | `ae62bcdb` | restriction | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 5 | `ad7daee9` | restriction | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ |
| 6 | `5e7bf2b5` | restriction | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 7 | `21e4def0` | golden-gate | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| 8 | `31d22b22` | golden-gate | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| 9 | `3a6704ab` | golden-gate | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |
| 10 | `0a4f4de7` | gibson | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ |
| 11 | `a4bf037c` | gibson | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ |
| 12 | `bc918101` | gibson | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ |
| 13 | `5cf2e092` | golden-gate | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ |
| 14 | `4fb34135` | restriction | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ |
| **合计** | | | **3** | **4** | **3** | **5** | **8** | **10** |

---

## 分题型小计

| 题型 | flash 无 | flash +工具 | pro 无 | pro +工具 | GPT-5.5 | Opus 4.8 |
|---|:--:|:--:|:--:|:--:|:--:|:--:|
| restriction-ligation（4，最模板化） | 3/4 | 3/4 | 3/4 | **4/4** | 4/4 | 4/4 |
| gibson（6，重叠引物设计） | 0/6 | 1/6 | 0/6 | 1/6 | 3/6 | **4/6** |
| golden-gate（4，IIS 酶+接头，最难） | 0/4 | 0/4 | 0/4 | 0/4 | 1/4 | **2/4** |

---

## 关键发现

### 1. 工具是必要条件，但不是充分条件
- 无工具的 DeepSeek（flash / pro）都卡在 **3/14，且只会 restriction**；pro 的额外算力没有突破这堵墙。
- 给 DeepSeek 装上 Opus 同款"通用代码执行 + 模拟自检"后，**flash 3→4、pro 3→5**，首次零星做对 gibson；但**离 Opus 的 10/14 仍差一大截**。
- 结论很干脆：**同样的工具给一个较弱的 agent 编排者，补不上和 Opus 之间的能力差距。**

### 2. 带工具时 pro > flash（5 vs 4），且失败模式发生质变
- pro 唯一明显领先在 **restriction 拿满 4/4**——它没像 flash 那样把模板题"想复杂"（见第 4 点）。
- 更有意义的是**失败原因的变化**：
  - flash 带工具的失败大多是 **"no protocol / no output"**——连一个能解析、能装配的协议都拼不出来；
  - pro 带工具的失败大多变成 **"Accuracy failed"**——它**能产出语法正确、能装配的协议了，只是设计/解读不对**。
- 也就是说 **pro 是更强的编排者**（能收敛到"可运行的设计"），但在 gibson / golden-gate 这类多步精确装配上**依然做不对**。

### 3. 难题的墙没被任何 DeepSeek 配置突破
- **golden-gate 全 0**（flash/pro，有无工具都是 0/4）；**gibson 最多 1/6**。
- Opus 恰恰在这两类领先（gibson 4/6、golden-gate 2/4），这正是 DeepSeek 换型号、加工具都补不上的部分——**多步装配的设计推理能力**。

### 4. 工具反而把一道"会做的题"做坏：#14
- #14（restriction，把 MYOD1 mRNA 克隆进 pIVT 载体）：**无工具 flash/pro 都做对，flash 带工具反而 ❌**。
- 原因：带工具的 flash **自作主张多加了一步 PCR 扩增插入**，但引物退火段对不上模板 → `PCR simulation ran successfully, but no amplicon was observed` → 装配产物为空。它甚至 dry_run 了 3 次、看到了报错，却在轮次内**改不对自己的引物**。
- **pro 带工具把这题修回了 ✅**（4/4 restriction），说明"过度设计 + 改不动"主要是 flash 的弱编排表现；但教训通用：**更大的自由度 + 弱编排 = 容易把简单题做坏且无法自我纠正**。

### 5. 一道曾被判错的题在修复后被做对：#11
- #11（`a4bf037c`，AAV 换 eGFP→NPAS4）输入文件名含**空格与括号** `addgene-…-457689 (1).gbk`，协议 DSL 用裸文件名无法表示该 token，属 **harness/数据缺陷**（4 方对比里两个带工具模型也都因此失分）。
- 本轮在 agent 前置加了 `ensure_dsl_safe_files`（生成无空格/括号的安全副本），**flash 带工具据此正确装配并通过（✅）**；pro 这次因选择了不同的插入口径（accuracy failed）反而没过——说明该题对设计口径（CDS vs 全长）敏感，存在运行间波动。

---

## 可比性说明（重要）

- **DeepSeek「+工具」用的是本仓库的 `routed_pipeline` 通用代码 agent**（`run_python` 子进程沙箱 + Biopython + 装配模拟自检），通过 Ark `deepseek-v4-flash` / `deepseek-v4-pro`（`/coding/v3`，深度思考默认开）。
- **GPT-5.5 codex 与 Opus 4.8 用的是各自原生的"完全放开"agent harness**（可写代码、装包、反复跑脚本自查、模拟自身设计），工具自由度更高。
- 因此 DeepSeek「+工具」与 GPT/Opus 的工具环境**并非完全同档**（前者是受控的两件套沙箱，后者是开放沙箱）。但两者本质都提供"通用代码执行"，故本表的核心读法是：
  1. **工具对 CloningQA 增益明确**（DeepSeek 3 → 4/5；带工具者整体远高于无工具）；
  2. **同款思路的工具下，pro ≥ flash，且失败从"拼不出"升级为"拼得出但不对"**；
  3. **DeepSeek（任意档 + 工具）距 GPT-5.5 / Opus 仍有显著差距，瓶颈是 agent 设计推理能力，而非工具或型号档位。**

---

## 文件

- DeepSeek 无工具：`results/cloning_flash_promptfix.json`、`results/cloning_pro_promptfix.json`
- DeepSeek +代码 agent（本轮）：`results/routed_pipeline/cloning_results_flash.json`、`results/routed_pipeline/cloning_results_pro.json`
- GPT-5.5 codex：`results/codex_gpt55_full/`、`*_scored.json`
- Opus 4.8 全工具：`results/cloning_opus_tools_scored.json`、`results/opus_tools_answers/q*.txt`
- 代码 agent 实现：`routed_pipeline/agent.py`（通用代码 agent）、`routed_pipeline/tools.py`（`run_python` 沙箱 + `dry_run_protocol`）
