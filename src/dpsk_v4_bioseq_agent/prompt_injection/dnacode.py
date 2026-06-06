"""
dnacode.py — 把 DNA 序列改写成 LLM 友好的「结构外显」表示（DNACode）

设计思路源自 MoleCode（给 SMILES 外显分子图）。核心不是“加元数据”，而是
把裸 ATCG 逼模型脑补的隐藏结构外显为可寻址对象：
  - 密码子框 (frame)        —— 头号隐藏结构，对应 SMILES 的连通性
  - 区段/坐标 (region)      —— typed 区间 + 持久坐标 ID
  - 互补/方向 (5'->3')      —— DNA 特有原语
  - 重复压缩 ((unit)×n)     —— 对应 MoleCode 的聚合物 RepeatUnit×n

分层（对应 MoleCode 的 base→ring-aware→scaffold-aware 消融）:
  L0 裸 ATCG
  L1 读框/翻译外显（密码子 + 氨基酸 + 极性）
  L2 区段外显（typed feature 区间 + ID/坐标），CDS 内展开密码子
  L3 注释外显（每区段 GC/Tm + 重复压缩 + 互补提示 + 可选酶切/motif 插件）

Biopython 在这里扮演 MoleCode 里 RDKit 的角色：确定性解析 + 可复算校验。
所有 [computed] 字段都能用 Biopython 当场重算（见 verify_model）。

约定：坐标一律 1-based 闭区间（生物学惯例），与 GenBank 显示一致。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Union

from Bio.Seq import Seq
from Bio.SeqRecord import SeqRecord
from Bio.SeqFeature import SeqFeature
try:                                  # Biopython>=1.81 推荐 SimpleLocation
    from Bio.SeqFeature import SimpleLocation as _Location
except ImportError:                   # 老版本回退
    from Bio.SeqFeature import FeatureLocation as _Location
from Bio.SeqUtils import gc_fraction, molecular_weight
from Bio.SeqUtils import MeltingTemp as _mt
from Bio.Restriction import RestrictionBatch


# 实验室常用酶（~15 种），酶切插件默认就用这一组，且只在命中时输出
COMMON_ENZYMES = [
    "EcoRI", "BamHI", "HindIII", "XhoI", "XbaI",
    "NotI", "NcoI", "NdeI", "SalI", "KpnI",
    "SacI", "PstI", "SmaI", "EcoRV", "SpeI",
]

EXPAND_CAP = 600          # 未聚焦时，CDS 超过此长度(nt)折叠成摘要，避免撑爆上下文
CODON_RUN_MIN = 4         # 连续相同密码子 >= 此数 → 压缩成 (CODON)×n
HOMOPOLYMER_MIN = 8       # 单碱基游程 >= 此数 → 压缩
REPEAT_MIN_COPIES = 3     # 微卫星(unit>=2)最少拷贝数
REPEAT_MIN_LEN = 9        # 微卫星最短总长(nt)


# ----------------------------------------------------------------------------
# 重复检测（可逆压缩：(unit)×n 一定能展开回原子串）
# ----------------------------------------------------------------------------
def find_tandem_repeats(s: str, max_unit: int = 6):
    """返回非重叠串联重复 [(start0, end0_excl, unit, count), ...]，贪心、偏好覆盖更长。"""
    s = str(s)
    n = len(s)
    out = []
    i = 0
    while i < n:
        best = None  # (total_len, unit_len, unit, count)
        for u in range(1, max_unit + 1):
            if i + u > n:
                break
            unit = s[i:i + u]
            count = 1
            j = i + u
            while j + u <= n and s[j:j + u] == unit:
                count += 1
                j += u
            total = count * u
            ok = (count >= HOMOPOLYMER_MIN) if u == 1 else \
                 (count >= REPEAT_MIN_COPIES and total >= REPEAT_MIN_LEN)
            if ok and (best is None or total > best[0] or
                       (total == best[0] and u < best[1])):
                best = (total, u, unit, count)
        if best:
            total, u, unit, count = best
            out.append((i, i + total, unit, count))
            i += total
        else:
            i += 1
    return out


# ----------------------------------------------------------------------------
# 中间模型：先 build 成结构化数据，再 render 成文本，再 verify。
# 这样“计算”和“呈现”分离，校验直接对着原始 record 复算。
# ----------------------------------------------------------------------------
@dataclass
class CodonItem:
    kind: str                 # "codon" | "repeat"
    triplet: str
    aa: str
    start: int                # 1-based forward 坐标
    end: int
    index: Optional[int] = None   # codon 序号（kind=codon）
    count: Optional[int] = None   # 拷贝数（kind=repeat）
    tag: str = ""             # START / STOP


@dataclass
class Region:
    type: str
    start: int                # 1-based 闭区间
    end: int
    strand: int = 1
    label: str = ""           # gene / product
    asserted: bool = True     # True=来自注释；False=本工具预测(ORF)
    gc: Optional[float] = None
    tm: Optional[float] = None
    protein_len: Optional[int] = None
    codons: list[CodonItem] = field(default_factory=list)
    folded: bool = False
    notes: list[str] = field(default_factory=list)


@dataclass
class DnaModel:
    id: str
    length: int
    seq: str
    gc: float
    mw: float
    molecule_type: str
    topology: str
    organism: Optional[str]
    gene: Optional[str]
    codon_table: int
    regions: list[Region] = field(default_factory=list)
    enzyme_hits: list[tuple[str, list[int]]] = field(default_factory=list)
    motif_hits: list[tuple[str, list[int]]] = field(default_factory=list)


# ----------------------------------------------------------------------------
# ORF 预测（无注释序列时合成 CDS 区段；标记为 computed/predicted，不冒充 asserted）
# ----------------------------------------------------------------------------
def find_orfs(seq: Seq, table: int = 1, min_aa: int = 25):
    """返回 SeqFeature 列表（type=CDS, note=predicted_ORF）。坐标 forward，带 strand。"""
    feats = []
    L = len(seq)
    for strand, nuc in [(1, seq), (-1, seq.reverse_complement())]:
        for frame in range(3):
            trim = (L - frame) // 3 * 3
            if trim <= 0:
                continue
            prot = str(nuc[frame:frame + trim].translate(table=table))
            apos = 0
            for seg in prot.split("*"):
                m = seg.find("M")
                if m != -1 and (len(seg) - m) >= min_aa:
                    nt_start = frame + (apos + m) * 3
                    nt_end = nt_start + (len(seg) - m) * 3 + 3  # 含终止子
                    nt_end = min(nt_end, L)
                    if strand == 1:
                        s0, e0 = nt_start, nt_end
                    else:
                        s0, e0 = L - nt_end, L - nt_start
                    feats.append(SeqFeature(
                        _Location(s0, e0, strand=strand),
                        type="CDS",
                        qualifiers={"note": ["predicted_ORF"]},
                    ))
                apos += len(seg) + 1
    feats.sort(key=lambda f: (int(f.location.start), -len(f)))
    return feats


# ----------------------------------------------------------------------------
# 把一个 CDS feature 展开成密码子（含相同密码子的可逆压缩）
# ----------------------------------------------------------------------------
def _codonize(feature: SeqFeature, full: Seq, table: int) -> list[CodonItem]:
    coding = feature.extract(full)
    ncod = len(coding) // 3
    codons = [str(coding[k * 3:k * 3 + 3]) for k in range(ncod)]
    prot = str(coding.translate(table=table))
    strand = feature.location.strand or 1
    start1 = int(feature.location.start) + 1
    end1 = int(feature.location.end)

    def coords(k):  # 第 k 个密码子(0-based)的 forward 1-based [a..b]
        if strand >= 0:
            a = start1 + k * 3
            return a, a + 2
        b = end1 - k * 3
        return b - 2, b

    items: list[CodonItem] = []
    i = 0
    while i < ncod:
        j = i
        while j < ncod and codons[j] == codons[i]:
            j += 1
        run = j - i
        aa = prot[i] if i < len(prot) else "?"
        if run >= CODON_RUN_MIN:
            a, _ = coords(i)
            _, b = coords(j - 1)
            lo, hi = min(a, b), max(a, b)
            items.append(CodonItem("repeat", codons[i], aa, lo, hi, count=run))
            i = j
        else:
            a, b = coords(i)
            lo, hi = min(a, b), max(a, b)
            tag = ""
            if i == 0 and codons[i] in ("ATG", "GTG", "TTG"):
                tag = "START"
            if aa == "*":
                tag = "STOP"
            items.append(CodonItem("codon", codons[i], aa, lo, hi,
                                   index=i + 1, tag=tag))
            i += 1
    return items


# ----------------------------------------------------------------------------
# build_model：record -> DnaModel
# ----------------------------------------------------------------------------
def build_model(
    record: SeqRecord,
    level: int = 3,
    focus: Union[None, int, tuple, str] = None,
    table: int = 1,
    linear: bool = True,
    enzymes: Union[None, str, list] = "common",
    motifs: Optional[dict] = None,
    predict_orf: bool = True,
) -> DnaModel:
    seq = record.seq
    L = len(seq)
    ann = record.annotations or {}

    model = DnaModel(
        id=record.id or "unknown",
        length=L,
        seq=str(seq),
        gc=round(gc_fraction(seq), 4),
        mw=round(molecular_weight(seq, seq_type="DNA"), 1) if L else 0.0,
        molecule_type=ann.get("molecule_type", "DNA"),
        topology=ann.get("topology", "linear" if linear else "circular"),
        organism=ann.get("organism"),
        gene=_first(record, "gene"),
        codon_table=table,
    )
    if level <= 0:
        return model

    # 收集区段
    feats = [f for f in record.features if f.type in
             ("gene", "CDS", "exon", "intron", "mRNA", "5'UTR", "3'UTR",
              "promoter", "regulatory", "misc_feature")]
    if not feats and predict_orf:
        feats = find_orfs(seq, table=table)[:3]  # 无注释 → 取前几条预测 ORF

    for f in feats:
        s1 = int(f.location.start) + 1
        e1 = int(f.location.end)
        strand = f.location.strand or 1
        asserted = "predicted_ORF" not in f.qualifiers.get("note", [])
        label = (f.qualifiers.get("gene", [""])[0]
                 or f.qualifiers.get("product", [""])[0]
                 or ("predicted_ORF" if not asserted else ""))
        reg = Region(type=f.type, start=s1, end=e1, strand=strand,
                     label=label, asserted=asserted)

        if level >= 3:
            sub = f.extract(seq)
            reg.gc = round(gc_fraction(sub), 4) if len(sub) else None
            if 0 < len(sub) <= 60:                      # Tm 只对短片段有意义
                try:
                    reg.tm = round(float(_mt.Tm_NN(sub)), 1)
                except Exception:
                    reg.tm = None
            for (a0, b0, unit, cnt) in find_tandem_repeats(str(sub)):
                # 仅对非 CDS（不会逐密码子展开）的区段加重复 note
                if f.type != "CDS":
                    ra = s1 + a0 if strand >= 0 else e1 - b0 + 1
                    rb = ra + (b0 - a0) - 1
                    reg.notes.append(f"({unit})×{cnt} @{ra}..{rb}")

        if f.type == "CDS":
            prot = f.extract(seq).translate(table=table)
            reg.protein_len = len(prot)
            if level >= 1 and _should_expand(reg, focus):
                reg.codons = _codonize(f, seq, table)
            else:
                reg.folded = True
        model.regions.append(reg)

    # L3 插件：酶切（默认 common，命中才记录）
    if level >= 3 and enzymes:
        names = COMMON_ENZYMES if enzymes == "common" else list(enzymes)
        batch = RestrictionBatch(names)
        res = batch.search(seq, linear=linear)
        for enz, sites in sorted(res.items(), key=lambda kv: str(kv[0])):
            if sites:
                model.enzyme_hits.append((str(enz), sites))

    # L3 插件：motif（可选，命中才记录）
    if level >= 3 and motifs:
        up = str(seq).upper()
        for name, pat in motifs.items():
            pat = pat.upper()
            hits, start = [], up.find(pat)
            while start != -1:
                hits.append(start + 1)
                start = up.find(pat, start + 1)
            if hits:
                model.motif_hits.append((name, hits))

    return model


def _first(record, key):
    for f in record.features:
        if key in f.qualifiers:
            return f.qualifiers[key][0]
    return None


def _should_expand(reg: Region, focus) -> bool:
    if focus is None:
        return (reg.end - reg.start + 1) <= EXPAND_CAP
    if isinstance(focus, int):
        return reg.start <= focus <= reg.end
    if isinstance(focus, (tuple, list)) and len(focus) == 2:
        lo, hi = focus
        return not (reg.end < lo or reg.start > hi)
    if isinstance(focus, str):
        return focus.lower() in (reg.type.lower(), (reg.label or "").lower())
    return False


# ----------------------------------------------------------------------------
# render：DnaModel -> DNACode 文本
# ----------------------------------------------------------------------------
def render(model: DnaModel, level: int = 3, width: int = 60) -> str:
    out = []
    # 头部：区分 asserted / computed
    asr = [f"id={model.id}"]
    if model.organism:
        asr.append(f'organism="{model.organism}"')
    if model.gene:
        asr.append(f"gene={model.gene}")
    asr += [f"molecule={model.molecule_type}", f"topology={model.topology}"]
    out.append("%% [asserted] " + "  ".join(asr))
    out.append(f"%% [computed] length={model.length}bp  GC={model.gc}  "
               f"MW={model.mw}  codon_table={model.codon_table}")

    if level <= 0:                                   # L0：裸序列
        out.append("")
        for i in range(0, model.length, width):
            out.append(model.seq[i:i + width])
        return "\n".join(out)

    out.append("")
    out.append(f"Seq {model.id} [1..{model.length}] 5'->3'")

    regions = model.regions
    if not regions and level >= 1:
        # 无区段（全序列），整体当作一个待读框对象
        out.append("├─ (no annotated regions; raw frames available on request)")

    for idx, reg in enumerate(regions):
        last = idx == len(regions) - 1
        branch = "└─" if last else "├─"
        head = f"{branch} Region {reg.type} [{reg.start}..{reg.end}]"
        if reg.strand < 0:
            head += " strand=-"
        if reg.label:
            head += f" {reg.label}"
        if not reg.asserted:
            head += " [predicted]"
        if reg.protein_len is not None:
            head += f" -> {reg.protein_len} aa"
        extra = []
        if reg.gc is not None and level >= 3:
            extra.append(f"GC={reg.gc}")
        if reg.tm is not None and level >= 3:
            extra.append(f"Tm={reg.tm}C")
        if extra:
            head += "   %% " + " ".join(extra)
        out.append(head)

        pad = "    " if last else "│   "
        for note in reg.notes:
            out.append(f"{pad}%% {note}")

        if reg.folded and reg.type == "CDS":
            out.append(f"{pad}%% folded ({reg.protein_len} codons); "
                       f"pass focus= to expand")
        for ci in reg.codons:
            if ci.kind == "repeat":
                out.append(f"{pad}({ci.triplet})×{ci.count} "
                           f"[{ci.start}..{ci.end}]  %% {ci.count}×{ci.aa}")
            else:
                tag = f" {ci.tag}" if ci.tag else ""
                out.append(f"{pad}c{ci.index} {ci.triplet} ({ci.aa}) "
                           f"[{ci.start}..{ci.end}]{tag}")

    # L3 插件输出
    if level >= 3:
        if model.enzyme_hits:
            parts = [f"{enz}×{len(sites)} @{','.join(map(str, sites))}"
                     for enz, sites in model.enzyme_hits]
            out.append("%% sites(common): " + " ; ".join(parts))
        if model.motif_hits:
            parts = [f"{name} @{','.join(map(str, hits))}"
                     for name, hits in model.motif_hits]
            out.append("%% motifs: " + " ; ".join(parts))
        out.append("%% complement strand implicit (A:T, G:C); "
                   "reverse_complement on request")
    return "\n".join(out)


# ----------------------------------------------------------------------------
# verify：所有 [computed] 字段对着原始 record 复算（auditability）
# ----------------------------------------------------------------------------
def verify_model(model: DnaModel, record: SeqRecord, table: int = 1) -> dict:
    seq = record.seq
    checks, ok = {}, True

    checks["length"] = (model.length == len(seq))
    checks["gc"] = (model.gc == round(gc_fraction(seq), 4))

    # 每个 CDS：翻译一致 + 密码子视图(含压缩)能复原编码序列
    cds_ok = True
    for reg in model.regions:
        if reg.type != "CDS" or not reg.codons:
            continue
        # 从密码子项重建编码序列
        rebuilt = "".join(
            ci.triplet * (ci.count if ci.kind == "repeat" else 1)
            for ci in reg.codons
        )
        # 取该区段编码链
        loc = _Location(reg.start - 1, reg.end, strand=reg.strand)
        coding = str(SeqFeature(loc).extract(seq))
        if rebuilt != coding:
            cds_ok = False
        # 翻译一致
        aa_from_view = "".join(
            ci.aa * (ci.count if ci.kind == "repeat" else 1)
            for ci in reg.codons
        )
        aa_true = str(Seq(coding).translate(table=table))
        if aa_from_view != aa_true:
            cds_ok = False
    checks["cds_roundtrip"] = cds_ok

    # 酶切复算
    enz_ok = True
    if model.enzyme_hits:
        names = [e for e, _ in model.enzyme_hits]
        res = RestrictionBatch(names).search(
            seq, linear=(model.topology == "linear"))
        for enz, sites in model.enzyme_hits:
            found = res.get([k for k in res if str(k) == enz][0])
            if sorted(found) != sorted(sites):
                enz_ok = False
    checks["enzyme_sites"] = enz_ok

    ok = all(checks.values())
    return {"ok": ok, "checks": checks}


# ----------------------------------------------------------------------------
# 顶层便捷入口
# ----------------------------------------------------------------------------
def to_dnacode(record: SeqRecord, level: int = 3, focus=None, table: int = 1,
               linear: bool = True, enzymes="common", motifs=None,
               predict_orf: bool = True, verify: bool = False):
    """record -> DNACode 文本。verify=True 时返回 (text, report)。"""
    model = build_model(record, level=level, focus=focus, table=table,
                        linear=linear, enzymes=enzymes, motifs=motifs,
                        predict_orf=predict_orf)
    text = render(model, level=level)
    if verify:
        return text, verify_model(model, record, table=table)
    return text


def from_fasta(path: str, **kw):
    from Bio import SeqIO
    return to_dnacode(SeqIO.read(path, "fasta"), **kw)


def from_accession(acc: str, email: str, db: str = "nucleotide",
                   rettype: str = "gb", **kw):
    """从 NCBI 拉取 RefSeq/GenBank 记录并转换（需要联网）。"""
    from Bio import Entrez, SeqIO
    Entrez.email = email
    with Entrez.efetch(db=db, id=acc, rettype=rettype, retmode="text") as h:
        rec = SeqIO.read(h, "genbank")
    return to_dnacode(rec, **kw)


# ----------------------------------------------------------------------------
# 演示
# ----------------------------------------------------------------------------
def _demo_record() -> SeqRecord:
    """构造一个带 promoter/5UTR/CDS(含polyQ)/polyA 的小记录。"""
    promoter = "GCGCTATAAAAGGGCGCGCGCGATCGATCGGCTAGCTAGCT"   # 含 TATA
    utr5 = "ACACACACACACGGTTGGTTGGTTAACCAACCAACCGGAA"        # 含微卫星
    # CDS 逐密码子拼，保证读框对齐、无内部终止子：
    head = "ATGGCCAAGGAATTCGATCGTACGGCA"  # M A K E F D R T A，含 EcoRI(GAATTC)
    polyq = "CAG" * 12                     # polyQ tract → (CAG)×12
    tail = "GGATCCCCCGGGAAATAA"            # G S P G K *，含 BamHI(GGATCC)+SmaI(CCCGGG)
    polya = "AAAAAAA"

    cds_core = head + polyq + tail         # 已是 3 的倍数
    seq = promoter + utr5 + cds_core + polya
    rec = SeqRecord(Seq(seq), id="DEMO001", name="DEMO",
                    description="synthetic demo")
    rec.annotations["molecule_type"] = "DNA"
    rec.annotations["topology"] = "linear"
    rec.annotations["organism"] = "Synthetica demo"

    p0 = 0
    u0 = len(promoter)
    c0 = u0 + len(utr5)
    c1 = c0 + len(cds_core)
    rec.features = [
        SeqFeature(_Location(p0, u0), type="promoter"),
        SeqFeature(_Location(u0, c0), type="5'UTR"),
        SeqFeature(_Location(c0, c1, strand=1), type="CDS",
                   qualifiers={"gene": ["DEMO"], "product": ["demo protein"]}),
        SeqFeature(_Location(c1, len(seq)), type="3'UTR"),
    ]
    return rec


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1].endswith((".fa", ".fasta", ".fna")):
        print(from_fasta(sys.argv[1], level=3))
        sys.exit(0)

    rec = _demo_record()
    for lvl in (0, 1, 2, 3):
        print("=" * 70)
        print(f"L{lvl}")
        print("=" * 70)
        print(to_dnacode(rec, level=lvl))
        print()

    print("=" * 70)
    print("L3 + focus='CDS' + verify")
    print("=" * 70)
    text, report = to_dnacode(rec, level=3, focus="CDS", verify=True)
    print(text)
    print("\n[verify]", report)
