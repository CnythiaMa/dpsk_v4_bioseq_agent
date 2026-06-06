"""The abandoned "externalize the agent into the prompt" approach (a recorded dead end).

Two pure, deterministic summary generators that pre-compute what the model would otherwise
have to count in an ORIGIN dump, and inject it as structured text:

- ``dnacode``            — SeqQA: reading-frame / translation / coordinates made explicit
- ``restructure_prompt`` — CloningQA: per-feature 45 bp edge sequences + feature index

See ``docs/prompt_injection.md`` for why it was dropped in favor of the code-execution agent.
"""
