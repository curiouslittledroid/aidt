# Fix task-prompt review findings

The task prompt under revision is `$1`.

Your first act is verification, not applying the reviewer's `Suggested fix`. Before making any edit,
verify the finding against the repository and the cited sources: the prompt under revision, its
roadmap entry, the spec sections it cites, and the files the finding names.

When the suggested fix is wrong or contradicts those sources, do not apply it:
make the correction the evidence supports and report the disagreement explicitly — which finding,
what the reviewer prescribed, what the evidence shows, and what you changed instead.

Never settle a material ambiguity. A finding that needs an owner decision (security, cost,
schema, data loss, hard-to-reverse) is never settled by guessing: state the options and stop,
leaving it a `Blocked` escalation.

Edit only `$1`. Do not implement the task the prompt describes, and do not change unrelated files.
