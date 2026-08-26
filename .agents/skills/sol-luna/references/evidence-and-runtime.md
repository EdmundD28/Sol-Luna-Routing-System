# Runtime and Evidence Tools

Read this reference only when runtime identity or boundary evidence is material to acceptance, or when the user explicitly requests a persistent evidence ledger or a routing comparison. Ordinary Sol-Luna work should keep the compact receipt and metrics in the task report without running these scripts.

## Runtime receipt

`scripts/runtime_receipt.py` reads one explicitly supplied Codex session JSONL. It never chooses the globally newest session and never treats worker prose as runtime proof.

```powershell
python .agents/skills/sol-luna/scripts/runtime_receipt.py `
  --session C:\explicit\rollout.jsonl `
  --thread-id THREAD_ID `
  --requested-agent luna_worker `
  --requested-model gpt-5.6-luna `
  --requested-effort xhigh `
  --expected-sandbox workspace-write `
  --expected-permission-profile managed `
  --require-identity `
  --require-boundary
```

The default output hashes the thread ID, session path, agent path, and working directory. It allowlists host fields from `session_meta` and `turn_context`, separates requested values from host-observed values, and reports missing or conflicting values as unknown.

Use `--require-identity` only when acceptance requires host-observed `agent_role`, `model`, and `effort`; strict mode also requires all three requested values so presence cannot masquerade as compliance. Use `--require-boundary` only with both expected sandbox and permission-profile values. Strict boundary mode compares them with host-observed values rather than merely checking that fields exist. Live parent overrides can still change a custom agent's effective boundary, so the receipt reports what the host recorded.

`--include-identifiers` creates a private diagnostic artifact. Never commit or publish that output.

## Evidence ledger

The ledger is opt-in and writes only to the explicit path supplied with `--ledger`. Prefer a repository-local ignored location such as `runtime/sol-luna/evidence.jsonl`. Appends use a process lock, an OS file lock, duplicate record IDs, and atomic replacement.

Create a fill-in record:

```powershell
python .agents/skills/sol-luna/scripts/evidence_ledger.py template
```

Validate and append a prepared record:

```powershell
python .agents/skills/sol-luna/scripts/evidence_ledger.py append `
  --ledger runtime/sol-luna/evidence.jsonl `
  --record runtime/sol-luna/run-record.json
```

Validate the ledger:

```powershell
python .agents/skills/sol-luna/scripts/evidence_ledger.py validate `
  --ledger runtime/sol-luna/evidence.jsonl
```

Assess whether one task family has enough matched evidence for human review:

```powershell
python .agents/skills/sol-luna/scripts/evidence_ledger.py status `
  --ledger runtime/sol-luna/evidence.jsonl `
  --task-family bounded-feature
```

The status gate requires at least five fully assessed matched `SOL_ONLY` versus `SOL_LUNA` pairs inside one exact cohort: independent acceptance suite, policy fingerprint, metric kind, measurement source, and uncertainty basis. Failed arms remain in the cohort and count against independent acceptance, final-defect, and first-pass gates; they are never discarded to make the route look cleaner. Token and credit cohorts never share a readiness count. When both are recorded, exact credits take comparison precedence over diagnostic tokens. Only exact credit cohorts—not estimates, token cohorts, or displayed allowance deltas—can satisfy the savings gate. The default first-pass floor is 80%. It returns either `insufficient_evidence` or `eligible_for_human_review`; success gates also expose paired reduction, elapsed regression, acceptance and defect rates, first-pass acceptance, and the Sol planning/review share. It never edits routing.

## Matched evaluation

Create and freeze a campaign plan:

```powershell
python .agents/skills/sol-luna/scripts/matched_eval.py template
python .agents/skills/sol-luna/scripts/matched_eval.py validate --plan runtime/sol-luna/plan.json
python .agents/skills/sol-luna/scripts/matched_eval.py run-sheet --plan runtime/sol-luna/plan.json
```

Each pair produces `SOL_ONLY` and `SOL_LUNA` arms bound to the same starting candidate, task-spec digest, independent acceptance-suite digest, and policy fingerprint. The run sheet counterbalances arm order across pairs to reduce systematic order bias. Execute each arm in a fresh checkout or worktree, append its phase-aware matched record, then assess:

```powershell
python .agents/skills/sol-luna/scripts/matched_eval.py assess `
  --plan runtime/sol-luna/plan.json `
  --ledger runtime/sol-luna/evidence.jsonl
```

## Native lifecycle receipt

Deterministic lifecycle replay is not native proof. A real runner may write a private, redacted receipt and validate it with:

```powershell
python .agents/skills/sol-luna/scripts/native_lifecycle_receipt.py `
  --input runtime/sol-luna/native-lifecycle.json
```

The validator requires host-observed identity and boundary values to equal the request, explicit custom-profile loading, redacted child references, real delegation, a running child interrupted at deadline, same-child continuation, stale-evidence rejection after a candidate change, exactly one passed focused repair, and zero writer dispatch when ownership conflicts. It cannot create those facts; a native runner must observe them.

The harness freezes and validates comparability but deliberately does not launch paid model work or change routing automatically.

## Contract boundaries

- `ACCEPTED` requires independent acceptance bound to a named final candidate and acceptance suite.
- `FAILED` is an in-scope implementation, runtime, or verification failure.
- `BLOCKED` requires a concrete missing decision, authority, input, permission, ownership change, or external-state change.
- One repair is the default. More than one repair requires a short justification and a new evidence reference.
- Token and credit values require a source and uncertainty statement. A displayed allowance delta is not silently converted into exact credits.
- Matched records identify `sol_execution` for the control arm and `sol_planning`, `luna_execution`, `sol_review`, `repair`, and `integration` for the delegated arm. `elapsed_seconds` is wall-clock duration; individual active-phase durations may overlap but none may exceed the run boundary. Token and credit phase totals remain additive and must reconcile with their recorded totals.
- Matched evidence is invalid unless host-observed runtime identity proves Sol is `gpt-5.6-sol` and every delegated Luna execution is `gpt-5.6-luna`. Agent names, profile labels, prompts, and requested settings are not runtime proof.
- Raw prompts and arbitrary extra fields are rejected. Run references are hashed before append, and private filesystem paths are rejected from summary fields.
