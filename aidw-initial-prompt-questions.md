I've read docs/workflow.md, the four prompt clusters you'd wrap, AGENTS.md, the Pi CLI (pi --help), and the existing aidt/ (currently just                     
 software-factory-spec.md + empty aidw/ and agent-configs/). Before writing the design doc, I need to settle a set of decisions. I've put my recommended        
 default under each so you can just say "default" where you agree.                                                                                              
                                      
 Recon notes that shape the questions                                                                                       
 - Session state matters. review-findings-to-github.md says "use only the findings from the immediately preceding review in this pi session";                   
   update-traceability needs test names /test produced. So either stages share a Pi session (--session-id) or the wrapper passes artifacts as files. This is    
   the single biggest design fork.               
 - HITL conflicts with -p. Steps 10–11 (publish findings, approve follow-ups) explicitly require human confirmation. pi -p is non-interactive, so the wrapper   
   must own those pauses (or the prompts must be adapted).
 - Prompt variables. The prompts use $1 $2 $3 and are designed to be expanded by Pi's / template mechanism. Invoked from the CLI that expansion does not happen 
   automatically — the wrapper must render them.       
 - .pi/prompts is referenced widely (docs/workflow.md, architecture docs, conventions, other prompts, tests). Moving it is a repo-wide change, not a folder     
   rename.                                            
 - Toolchain: Python 3.14.7 present, PyYAML not installed; gh is installed and authenticated; Node 24 + pnpm.                                      
 ────────────────────────────────────────────────────────────────────────────────                                                                               
                             
 A. Scope and step grouping   

 A1. Confirm the four wrappers map to workflow stages like this?                                                                         
 - prompt → /task-prompt + /task-revie
 - implement → /impliment-task → /test → /update-traceability → /record-implementation-results → /update-architecture → /pr              
 - review → /code-review → (if findings) /review-findings-to-github → human gate → /approve-review-followups                             
 - fix → /fix-next-review-followup → /test → /code-review (loop until approved)                                                                    
 Default: yes, exactly that.                                                                                                             
 A2. Is /integration-tests (workflow Step 8) in scope for v1? It needs a deployed dev stack and is the messiest dependency.              
                     
 Default: out of scope for v1, but leave a hook/subcommand stub. (Note the existing prompt is misnamed integration-tests.md and requires 
 post-CI deployment.)                                                                                                                    
 A3. Are /show-updated-player-actions and /show-updated-integration-tests in scope?                                                                      
 Default: out of scope.                                                                                                                   
 A4. Should each wrapper be one end-to-end orchestrator, or atomic per-stage commands plus a thin orchestrator on top?                   
                     
 Default: both — atomic stage commands (resumable) plus a chain command per group.                                                       
             
 A5. Should a group be resumable after failure (state file recording which stage completed, --from <stage>/--resume)?                    
                
 Default: yes — run state persisted under aidt/runs/<run-id>/state.json.                                                    

 
 B. Pi invocation and session model
               
 B1. How should artifacts pass between stages of the same group: a shared Pi session (--session-id) or explicit artifact files           
 produced/consumed by the wrapper (and a fresh session per stage)?                                                               
 Default: hybrid — authoring-adjacent stages within one agent (e.g. implement → traceability → architecture) share one session; each     
 reviewer/independent agent gets a fresh session; cross-agent handoffs go through files (findings manifest, PR number, task-prompt       
 path). Reason: workflow requires author ≠ judge, and the existing publisher/runner scripts already expect file manifests.               


 B2. Given that, how do we satisfy the "same session" expectations baked into review-findings-to-github and update-traceability?         
 Options: (a) run those stages in the same session as their predecessor, (b) modify the prompts in aidt/prompts to read a                
 wrapper-written artifact instead of session memory.                                                                       
 Default: (b) for the review cluster (extract findings to a manifest), (a) for update-traceability (same session as implementation       
 agent).                                                  


 B3. Should Pi run in --mode json and the wrapper tee/parse it, or plain -p text captured to a log?                                      
                     
 Default: --mode json, log raw JSONL to the run dir, and parse the final assistant message for verdicts (Approve / Request changes /     
 Blocked) and artifacts; also emit a human-readable transcript.                                                                                                                            
 B4. Non-interactive defaults to apply to every invocation: -p --approve --no-session (or session per B1), plus per-agent --provider,    
 --model, --thinking, --tools/--exclude-tools, --system-prompt/--append-system-prompt, --extension, --skill, --prompt-template,          
 --mcp-config? Anything to add or forbid?                                                                  
 Default: those, with --approve always on (project is trusted), --no-context-files opt-in per agent (see C2), and no --continue.         
                                                                                                                                         
 B5. Should each run have a wall-clock timeout and an optional cost/turn ceiling, aborting the stage if exceeded?                        
     
 Default: yes — timeout always (per-agent config), cost ceiling optional.                                                                                                                              
 C. Agent configs 


 C1. Proposed YAML schema — confirm fields (and say if any are missing):

 ```yaml                                                                                                                                 
   id: implementer                                                                                                                       
   description: ...                                                                                                                      
   provider: openrouter                                                                                                                  
   model: <provider/model>                                                                                                               
   thinking: medium                                                                                                                      
   system_prompt:            # replaces pi's default prompt                                                                              
     mode: override          # override | append | none                                                                                  
     file: ...                                                                                                                           
   agents_md: aidt/agents/implementer/AGENTS.md   # per-agent context file                                                               
   tools:                    # allowlist                                                                                                 
     allow: [...]                                                                                                                        
     deny: [...]                                                                                                                         
   skills: [...]                                                                                                                         
   extensions: [...]                                                                                                                     
   prompt_templates: aidt/prompts                                                                                                        
   mcp_config: .mcp.json                                                                                                                 
   cwd: <repo root>                                                                                                                      
   env: {}                                                                                                                               
   session: fresh            # fresh | continue | shared-with:<agent>                                                                    
   timeout_seconds: 3600                                                                                                                 
   max_cost_usd: null                                                                                                                    
   output: json                                                                                                                          
 ```                                                      
 
 Default: this schema. Note --tools is an allowlist and --exclude-tools a denylist — decide whether agents express allow, deny, or both. 
                                                                                                                                         
 C2. How is a custom AGENTS.md applied? Pi discovers context files by walking up from cwd, so to use a per-agent file we likely run with 
 --no-context-files and --append-system-prompt <file contents>, with cwd = repo root.                                                    
               
 Default: per-agent dir (aidt/agents/<id>/AGENTS.md); wrapper inlines it via --append-system-prompt. Confirm Pi's --append-system-prompt 
  accepts a file path vs literal text — I'll verify during implementation.                                                               
    
 C3. Which agents override Pi's system prompt entirely vs append? (e.g. reviewer might want a strict read-only judge prompt.)            
               
 Default: all agents use append so Pi's tool-safety prompt remains; override supported but unused in v1.                                 
                                                                   
 C4. Tool access policy per agent — give me the intended allow/deny sets. My proposed baseline:                                          
 - task-author: read, bash, write, edit                                                                                                  
 - task-reviewer, code-reviewer: read, bash (read-only; no write/edit)                                                                   
 - implementer, fixer: read, bash, write, edit                                                                                           
 - publisher/approver: bash only (delegates to the TS scripts)                                                                           
 - tester: read, bash, write, edit (writes tests)                                                                  
 Default: as above. Do you want deny-by-default with explicit allow?                                                                                                                         
 C5. Should the loader enforce the workflow rule "reviewer model ≠ implementation model" (warn vs hard-fail), and should it enforce      
 read-only tools for reviewers as a hard gate rather than trusting the model?                                                            
 Default: warn by default, --strict hard-fails on model collision; wrapper itself does not enforce tool restrictions beyond passing      
 flags.                                                                                                                       
 C6. Concrete model choices: do you want to name them now, or should I enumerate via pi list-models and propose mappings per the role    
 table (author / reviewer-A / reviewer-B / cheap-mechanical)? If you have opinions, give provider+model slugs.                           
            
 Default: I enumerate and propose; configs ship with placeholder IDs you edit.                                                           
                                                                                                                                         
 D. Prompts
 
 D1. Move .pi/prompts → ./aidt/prompts, leave it in place, or keep canonical + thin aidt overlay?                                        
          
 Default: keep .pi/prompts canonical for repo compatibility (docs/workflow.md and many docs reference it), and have aidt/prompts contain 
 only toolkit-specific additions/overrides (e.g. artifact-driven variants, rendered templates). This avoids a repo-wide reference churn  
 PR.                                                                                                                              
 D2. How should the wrapper render prompt variables ($1…$n) and include file contents referenced by a prompt?                            
               
 Default: wrapper reads the prompt file, substitutes positional args, resolves @path/explicit include directives itself, and passes the  
 rendered text as the message to pi -p (via stdin). No reliance on Pi / expansion.                                                                                                        

 D3. May the wrapper patch/copy prompts to be automation-friendly, or must the originals be treated as immutable source of truth?        
                     
 Default: originals immutable; any automation adaptations live as separate files in aidt/prompts/ with a clear header noting the         
 divergence, and the design doc lists each divergence.                                                                                                                     
 D4. Which directory should Pi treat as the working repo root (cwd) — the Mythical Forge root, or aidt/?                                 
                                                           Default: Mythical Forge root, with aidt/ paths passed absolute/relative to it.                                                          
                                                                                                                                         
 E. Human-in-the-loop and safety


 E1. Confirm the pause points: (1) after /task-review before implementing, (2) before publishing review issues to GitHub, (3) after      
 issues are published before approving fixes, (4) before /pr pushes/opens (optional).                                                    
          
 Default: all four; (1) and (4) skippable with --yes.                                                                                                                         
 E2. For (2)/(3), does the wrapper present a diff/summary on the TTY and take y/n, then invoke the agent/prompt non-interactively only   
 after approval? That is the cleanest way to keep -p.                                                                    
 Default: yes — wrapper owns the gate, the Pi stage runs only after approval; --dry-run shows the action without executing.              
                                                                                                                                         
 E3. GitHub writes: strictly reuse the existing TS scripts (publish-review-followups.ts, review-followup.ts) rather than reimplementing  
 gh logic in Python?                                                            
 Default: yes — Python wrapper only orchestrates and calls them; no duplicate GitHub logic.                                              
                                                                                                                                         
 E4. Git safety rules the wrapper must enforce: refuse on dirty tree (except within an active run), refuse on main for implement/fix,    
 never force-push, never merge, never reset --hard. Confirm, and whether to support git worktree per run.                                
                                                           Default: enforce the refusals; no worktree in v1.                                                                                                                                    
 E5. Secrets: API keys via existing env/pi auth; and load optional local overrides from a gitignored aidt/.env.local? Anything else      
 needed (AWS profile, GH_TOKEN)?                                                             
 Default: inherit env; optionally source aidt/.env.local; never commit secrets; add to .gitignore.                                       


 E6. Should a wrapper ever auto-retry a failed stage? If so, how many times and only for which failure classes (e.g. transient           
 pi/network vs gate failure)?                                                            
 Default: no auto-retry for gate failures; one retry for clearly transient invocation errors, configurable.                              
                                                                                                                                         
 F. Tooling and UX
 
 
 F1. Python dependency policy: stdlib-only, or a managed project (pyproject.toml + uv) allowing PyYAML, typer/click, rich? PyYAML is     
 currently absent.                                                              
 Default: pyproject.toml managed by uv, deps limited to pyyaml + typer; rich optional; keep it runnable via uv run. If you'd rather      
 zero-install, I can write a minimal YAML subset parser.                                                                                                                     
 F2. CLI shape and names — confirm:                                                             
 ```                 
   aidw prompt    <phase> <epic> <task>                                                                                                  
   aidw implement <task-prompt-path> [--yes]                                                                                             
   aidw review    --pr <n> [--dry-run]                                                                                                   
   aidw fix       --pr <n>                                                                                                               
   aidw tasks     [--phase 03] [--todo]                                                                                                  
   aidw run       <group> ...          # orchestrator                                                                                    
   aidw doctor                          # validate env/config                                                                            
 ```                                                               
 Default: these names; aidw is a single dispatcher in aidt/aidw/.


 F3. Run artifacts layout — aidt/runs/<utc-timestamp>-<task-or-pr>/ containing state.json, per-stage logs (JSONL + human), rendered      
 prompts, findings manifests, session IDs, cost/usage. Gitignored?                                                    
 Default: yes, gitignore aidt/runs/; also gitignore aidt/.env.local.                                                   


 F4. Roadmap selection (aidw tasks): parse docs/tasks/*.md checkboxes, show unchecked tasks with phase/epic/id, dependencies, and "Done  
 when"; support filtering. In v1 or later?                                                   

 Default: v1 basic listing; dependency-graph awareness later.                                                   


 F5. Testing the toolkit: pytest + unit tests under aidt/tests/, runnable via uv run pytest; not wired into the app's pnpm CI.           
 Acceptable? Should CI run them at all?                                                                      
 Default: pytest locally; not in app CI for v1.                                                                                                                
 F6. Must the toolkit run from any cwd (auto-detect repo root via git) and use absolute paths internally?                                
      
 Default: yes.                                                     
 
                                                         
 F7. Naming for the docs: what do aidt and aidw stand for? (I'll title the design doc accordingly.)               