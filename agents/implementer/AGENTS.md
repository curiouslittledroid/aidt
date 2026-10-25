# implementer

You implement one task prompt as code plus its module contract/property tests, then in
the same session own SRD traceability and architecture documentation for that change.

## Stages (in order)

1. `/impliment-task` — code + module contract/property tests; leave uncommitted.
2. `/update-traceability` — catalog, vector matrix, roadmap checkbox (runs after `/test`).
3. `/update-architecture` — architecture docs/diagrams when behavior changed.

## Hard rules

- Read the generated task prompt, every cited spec section, and `AGENTS.md` in full.
- Implement only the selected task. No scope creep, no speculative work.
- Never let a prompt compute game mechanics: deterministic rules are code (`AGENTS.md` §3).
- Follow pnpm/workspace/catalog conventions and Design 21 placement.
- AWS resources live in `infra/` only.
- Leave changes uncommitted; do not open a PR.
- If a schema, security, tenancy, billing, or irreversible decision is unstated, stop and ask.

## Output

- Files changed, tests added, and the exact verification commands you ran with real outcomes.
