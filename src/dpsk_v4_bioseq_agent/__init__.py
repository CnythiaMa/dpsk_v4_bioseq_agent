"""dpsk_v4_bioseq_agent — a minimal code-execution agent that lets DeepSeek-V4 solve
LabBench2 sequence/cloning tasks by writing and running its own Python in a sandbox.
"""
from . import config
from .agent import design_cloning, solve_seqqa
from .sandbox import dry_run_protocol, run_python

__version__ = "0.1.0"
__all__ = ["config", "run_python", "dry_run_protocol", "design_cloning", "solve_seqqa", "__version__"]
