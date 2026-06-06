#!/usr/bin/env python
"""
Restructure a LabBench2 cloning prompt for better long-context focus.

Idea (in-context only, no model changes):
  - The raw GenBank dumps are a haystack. For cloning, only the EDGES of each
    feature matter (CDS start/stop, vector cut sites, recombination sites...).
  - LLMs are bad at "extract bases 2824..2871 from this ORIGIN block". So we
    pre-compute those slices DETERMINISTICALLY with Biopython and put them up front.
  - Transformation is a PURE FUNCTION of the file, identical for every problem,
    and computes edges for ALL features (no answer-specific logic) -> no overfit.
  - Raw files are kept but strongly de-emphasized ("do not read unless necessary").

Usage:
  python restructure_prompt.py <input_prompt.txt> [--window 45] [-o out.txt]
"""
import argparse
import io
import re
import sys
from pathlib import Path

from Bio import SeqIO


FILE_MARKER = re.compile(r'^File:\s*(.+?)\s*$', re.MULTILINE)
# Markers that signal the start of the task instructions (end of the human request)
INSTR_MARKERS = [
    "In your answer, refer to files",
    "You need to express the final protocol",
    "You may use the following operations",
]


def split_blocks(text: str):
    """Split prompt into [(filename, content), ...] file blocks + trailing prose."""
    markers = list(FILE_MARKER.finditer(text))
    if not markers:
        return [], text

    blocks = []
    for i, m in enumerate(markers):
        name = m.group(1).strip()
        content_start = m.end()
        content_end = markers[i + 1].start() if i + 1 < len(markers) else len(text)
        block = text[content_start:content_end]
        blocks.append((name, block))

    # The last block's content contains the file body + the trailing task prose.
    last_name, last_block = blocks[-1]
    file_body, trailing = _peel_trailing_prose(last_block)
    blocks[-1] = (last_name, file_body)
    return blocks, trailing


def _peel_trailing_prose(block: str):
    """Separate a GenBank/FASTA body from the question prose that follows it."""
    # GenBank ends with a line '//'. Everything after the final '//' is prose.
    lines = block.splitlines(keepends=True)
    last_slashes = None
    for idx, ln in enumerate(lines):
        if ln.strip() == "//":
            last_slashes = idx
    if last_slashes is not None:
        body = "".join(lines[: last_slashes + 1])
        prose = "".join(lines[last_slashes + 1 :])
        return body, prose
    # FASTA / txt last file: fall back to scanning for an instruction marker.
    for marker in INSTR_MARKERS:
        pos = block.find(marker)
        if pos != -1:
            # back up to the start of that line
            line_start = block.rfind("\n", 0, pos) + 1
            return block[:line_start], block[line_start:]
    return block, ""


def detect_kind(content: str) -> str:
    if "LOCUS" in content and re.search(r'^ORIGIN', content, re.MULTILINE):
        return "genbank"
    if content.lstrip().startswith(">"):
        return "fasta"
    return "txt"


def gc_pct(seq: str) -> float:
    seq = seq.upper()
    if not seq:
        return 0.0
    gc = sum(seq.count(b) for b in "GC")
    return 100.0 * gc / len(seq)


def fmt_feature_index(rec) -> str:
    lines = []
    seqlen = len(rec.seq)
    for f in rec.features:
        ftype = f.type
        if ftype == "source":
            continue
        label = (f.qualifiers.get("label")
                 or f.qualifiers.get("gene")
                 or f.qualifiers.get("note")
                 or [ftype])[0]
        label = label.replace("\n", " ")[:40]
        start = int(f.location.start) + 1   # GenBank 1-based inclusive
        end = int(f.location.end)
        strand = {1: "+", -1: "-", None: "."}.get(f.location.strand, ".")
        flen = end - start + 1
        lines.append(f"  {ftype:<14} {label:<40} {start:>6}..{end:<6} {strand} len={flen}")
    return "\n".join(lines)


def fmt_junctions(rec, window: int) -> str:
    seq = str(rec.seq).upper()
    seqlen = len(seq)
    out = []
    seen = set()
    for f in rec.features:
        if f.type == "source":
            continue
        label = (f.qualifiers.get("label")
                 or f.qualifiers.get("gene")
                 or [f.type])[0]
        label = label.replace("\n", " ")[:40]
        s = int(f.location.start)          # 0-based
        e = int(f.location.end)            # 1-based-exclusive == top-strand end coord
        strand = {1: "+", -1: "-", None: "."}.get(f.location.strand, ".")

        left = seq[s: s + window]
        right = seq[max(0, e - window): e]
        # left edge: top-strand coords (s+1 .. s+len)
        lc = (s + 1, s + len(left))
        rc = (e - len(right) + 1, e)

        key = (label, lc, rc)
        if key in seen:
            continue
        seen.add(key)

        out.append(f"  [{f.type} | {label} | strand {strand}]")
        out.append(f"    left  {lc[0]:>6}..{lc[1]:<6} (top, GC {gc_pct(left):4.0f}%): {left}")
        out.append(f"    right {rc[0]:>6}..{rc[1]:<6} (top, GC {gc_pct(right):4.0f}%): {right}")
    return "\n".join(out)


def fmt_construct_ends(rec, window: int) -> str:
    seq = str(rec.seq).upper()
    topo = "circular" if _is_circular(rec) else "linear"
    head = seq[:window]
    tail = seq[-window:]
    note = " (adjacent to head; molecule is circular)" if topo == "circular" else ""
    return (f"    head 1..{len(head)} (top): {head}\n"
            f"    tail {len(seq) - len(tail) + 1}..{len(seq)} (top){note}: {tail}")


def _is_circular(rec) -> bool:
    topo = rec.annotations.get("topology", "")
    return str(topo).lower() == "circular"


def summarize_genbank(name: str, content: str, window: int) -> str:
    rec = SeqIO.read(io.StringIO(content), "genbank")
    seqlen = len(rec.seq)
    topo = "circular" if _is_circular(rec) else "linear"
    locus = rec.name
    desc = (rec.description or "").replace("\n", " ").strip()
    parts = [
        f"### FILE: {name}",
        f"LOCUS: {locus}  |  {seqlen} bp  |  {topo}",
        f"DESCRIPTION: {desc}" if desc and desc != "." else None,
        "",
        "FEATURE INDEX  (type | label | start..end | strand | length):",
        fmt_feature_index(rec),
        "",
        f"FEATURE JUNCTIONS  (each feature's two edges, top strand 5'->3', {window} bp):",
        fmt_junctions(rec, window),
        "",
        "CONSTRUCT ENDS:",
        fmt_construct_ends(rec, window),
    ]
    return "\n".join(p for p in parts if p is not None)


def summarize_fasta(name: str, content: str, window: int) -> str:
    rec = SeqIO.read(io.StringIO(content), "fasta")
    seq = str(rec.seq).upper()
    return (f"### FILE: {name}\n"
            f"FASTA: {rec.id}  |  {len(seq)} bp  (no feature annotations)\n"
            f"    head 1..{min(window, len(seq))} (GC {gc_pct(seq[:window]):.0f}%): {seq[:window]}\n"
            f"    tail {max(1, len(seq)-window+1)}..{len(seq)}: {seq[-window:]}")


def extract_core_request(prose: str) -> str:
    """The human request = prose up to the first task-instruction marker."""
    cut = len(prose)
    for marker in INSTR_MARKERS:
        pos = prose.find(marker)
        if pos != -1:
            line_start = prose.rfind("\n", 0, pos) + 1
            cut = min(cut, line_start)
    return prose[:cut].strip()


KEYNOTES = """\
=============================  KEYNOTES  (read first)  =========================
Before you start, keep these primer-design fundamentals in mind:

1. STRAND DIRECTION IS CRITICAL. Every primer is written 5'->3'. The FORWARD
   primer = the top-strand sequence at the LEFT edge of your target region (as
   shown in the summaries). The REVERSE primer = the REVERSE COMPLEMENT of the
   top-strand sequence at the RIGHT edge. If a feature is annotated on the minus
   strand, reverse-complement accordingly. Getting this wrong is the #1 error.
2. A PCR product spans exactly from where the forward primer anneals to where the
   reverse primer anneals. Pick edges that INCLUDE what you want and EXCLUDE what
   you want removed.
3. Annealing region ~18-25 nt, GC ~40-60% (the GC% of every edge is printed for
   you). Any assembly overhang goes on the 5' end of the primer; the 3' end must
   match the template exactly.
4. Linearizing a CIRCULAR backbone by PCR: the two vector primers point OUTWARD
   (away from each other) and anneal in the FLANKS of the segment being removed —
   never inside it.
5. Coordinates in the summaries are 1-based inclusive and already sliced at exact
   positions. Do NOT recount positions by hand.
6. Self-check: mentally reconstruct each junction 5'->3' and confirm the fragments
   join in the intended order and orientation before writing the final protocol.
==============================================================================="""


USAGE_NOTICE = """\
===================  HOW TO USE THIS PROMPT  (read carefully)  ===================
Your ONLY working data is the STRUCTURED SUMMARIES section below. It was generated
deterministically from the source files and already contains, for every feature,
the exact edge sequences you need.

*** DO NOT open, read, scan, or count positions inside the RAW GENBANK FILES. ***
They are an emergency fallback only. They contain NOTHING you cannot already get
from the summaries, and hand-counting positions in an ORIGIN dump is the single
biggest source of wrong primers. Reading them only wastes your attention and
introduces errors.

Work entirely from FEATURE INDEX / FEATURE JUNCTIONS / CONSTRUCT ENDS. Only if a
specific sequence you need is genuinely missing from the summaries may you consult
ONE raw file — and even then, copy only that one slice.
================================================================================="""


OUTPUT_PROCEDURE = """\
=========================  OUTPUT PROCEDURE  (follow in order)  ==================
Reason in this exact order. Use ONLY the structured summaries.

<relevant_features>
List only the features actually involved in this cloning. For each, copy its
edge sequence(s) verbatim from FEATURE JUNCTIONS, with file name and coordinates.
Ignore every other feature.
</relevant_features>

<primer_design>
For each primer write: annealing region (copied from a feature edge) + any
overhang (copied from the adjacent fragment's edge), then the full 5'->3'
nucleotide string. Mind strand/orientation and reverse-complement where needed.
</primer_design>

<protocol>
The final single functional expression, per the grammar and ADDITIONAL
REQUIREMENTS stated above. Use exact base filenames; write real primer sequences
as quoted literals.
</protocol>
================================================================================="""


def build_prompt(blocks, trailing, window: int) -> str:
    core = extract_core_request(trailing)

    summaries = []
    raw_sections = []
    for name, content in blocks:
        kind = detect_kind(content)
        try:
            if kind == "genbank":
                summaries.append(summarize_genbank(name, content, window))
            elif kind == "fasta":
                summaries.append(summarize_fasta(name, content, window))
            else:
                summaries.append(f"### FILE: {name}\n(plain text)\n{content.strip()}")
        except Exception as ex:  # noqa: BLE001
            summaries.append(f"### FILE: {name}\n(could not parse: {ex}; see raw below)")
        raw_sections.append(f"File: {name}\n{content.rstrip()}\n")

    parts = [
        KEYNOTES,
        "",
        "============================  CLONING REQUEST  =================================",
        core,
        "",
        USAGE_NOTICE,
        "",
        "======================  STRUCTURED SUMMARIES (your data)  ======================",
        "\n\n".join(summaries),
        "",
        "==============  RAW GENBANK FILES  —  DO NOT READ  (fallback only)  ============",
        "Reference-only emergency fallback. Working from these instead of the summaries",
        "above wastes your attention budget and causes position-counting errors.",
        "",
        "\n".join(raw_sections),
        "===============  FULL ORIGINAL INSTRUCTIONS  (authoritative)  ==================",
        trailing.strip(),
        "",
        OUTPUT_PROCEDURE,
    ]
    return "\n".join(parts) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("--window", type=int, default=45)
    ap.add_argument("-o", "--output")
    args = ap.parse_args()

    inp = Path(args.input)
    text = inp.read_text()
    blocks, trailing = split_blocks(text)

    sys.stderr.write(f"[parsed] {len(blocks)} file block(s):\n")
    for name, content in blocks:
        sys.stderr.write(f"   - {name}  ({detect_kind(content)}, {len(content)} chars)\n")

    out_text = build_prompt(blocks, trailing, args.window)

    if args.output:
        out = Path(args.output)
    else:
        out = inp.with_name(inp.stem + "_restructured" + inp.suffix)
    out.write_text(out_text)

    sys.stderr.write(f"[written] {out}\n")
    sys.stderr.write(f"[size] original {len(text)} -> restructured {len(out_text)} chars\n")


if __name__ == "__main__":
    main()
