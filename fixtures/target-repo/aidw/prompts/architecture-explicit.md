---
description: E4.7 fixture explicit-path prompt for the implement chain's I4 stage
---
E4.7 FIXTURE EXPLICIT PATH (aidw/prompts/architecture-explicit.md) — this prompt is named by
the stage's own `prompt:` declaration in `aidw/config.yaml`, not by its filename.

It exists only to prove D14 level 1: an explicit path wins over a same-named shadow and never
falls through to levels 2–3 (EXTRACTION.md §3.4/§3.6). Deliberately **not** named
`update-architecture.md`: the filename it shadows is the toolkit's, and the fixture adds no
such shadow, so the only way I4 can resolve here is through the declaration.
