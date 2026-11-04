---
description: E4.7 fixture filename override for the implement chain's I2 test stage
---
E4.7 FIXTURE FILENAME OVERRIDE (aidw/prompts/test.md) — this prompt lives in the fixture
target repo, not in the toolkit.

It exists only to prove D14 level 2: a same-named file in `<target>/aidw/prompts/` shadows
`<toolkit>/prompts/test.md` (EXTRACTION.md §3.4/§3.6). It is not a usable test prompt: it is
a marker, and `tests/test_override_integration.py` asserts that I2 renders exactly this body
with the frontmatter above stripped (design §7.3).
