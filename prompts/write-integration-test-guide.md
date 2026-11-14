---
description: Write a human-run integration-test guide beside the build results
argument-hint: "[branch]"
---

# Write the integration-test guide

The implementation, its tests and the build-results document are complete on the current
branch. This prompt owns **only one file**: a step-by-step procedure a human follows to
integration-test the change by hand, written beside the build results under the repo's
configured results directory (`paths.implementation_results_dir`).

It is an **instruction document, never an execution**. Nothing here runs an integration test,
a verification gate, or any command that touches a cloud account, a browser or a deployed
stack: the person reading the guide runs it, in their own environment, with their own
credentials. You read the tree; you never exercise it.

## Variables

- `$1` (optional) — branch name override. Default: `git branch --show-current`.

## Owned artifact (the only file this prompt may write)

`<implementation_results_dir>/<branch>/integration-test-guide.md`.

Do **not** modify implementation code, tests, specs, the roadmap, architecture docs, the
build-results document, or the summary written beside it.

## Inputs

1. `<implementation_results_dir>/<branch>/build-results.md` — read it **in full**. It is the
   recorded evidence for what changed and what was already verified, including every
   `unverified` row and the reason it could not be checked. If it does not exist, **stop and
   report it**: a guide built without it would describe work nobody recorded.
2. The task prompt at `paths.task_prompts_dir`/`<branch>-prompt.md` — for the problem the
   task solved, the surfaces it names, its acceptance criteria and its explicit non-goals.
   It is the authority on what a human should confirm by hand.
3. The branch's changed files — read-only `git` (`git diff --name-only`, `git status`) and
   reading those files themselves. They are the authority on which surfaces the change
   actually touches: a new subcommand, an existing script's new flag, a route, a UI screen.

Read-only orienting commands are fine: `git branch --show-current`, `git diff --name-only`,
`git status`, and reading the files above. Nothing else. If a fact cannot be established from
these, it goes in the guide as unconfirmed rather than as an invented detail.

## Instructions

Write `<implementation_results_dir>/<branch>/integration-test-guide.md` in exactly these four
sections, in this order. The heading wording is yours; the order and the content of each
section are not.

1. **What this guide covers.** One short paragraph: what change this procedure exercises, on
   which branch, and which surfaces it walks. Say plainly that it is a hand-run procedure and
   that nothing in it has been executed by the toolkit.
2. **Scenarios.** One scenario per surface the change actually touches, grouped by surface
   kind — the repo's existing tooling, custom CLI/TUI commands, browser UI flows, and external
   actions such as cloud-provider (for example AWS) commands. Cover only surfaces some
   changed file, build-results row or task-prompt statement points at; a surface with no such
   evidence does not belong here. Each scenario carries **all five** of these fields, in this
   order:
   1. **Prerequisites** — accounts, permissions, environment variables, fixtures, seed data,
      services or state that must exist before the first step.
   2. **Command(s) or steps** — the exact commands to run, or the exact clicks and inputs, in
      order. Quote a command only when it is confirmable in the changed files, the build
      results or the task prompt.
   3. **Expected observable result** — what the human should see: output text, exit status,
      an HTTP response, a rendered screen, a log line, a state change.
   4. **How to tell pass from fail** — the discriminating check, stated so a failure is
      distinguishable from a pass. "It works" is not a check.
   5. **Cost, permission or destructive warning** — any spend, credential scope, quota,
      irreversible write or teardown obligation, or the word `none` when the scenario truly
      has none. Never leave the field out.
3. **Teardown.** What the human must undo, delete, stop or revert after the scenarios so the
   environment is back to the state the guide found it in: branches, fixtures, deployed
   resources, local files, environment variables. If a scenario creates nothing, say so
   explicitly rather than dropping the section.
4. **Could not be exercised in this environment.** An honest list of what this guide cannot
   cover from a normal developer environment — a deployed stack, a production-only account, a
   paid service, hardware, a browser-only flow — each with the reason and, where it is
   knowable, the environment that would exercise it. This section is **mandatory**: a guide
   that claims complete coverage it cannot confirm is fabrication. If everything is
   exercisable, say so and name what still needs credentials or spend.

Rules for the whole document:

- **Traceable or absent.** Every scenario traces back to a changed file, a build-results row
  or the task prompt. Never invent a flag, subcommand, route, endpoint, URL, bucket, role,
  ARN, screen name or environment variable. A command you cannot confirm against the tree is
  reported as **unconfirmed**, with the reason, in the scenario's own step — never guessed,
  never silently replaced with something plausible.
- **Instruction voice, not results.** Write what a human should run and expect. Do not claim
  an outcome you did not observe.
- **No invented results.** Anything the build results mark `unverified` stays unverified in
  the guide, with its recorded reason. Never describe a fix, a pass or a successful run the
  build results do not record.
- **Stay within the docs.** Reference configuration by its `paths.*` key, never by a
  hardcoded directory that belongs to one repo.
- **Leave the tree alone.** Write the one owned file and nothing else.

## Non-goals — do NOT do these

- Do **not** run an integration test, a verification gate, a linter, a build or a test suite.
- Do **not** run any command that touches a cloud account, a browser, a deployed stack or a
  paid service. Read-only `git` and file inspection only.
- Do **not** touch implementation code, tests, specs, the roadmap, or architecture docs.
- Do **not** edit the build-results document or the summary; this prompt only reads the
  build results.
- Do **not** commit, push, or open a pull request (the delivery stage owns that).

## Done when

- `<implementation_results_dir>/<branch>/integration-test-guide.md` exists and contains the
  four sections above, in order, with no placeholder text.
- Every scenario carries all five fields, and the guide ends with the teardown section and the
  honest "could not be exercised" section.
- Every scenario traces to a changed file, a build-results row or the task prompt; every
  unconfirmable command is marked unconfirmed with its reason.
- No test, gate, cloud, browser or deployed-stack command was executed, and no code, test,
  spec, roadmap, architecture or build-results file was modified.

## Final response

Return: the path written, a one-line description of each of the four sections, the scenarios
you could not confirm against the tree (naming the command and why), and anything the build
results marked `unverified` that the guide therefore carries as unverified.
