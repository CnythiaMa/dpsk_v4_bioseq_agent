"""Sandbox tests — no API needed (run_python uses a local subprocess + Biopython)."""
from dpsk_v4_bioseq_agent.sandbox import dsl_safe_name, run_python


def test_state_persists_across_cells_and_biopython(tmp_path):
    hist: list[str] = []
    c1 = "x = 21 * 2\nprint('set')"
    r1 = run_python(tmp_path, c1, hist)
    hist.append(c1)
    assert r1["ok"] and "set" in r1["stdout"]

    # next cell sees `x` from the previous cell; prior stdout is suppressed
    r2 = run_python(tmp_path, "from Bio.Seq import Seq\nprint(x, str(Seq('ACGT').reverse_complement()))", hist)
    assert r2["ok"]
    assert "42 ACGT" in r2["stdout"]      # rev-comp of ACGT is ACGT
    assert "set" not in r2["stdout"]      # only the new cell's stdout is returned


def test_error_is_captured(tmp_path):
    r = run_python(tmp_path, "1 / 0", [])
    assert r["ok"] is False
    assert "ZeroDivisionError" in (r.get("stdout", "") + r.get("stderr", ""))


def test_dsl_safe_name():
    assert dsl_safe_name("addgene-x (1).gbk") == "addgene-x__1_.gbk"
