# Generate a manual test plan + executable test scripts

Based on the work just completed in this session, generate a step-by-step manual test plan and a companion set of executable bash scripts, all saved to a directory under `manual-test-plans/`.

## Instructions

1. Determine the current git branch name with `git branch --show-current`.
2. Review the task prompt that was just implemented (likely in `docs/task-prompts/<branch-name>-prompt.md`), along with any spec sections it cited, the implemented code, and the conversation context.
3. Create a directory `manual-test-plans/<branch-name>/`.
4. Write a comprehensive manual test plan (`manual-test-plans/<branch-name>/testplan.md`) covering:
   - **Prerequisites** — what must be deployed or configured before testing (specific `cdk deploy` commands, env vars, CLI profile setup).
   - **Read-only smoke tests** — verify infrastructure exists and is configured correctly.
   - **Happy-path tests** — core functionality works end to end.
   - **Error-path tests** — edge cases, failure modes, boundary conditions.
   - **Observability checks** — verify logs/metrics confirm behavior.
   - **Cleanup** — commands to tear down all test resources.
   - For every CLI command, show the **expected** output or behavior.
5. Generate a set of executable bash scripts in `manual-test-plans/<branch-name>/scripts/` that automate the test plan. Follow the conventions below.

## Script conventions

### Naming and structure

| Script | Purpose |
|--------|---------|
| `00-env.sh` | Fetches stack outputs, exports env vars. Designed to be `source`-d. |
| `01-verify-config.sh` | Read-only smoke tests with pass/fail assertions. |
| `02-test-*-happy.sh` | Happy-path automated test. |
| `03-test-*-error.sh` | Error-path automated test. |
| `04-setup-*.sh` | Any manual/interactive setup step (e.g., MFA enrollment). |
| `05-verify-*.sh` | Verification after manual/interactive setup. |
| `06-cleanup.sh` | Deletes all test resources. |
| `run-all.sh` | Master runner that calls scripts in order. |

### Shell scripting rules

- **Shebang:** `#!/usr/bin/env bash`
- **Strict mode:** `set -euo pipefail` at the top of every script.
- **Syntax:** Every script must pass `bash -n <script>` without errors before you deliver it.
- **Color helpers:** Define `red()` and `green()` functions for pass/fail output.
- **Self-containment:** Each script declares its own dependencies with a `require()` helper. Do not assume the caller sourced env vars unless the script explicitly requires `00-env.sh`.
- **`00-env.sh` variables:** All variables in `00-env.sh` must be `export`-ed so child scripts inherit them. Use `export VAR="${VAR:-default}"` to allow caller overrides. If a shell variable in a test script needs an env var from `00-env.sh`, assert it exists at the top with `[[ -n "${VAR:-}" ]] || { red "source 00-env.sh first"; exit 1; }`.
- **Error capture with AWS CLI v2:** AWS CLI v2 writes errors to stderr. Capture both streams with `2>&1`, store exit code, and handle `jq`-parseable JSON failures vs plain-text error messages. Always check `$EXIT_CODE` first, then try jq, then fall back to raw text grep on the combined output.

### Cognito / CDK / AWS-specific patterns

- **`admin-initiate-auth`** is the recommended auth API for test scripts (not `initiate-auth`), because it works with IAM credentials and doesn't require client-level auth flows to be enabled. If the app client doesn't have `adminUserPassword: true`, note in the test plan that this must be enabled first.
- **Cognito Hosted UI domain:** CDK's `UserPoolDomain.domainName` may return only the prefix (e.g., `mythical-forge-dev`) rather than the FQDN. Always construct the full URL defensively: check for `amazoncognito.com` in the value; if absent, append `.auth.<region>.amazoncognito.com`.
- **CDK logical ID suffixes:** CDK appends random hash suffixes to logical IDs (e.g., `PreAuthLambdaABC54786`). When querying stack resources by logical ID, use `jq` with `startswith` instead of `--query` with exact JMESPath equality.
- **Cognito `describe-user-pool` gaps:** Some fields (`EnabledMfas`) only populate after a user enrolls MFA, even though the CFN template asserts them. Script assertions must allow null/empty for these fields.
- **jq defensiveness:** Always use `// {}`, `// []`, or `// "UNKNOWN"` defaults with jq to handle null API responses gracefully. Prefer `jq -r '(.field // {}) | keys | join(",")'` over `jq -r '.field | keys | join(",")'`.
- **IAM permissions for Lambda tests:** If the Lambda calls Cognito Admin APIs (`AdminListGroupsForUser`, `AdminGetUser`), the script should verify the Lambda's IAM role permits those actions, not just the Lambda's existence.
- **Secrets Manager placeholders:** If the stack creates Secrets Manager secrets with placeholder values, the scripts should note this in prerequisites and not attempt to validate secret contents.

### User interaction

- If a step requires manual input (TOTP code, browser interaction, etc.), the script should:
  1. Perform all automated setup before the manual step.
  2. Display clear instructions with exact URLs, credentials, and expected actions.
  3. Prompt the user with `read -r -p` for input, validating format where possible.
  4. Resume automated flow after the input.
- Prefer API-driven flows over browser flows whenever Cognito's Admin API supports it (e.g., `associate-software-token` + `verify-software-token` instead of Hosted UI MFA enrollment).
- If a browser is unavoidable, generate the exact URL with properly encoded query parameters using `python3 -c "import urllib.parse; print(urllib.parse.quote(...))"`).

### Environment variables

All scripts should accept overrides via environment variables. Document the defaults:

```bash
export STACK_NAME="${STACK_NAME:-<stack-name>}"
export AWS_PROFILE="${AWS_PROFILE:-dev}"
export REGION="${AWS_REGION:-ap-southeast-2}"
```

### Deliverables checklist

- [ ] `manual-test-plans/<branch-name>/testplan.md` — human-readable test plan.
- [ ] `manual-test-plans/<branch-name>/scripts/00-env.sh` — environment setup (source-able).
- [ ] `manual-test-plans/<branch-name>/scripts/01-verify-config.sh` — read-only smoke tests.
- [ ] `manual-test-plans/<branch-name>/scripts/0N-test-*.sh` — automated test scripts (one per test scenario).
- [ ] `manual-test-plans/<branch-name>/scripts/0N-setup-*.sh` — any interactive setup scripts.
- [ ] `manual-test-plans/<branch-name>/scripts/0N-verify-*.sh` — post-setup verification scripts.
- [ ] `manual-test-plans/<branch-name>/scripts/99-cleanup.sh` — resource teardown.
- [ ] `manual-test-plans/<branch-name>/scripts/run-all.sh` — master runner.
- [ ] All scripts pass `bash -n` syntax check.
- [ ] All scripts are `chmod +x`.

## After writing

- Verify every script passes `bash -n <script>`.
- Return the path to the test plan directory and a one-line summary of what it covers.
- If the test plan references any prerequisite changes to deployed infrastructure (e.g., enabling `adminUserPassword` on a Cognito client, adding an IAM permission), call them out explicitly at the top of the plan.