"""dnacode rendering test — no API needed (pure Biopython)."""
from Bio.Seq import Seq
from Bio.SeqFeature import FeatureLocation, SeqFeature
from Bio.SeqRecord import SeqRecord

from dpsk_v4_bioseq_agent.prompt_injection.dnacode import to_dnacode


def _demo_record():
    dna = "ACGTACGT" + "ATGGCTGAAAAGCTGATCGCATAA" + "TTGCATGC"   # 5'UTR + CDS(ATG..TAA) + 3'UTR
    rec = SeqRecord(Seq(dna), id="demo",
                    annotations={"molecule_type": "DNA", "topology": "linear", "organism": "synthetic"})
    rec.features.append(SeqFeature(FeatureLocation(8, 8 + 24), type="CDS", qualifiers={"gene": ["demoG"]}))
    return rec


def test_codons_and_markers_rendered():
    out = to_dnacode(_demo_record(), level=1)
    assert isinstance(out, str)
    assert "START" in out and "STOP" in out
    assert "ATG (M)" in out          # start codon -> Met
    assert "TAA (*)" in out          # stop codon
    assert "GC=" in out              # computed annotation present
