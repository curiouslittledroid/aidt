---
description: E4.7 fixture prompt for the repo-added lint stage
---
E4.7 FIXTURE REPO-ADDED LINT (aidw/prompts/lint.md) — the prompt for the fixture's repo-added
`lint` stage.

The stage is declared in `aidw/config.yaml` with an `agent` but **no** `prompt:`, so this file
is resolved by D14 level 2 (filename shadow on the declared id, EXTRACTION.md §3.5/§3.6). That
is what makes a repo-added stage's prompt resolution the same mechanism as a core stage's.
