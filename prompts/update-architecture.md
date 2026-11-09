---
description: Update the repo's architecture documentation after an implementation change
---

# Update architecture documentation

Run this prompt after an implementation task and before review or PR preparation. The
implementation is already complete; this prompt updates the architecture documentation to match the
verified repository state. Do not modify implementation code.

**A stale document still validates.** Whatever checker this repo runs over its architecture
artefacts proves that a document is internally consistent and that its citations resolve. It
**cannot** tell you that a component name, a relationship, or a participant still describes the
system. A green check is evidence about the *document*, not about the truth of its content, and
"the committed document says X" is not a reason to keep X. **Re-derive every claim from the code,
the configuration and the deployed artefacts before preserving it.**

## Variables

change_ref: $1
base_ref: $2

- `change_ref` is optional. If supplied, use it as the commit, branch, or PR/change reference to
  review.
- `base_ref` is optional. If omitted, use the repo's base branch when it exists.
- If neither argument is supplied, review the current branch relative to the base branch, plus
  staged, unstaged and untracked files.

## Scope

The artefacts this prompt may change are the ones the repo's architecture directory
(`paths.architecture_dir`) contains, as its `aidw/conventions.md` and root `AGENTS.md` define and
approve them. That list is the repo's to declare — a repo whose conventions name no architecture
artefact has nothing for this stage to update, and this prompt then records that conclusion and
changes nothing.

- Update only the artefacts a change actually affects. Do not create a new document, a new diagram
  or a new directory to have somewhere to write: if a completed change seems to need one, stop and
  ask for it to be approved and added to the repo's list first.
- Keep each artefact internally consistent with the others it repeats facts from.
- Follow the authoring contract the repo documents for that directory — its conventions, its
  tooling, its validation commands and its size/geometry budgets. If the repo uses tooling this
  prompt does not name, read that tooling's own instructions rather than guessing.

The architecture documentation describes **verified implementation**. Do not add a component,
relationship, runtime behaviour, security property or deployment dependency solely because a design
document proposes it. A placeholder is documented as a placeholder; something not implemented is
not drawn at all.

## Instructions

1. **Set the review frame.** Read the repo's root `AGENTS.md` and `aidw/conventions.md`. Determine
   the current branch and repository status, identify the change being documented, and inspect the
   complete relevant diff — including staged, unstaged and untracked files. If `change_ref` is
   supplied, include that change explicitly. Preserve unrelated user changes: do not reset,
   checkout, clean, commit, push, or modify implementation files.
2. **Classify the change.** Identify whether it affects a deployed resource or topology, a service,
   API, persistence layer, queue or event flow, a runtime boundary, an existing artefact's facts,
   or nothing architecture-relevant. State the classification before you edit anything.
3. **Read the implementation evidence.** Inspect the changed source, configuration, deployment
   definition and tests in context; prefer the actual implementation and any generated or
   synthesised artefacts over prose. Record exact names, ownership, boundaries, protocols,
   endpoints and whether a component is live, a placeholder, optional or deferred.
4. **Verify from generated evidence.** Where the repo's architecture facts can be derived from a
   generated artefact (a synthesised template, a schema dump, a manifest), generate it with the
   repo's own command and check the facts against it. Do not document a resource as deployed
   unless the source and the generated evidence agree.
5. **Update the affected artefacts** with targeted edits. Remove stale entries, paths and claims
   rather than leaving contradictory text. Use repository-relative paths within the architecture
   directory.
6. **Re-derive every diagram you touch.** Rebuild it from the evidence above, not by patching
   labels. Validate after every candidate edit and immediately before delivery with the repo's
   validation command, and never hand-edit a generated artefact. If validation or the repo's
   browser/visual evidence fails, repair the source specification and re-run — reporting an
   environmental failure truthfully instead of claiming verification.
7. **Keep the allowlist closed.** If the change needs an artefact the repo's list does not name,
   stop and ask instead of creating it. If nothing architecture-relevant changed, leave every
   artefact untouched and state why.
8. **Verify the result.** Confirm the links and repository-relative paths resolve, re-run the
   repo's checks, and run `git diff --check`. Review the final diff for stale paths,
   contradictions, invented facts, accidental implementation changes and unrelated modifications.

## Done when

- Every affected architecture artefact accurately describes the verified implementation, derived
  from source and generated evidence.
- Only the repo's approved architecture artefacts changed — no new documents, diagrams or
  directories.
- Any artefact this run re-derived was re-derived from evidence and passes the repo's validation,
  with its "last verified" record (if the repo keeps one) updated only for artefacts actually
  re-checked, never backdated.
- If nothing architecture-relevant changed, that conclusion is recorded and nothing was changed.
- `git diff --check` passes and the final diff contains only intended documentation updates.

If the implementation, the generated evidence or the cited specification is ambiguous or
contradictory — especially for security boundaries, permissions, data ownership or irreversible
changes — stop and ask rather than guessing.

## Response

Return:

1. The architecture artefacts updated, with paths.
2. The evidence and commands used to verify them.
3. Any remaining unverified areas or environment limitations.
