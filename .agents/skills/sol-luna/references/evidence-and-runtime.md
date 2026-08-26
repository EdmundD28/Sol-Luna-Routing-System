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
  --requested-effort max
```

The default output hashes the thread ID, session path, agent path, and working directory. It allowlists host fields from `session_meta` and `turn_context`, separates requested values from host-observed values, and reports missing or conflicting values as unknown.

Use `--require-identity` only when the task's acceptance criteria require host-observed `agent_role`, `model`, and `effort`. Use `--require-boundary` only when acceptance requires host-observed sandbox and permission-profile types. Unknown fields may be reported for ordinary reversible work; a mismatch between requested and host-observed values is always disclosed.

`--include-identifiers` creates a private diagnostic artifact. Never commit or publish that output.

## Evidence ledger

The ledger is opt-in and writes only to the explicit path supplied with `--ledger`. Prefer a repository-local ignored location such as `runtime/sol-luna/evidence.jsonl`.

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

The status gate requires at least five clean matched `SOL_ONLY` versus `SOL_LUNA` pairs with the same independent acceptance suite and a comparable token or credit source. It returns either `insufficient_evidence` or `eligible_for_human_review`. It never recommends a route, edits configuration, or enables automatic routing.

## Contract boundaries

- `ACCEPTED` requires independent acceptance bound to a named final candidate and acceptance suite.
- `FAILED` is an in-scope implementation, runtime, or verification failure.
- `BLOCKED` requires a concrete missing decision, authority, input, permission, ownership change, or external-state change.
- One repair is the default. More than one repair requires a short justification and a new evidence reference.
- Token and credit values require a source and uncertainty statement. A displayed allowance delta is not silently converted into exact credits.
- Raw prompts and arbitrary extra fields are rejected. Run references are hashed before append, and private filesystem paths are rejected from summary fields.
