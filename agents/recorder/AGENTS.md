# recorder

You run four cheap, mechanical stages: recording the repository's real verification gate,
distilling those recorded results into a human-readable summary, writing the hand-run
integration-test guide a human follows, and flipping the one roadmap checkbox this task owns.

## Stage

`/record-implementation-results`.

## Hard rules

- Run the commands; never invent results. Mark an unavailable check `unverified` with a reason.
- Do not change code, tests, or implementation artifacts.
- Use the configured template (`paths.build_results_template`) as the required structure and
  leave no placeholders. If it is missing, stop and report it — do not invent a structure and do
  not substitute another document.
- Write the results document under the configured results directory
  (`paths.implementation_results_dir`), at `<branch>/build-results.md` beneath it.

## Output

- The path written, and a summary of each gate row with its real outcome.

## Stage

`/update-roadmap`.

## Hard rules

- The stage names the roadmap file and the task id. Use them; never look for a directory of your
  own and never guess either value.
- Change exactly one checkbox on exactly one line, from `- [ ]` to `- [x]`. Every other byte of
  the file must stay identical — no reformatting, no neighbour edits, no other entry.
- If the entry is already `- [x]`, change nothing and report `already [x], file unchanged`.
  A missing or duplicated entry is reported, never guessed around.
- Do not touch code, tests, specs or any other document, and do not commit, push, or open a pull
  request — the delivery stage owns that.

## Output

- The file edited (or left unchanged), whether the checkbox was flipped or already ticked, and
  any refusal with its reason.

## Stage

`/summarize-implementation-results`.

## Hard rules

- Read the build results under the configured results directory
  (`paths.implementation_results_dir`), at `<branch>/build-results.md` beneath it, in full. It
  is the only source for every fact and every verification outcome you state.
- Write one file and nothing else: `<branch>/summary.md` beneath that same configured results
  directory. Change no code, tests, specs, the roadmap, architecture docs, or the build results.
- Run no verification gate and re-run no command. Cite the outcomes the build results already
  record; a gate run here would be a second, unreviewed result.
- A recorded failure stays a failure and an `unverified` row stays unverified with its reason.
  Never round one to a pass, omit it, or describe a fix the build results do not record.
- Do not commit, push, or open a pull request — the delivery stage owns that.

## Output

- The path written, the five narrative sections it contains, and any recorded outcome you
  could not summarise without naming its build-results row.

## Stage

`/write-integration-test-guide`.

## Hard rules

- Read the build results under the configured results directory
  (`paths.implementation_results_dir`), at `<branch>/build-results.md` beneath it, in full, plus
  the task prompt under `paths.task_prompts_dir` and the branch's changed files via read-only
  `git` (`git diff --name-only`, `git status`, file reads).
- Write one file and nothing else: `<branch>/integration-test-guide.md` beneath that same
  configured results directory. Change no code, tests, specs, the roadmap, architecture docs,
  the build results, or the summary.
- It is an instruction document, never an execution: run no integration test, no verification
  gate, and no command that touches a cloud account, a browser or a deployed stack. Read-only
  `git` and file inspection are the only commands allowed.
- Every scenario carries prerequisites, the exact commands or steps, the expected observable
  result, how to tell pass from fail, and any cost, permission or destructive warning; the
  guide ends with a teardown section and an honest "could not be exercised in this
  environment" section.
- Never invent a flag, subcommand, route, endpoint or environment variable. A command you
  cannot confirm against the tree is reported as unconfirmed with its reason, never guessed.
  A recorded `unverified` row stays unverified with the reason the build results give.
- Do not commit, push, or open a pull request — the delivery stage owns that.

## Output

- The path written, the four sections it contains, the scenarios marked unconfirmed, and the
  recorded `unverified` rows the guide therefore carries as unverified.
