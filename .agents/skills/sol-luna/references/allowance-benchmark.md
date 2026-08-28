# Included-Allowance Benchmark

Use this protocol only when the task is to quantify Sol-only versus Sol-Luna subscription usage. The user-visible plan meters are authoritative for this question; diagnostic tokens and purchased-credit estimates are secondary explanations.

## Freeze the comparison

- Use one account, plan, speed setting, formal repository checkout, task family, starting Git reference, task specification, independent acceptance suite, and Sol-Luna revision. Freeze their digests in the campaign `init` event.
- Give Sol-only one complete top-level task in one Sol run. Sol may naturally decompose its own work, but the experiment controller must not turn it into separately dispatched or artificially serialized packages. In the Sol-Luna arm, give its Sol controller that same complete task and measure the controller's full route interval, including every Luna child it launches.
- Freeze the Sol-Luna worker count and active Luna-writer count in the campaign `init` event. The defaults are one worker and one active writer, but a pre-registered campaign may use any `worker_count >= 1` and `1 <= active_luna_writer_count <= worker_count`. Keep the topology label alongside those counts. Record delegated coverage separately from active concurrency; concurrency is a frozen treatment parameter, never an optimization target.
- Store the campaign ledger and dashboard captures outside the repository. Do not create a clone, copied project, or worktree.
- Pre-register the route order, pair count, batch size, quality gate, time gate, and minimum allowance advantage. A production campaign requires at least five pairs; for the first v0.1.1 campaign, test a conservative lower bound of at least 10×.
- Run counterbalanced pairs. Five pairs with a 3/2 first-arm split are the minimum production campaign; use more pairs when the meter remains too coarse.

## Read the meters

Measure only the route task interval: retain a settled dashboard reading immediately before launching the tested task and another immediately after that task returns. Route elapsed time uses the same boundaries. Do not include the experiment controller's independent acceptance, commit, branch restoration, dashboard-settlement wait, or between-arm preparation in either route. Run the same independent acceptance after both route results exist and report that referee cost separately.

Before the next route, finish referee and repository preparation, then take a fresh starting reading. The two route intervals therefore need not be percentage-continuous. They must remain in the same window, must not overlap, and the later reading must not increase. Report any consumption in the excluded between-arm gap instead of assigning it to either route. Stop and invalidate an affected arm if either window resets, another shared-pool task runs during that arm, or the plan or speed changes.

The five-hour meter is primary because its smaller allowance window usually magnifies the same usage into a larger percentage change. The weekly meter is a separate, coarser corroborating view of the same shared usage. Never add the two percentages or infer one window's hidden capacity from the other without calibration.

Within one unchanged meter, the hidden capacity cancels:

```text
allowance advantage = Sol-only percentage-point consumption / Sol-Luna percentage-point consumption
```

Use `allowance_campaign.py` to create and recover the append-only campaign ledger. It generates records accepted directly by `allowance_meter.validate_record()` and passes completed records to `allowance_meter.assess()`. If integer display resolution makes the denominator indistinguishable from zero or the conservative lower bound misses the pre-registered threshold, enlarge the matched batch within the quota budget or report `HOLD`; do not manufacture precision.

## Record the campaign

Keep the ledger and evidence captures outside the repository. Initialization is exclusive and refuses an existing ledger:

```powershell
python .agents/skills/sol-luna/scripts/allowance_campaign.py init `
  --ledger C:\benchmark\campaign.jsonl `
  --contract-digest sha256:0000000000000000000000000000000000000000000000000000000000000000 `
  --usage-scope-digest sha256:1111111111111111111111111111111111111111111111111111111111111111 `
  --task-family bounded-feature `
  --batch-size 1 `
  --reading-uncertainty 1 `
  --first-routes SOL_ONLY,SOL_LUNA,SOL_LUNA,SOL_ONLY,SOL_ONLY `
  --starting-commit-sha 0123456789abcdef0123456789abcdef01234567 `
  --task-spec-digest sha256:2222222222222222222222222222222222222222222222222222222222222222 `
  --acceptance-suite-digest sha256:3333333333333333333333333333333333333333333333333333333333333333 `
  --sol-luna-worker-count 1 --sol-luna-active-luna-writer-count 1 `
  --target-elapsed-min-seconds 1200 --target-elapsed-max-seconds 2400 `
  --meter-resolution-percentage-points 1 `
  --repair-policy-digest sha256:4444444444444444444444444444444444444444444444444444444444444444 `
  --five-hour-window-id five-hour-001 `
  --five-hour-reset-at 2026-08-28T12:00:00+10:00 `
  --weekly-window-id weekly-001 `
  --weekly-reset-at 2026-09-01T00:00:00+10:00
```

Immediately before launching an arm, take settled readings and record them. The command derives the pair and position from the registered order. Readings must be integer multiples of the frozen meter resolution; an out-of-band or reset reading invalidates the campaign:

```powershell
python .agents/skills/sol-luna/scripts/allowance_campaign.py begin-arm `
  --ledger C:\benchmark\campaign.jsonl `
  --route SOL_ONLY --route-revision v0.1.1 `
  --observed-at 2026-08-28T09:00:00+10:00 `
  --five-hour-remaining-percent 100 --weekly-remaining-percent 100 `
  --start-evidence-digest sha256:2222222222222222222222222222222222222222222222222222222222222222
```

End the interval as soon as the tested Agent returns. `--elapsed-seconds` covers only that route interval and is formally comparable only inside the frozen 1200–2400 second target. The route end records only the candidate digest and settled meter reading. Then run the independent acceptance outside the route interval and append a `record-acceptance` event before beginning the next arm. That event binds the candidate digest, acceptance command/result/suite digests, observation time, referee elapsed time, and `PASSED`/`FAILED` plus defects. Referee time is part of the excluded between-arm gap and is never assigned to either route. Assessment refuses a pending route end or any missing acceptance event.

```powershell
python .agents/skills/sol-luna/scripts/allowance_campaign.py end-arm `
  --ledger C:\benchmark\campaign.jsonl `
  --pair-id pair-001 --route SOL_ONLY --observed-at 2026-08-28T09:10:00+10:00 `
  --five-hour-remaining-percent 92 --weekly-remaining-percent 99 `
  --end-evidence-digest sha256:3333333333333333333333333333333333333333333333333333333333333333 `
  --elapsed-seconds 1500 `
  --candidate-digest sha256:5555555555555555555555555555555555555555555555555555555555555555
```

Then append the independent referee result:

```powershell
python .agents/skills/sol-luna/scripts/allowance_campaign.py record-acceptance `
  --ledger C:\benchmark\campaign.jsonl --pair-id pair-001 --route SOL_ONLY `
  --candidate-digest sha256:5555555555555555555555555555555555555555555555555555555555555555 `
  --acceptance-command-digest sha256:6666666666666666666666666666666666666666666666666666666666666666 `
  --acceptance-result-digest sha256:7777777777777777777777777777777777777777777777777777777777777777 `
  --acceptance-suite-digest sha256:3333333333333333333333333333333333333333333333333333333333333333 `
  --observed-at 2026-08-28T09:12:00+10:00 --acceptance-elapsed-seconds 120 `
  --independent-acceptance PASSED --defects 0
```

`status` is lock-free and read-only. It reports the active arm, next route, last readings, completed pairs, and cumulative excluded controller/referee consumption for each window. `assess` refuses an active arm and keeps five-hour and weekly results separate:

```powershell
python .agents/skills/sol-luna/scripts/allowance_campaign.py status --ledger C:\benchmark\campaign.jsonl
python .agents/skills/sol-luna/scripts/allowance_campaign.py assess `
  --ledger C:\benchmark\campaign.jsonl `
  --minimum-advantage-multiple 10 --minimum-pairs 5
```

Every ledger event is compact, sorted-key UTF-8 JSONL and links to the SHA-256 of the preceding canonical event. Before every write, the complete history is replayed semantically. Writers use an `O_EXCL` `.lock`, a flushed and `fsync`-ed same-directory temporary file, and `os.replace`; a foreign lock is never removed. A reset boundary, time reversal, wrong route, increased reading, damaged chain, unsupported field, or record inconsistent with its begin/end evidence fails closed.

## Bind host-observed identities

After generating strict `runtime_receipt.py` receipts, create a manifest with exactly one `SOL_ONLY` and one `SOL_LUNA` run per pair. Receipt paths are relative to the manifest directory:

```json
{
  "schema_version": 2,
  "campaign_id": "campaign-001",
  "sol_luna_effort": "medium",
  "sol_luna_writer_count": 1,
  "runs": [
    {
      "pair_id": "pair-001",
      "route": "SOL_ONLY",
      "controller_receipt": "receipts/sol-only.json",
      "worker_receipts": []
    },
    {
      "pair_id": "pair-001",
      "route": "SOL_LUNA",
      "controller_receipt": "receipts/controller.json",
      "worker_receipts": ["receipts/luna-a.json"]
    }
  ]
}
```

Build the immutable index once:

```powershell
python .agents/skills/sol-luna/scripts/benchmark_identity.py build `
  --manifest C:\benchmark\manifest.json `
  --output C:\benchmark\identity-index.json
```

The builder requires verified, fully readable explicit-session receipts with host-observed model, reasoning effort, role, and provider. `SOL_ONLY` is exactly one OpenAI `gpt-5.6-sol/high` controller and no worker. `SOL_LUNA` uses the same controller plus the campaign's frozen worker/writer topology; every Sol-Luna arm in one campaign must use the same shape and effort. A logical receipt cannot be reused anywhere in the campaign, even when whitespace, indentation, or JSON key order differs. Absolute paths, drive paths, traversal, control characters, Windows device names, symlinks, missing routes, role/model/effort impersonation, self-report proof, unknown fields, and an existing output fail closed.

The output allowlist contains only the campaign and pair identifiers, declared Luna effort and writer count, route, redacted controller/writer identity values, receipt SHA-256 values, verification status, schema version, and a SHA-256 over the canonical index without that digest field. Each `receipt_sha256` is computed over the parsed receipt's sorted-key, compact canonical JSON, so it is stable across equivalent serializations. The index never copies receipt paths, source/thread references, working directories, or agent paths. Output uses a same-directory flushed and `fsync`-ed temporary file followed by `os.replace`.

## Build the structural attestation

After every registered arm is complete, bind the campaign ledger and identity index to the frozen benchmark contract:

```powershell
python .agents/skills/sol-luna/scripts/benchmark_attestation.py build `
  --campaign-ledger C:\benchmark\campaign.jsonl `
  --identity-index C:\benchmark\identity-index.json `
  --contract C:\benchmark\contract.json `
  --output C:\benchmark\attestation.json
```

The contract is a strict schema-2 JSON object declaring the campaign ID, route revision, expected pair and batch counts, Luna effort, total worker pool, maximum active Luna writers, both topology labels, and the benchmark-contract, task-spec, acceptance-suite, and policy SHA-256 values. The builder replays the authoritative campaign ledger, requires a complete zero-defect accepted campaign with unchanged meter windows, verifies the identity-index digest and exact pair/route membership, and checks host-observed OpenAI `gpt-5.6-sol/high` controllers plus the declared OpenAI `gpt-5.6-luna` workers. Identity receipts prove participation, while the frozen campaign fields separately preserve the active-writer treatment. Inputs must be regular non-symlink files. The output parent must already be a directory, the output must not exist or alias an input, and the builder writes atomically without including paths, timestamps, session references, prompts, or notes. Its attestation proves structural coherence only; use `allowance_meter.py` to decide the economic threshold.

## Accept or hold

Call the campaign a pass only when independent acceptance is equal, defects do not increase, total Sol-Luna elapsed time is strictly lower, the five-hour conservative aggregate advantage reaches the declared threshold, weekly evidence does not contradict the direction, and the arm order is counterbalanced. Report the displayed ratio and uncertainty interval, both meters separately, all failures and repairs, and any contamination boundary.

The official per-model rate card can estimate purchased credits from complete classified phase usage. It does not reveal the capacity behind a personal plan's five-hour or weekly percentage and cannot replace the account-meter result.
