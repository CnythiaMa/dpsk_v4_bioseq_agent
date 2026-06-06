# prompt-injection-dnacode —— "把 Agent 外置进 Prompt"(走过的弯路)

> 这是**最终代码 Agent 方案之前**尝试过、但被放弃的一条路线,放在这里完整记录思路。

## 背景

LabBench 题目**限制使用 in-context learning / Agent**,直接挂工具未必符合题意。所以第一版思路是**把"工具该算的东西"提前用脚本算好、以结构化文本的形式注进 prompt**——让模型读"现成的序列摘要",而不是自己在思维链里反复数碱基。

两个任务各有一个注入脚本(都是**纯函数、对所有题一视同仁、无答案特异逻辑**,因此不过拟合):

| 任务 | 脚本 | 外显什么 |
|---|---|---|
| **SeqQA** | **`dnacode.py`**(556 行) | 读框 / 翻译(密码子→氨基酸)/ 坐标 / GC·Tm / 重复压缩 |
| **CloningQA** | **`restructure_prompt.py`**(342 行) | 每个特征的**两端 45bp 边序列** + 特征索引 + 构建端点 |

---

## ① SeqQA:`dnacode.py`

思路仿照 *MoleCode*(把分子的隐藏结构外显成可寻址对象),迁移到 DNA:**不是给序列加元数据,而是把模型本来要"脑补"的隐藏结构外显成文本。** 分四层(L0 裸序列 → L1 读框/翻译 → L2 区段/坐标 → L3 注释/GC/Tm/酶切)。

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

用法:
```python
from dnacode import to_dnacode
from Bio import SeqIO
rec = SeqIO.read("gene.gb", "genbank")
print(to_dnacode(rec, level=3))                                  # 注进 prompt 的文本
text, report = to_dnacode(rec, level=3, focus="CDS", verify=True)  # 带自审计复算
```
关键纪律:`[asserted]`(注释给的)与 `[computed]`(Biopython 算的、可复算)分离;`verify=True` 把所有 computed 字段对原始记录复算;大 CDS(>600nt)自动折叠成摘要+校验和。

---

## ② CloningQA:`restructure_prompt.py`

克隆设计只关心**特征的"边"**(CDS 起止、载体切点、重组位点……)。所以这个脚本把一道 cloning 题里每个 GenBank 文件的**全部特征 + 每个特征两端各 45bp 的确切边序列**确定性地算好,放在 prompt 最前面,并把原始 ORIGIN dump 强烈降权("非必要不要读")。

用法:
```bash
python restructure_prompt.py <原始 cloning prompt.txt> [--window 45] -o out.txt
```

真实输出(`pLVX-EGFP-IRES-puro`,8911bp 环状质粒):
```
*** 你唯一的工作数据是下面的 STRUCTURED SUMMARIES。不要去原始 GenBank 里手数坐标——
    在 ORIGIN dump 里手数位置是错引物的最大来源。每个特征两端 45bp 边序列已预先算好。***

==================  STRUCTURED SUMMARIES (your data)  ==================
### FILE: plvx-egfp-ires-puro.gb
LOCUS: pLVX-EGFP-IRES-puro  |  8911 bp  |  circular

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
引物设计要的边序列(EGFP 起止、attB 重组位点……)直接抄,不用再去 8911bp 的 ORIGIN 里数。

> 完整的真实样例见 `bio/results/opus_prompts/q03_*_restructured.txt`。

---

## 两个任务为什么都放弃

| 任务 | 结果 |
|---|---|
| **SeqQA** | ❌ **等于直接泄露答案**——摘要里就含 GC/Tm/翻译等要算的量,失去评测意义 |
| **CloningQA** | ❌ 边序列都铺好了,但复杂的多步装配设计(选接头、保读框、多片段定序)**还是要模型自己做**,光给静态摘要效果不好 |

## 结论
这条路证伪后,才转向**真正给模型工具调用能力**的代码 Agent 方案(见 [`../labbench-code-agent/`](../labbench-code-agent/))——不预先算好喂它,而是给它沙箱让它自己写代码算 + 自检。
