# Included-Allowance Benchmark

Use this protocol only when the task is to quantify Sol-only versus Sol-Luna subscription usage. The user-visible plan meters are authoritative for this question; diagnostic tokens and purchased-credit estimates are secondary explanations.

## Freeze the comparison

- Use one account, plan, speed setting, formal repository checkout, task family, starting Git reference, task specification, independent acceptance suite, and Sol-Luna revision.
- Give Sol-only one complete top-level task in one Sol run. Do not split it into separately dispatched or artificially serialized packages. In the Sol-Luna arm, give its Sol controller that same complete task and measure the controller's full route interval, including every Luna child it launches.
- Test the production default first: one Luna writer at the lowest task-supported effort while Sol performs complementary Sol-owned work. Treat additional Luna writers as a separate concurrency experiment rather than silently changing the route under test.
- Store the campaign ledger and dashboard captures outside the repository. Do not create a clone, copied project, or worktree.
- Pre-register the route order, pair count, batch size, quality gate, time gate, and minimum allowance advantage. For the first v0.1.1 campaign, test a conservative lower bound of at least 10×.
- Run counterbalanced pairs. Four pairs in `ABBA` or `BAAB` order are the minimum pilot; use more pairs when the meter remains too coarse.

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
  --first-routes SOL_ONLY,SOL_LUNA,SOL_LUNA,SOL_ONLY `
  --five-hour-window-id five-hour-001 `
  --five-hour-reset-at 2026-08-28T12:00:00+10:00 `
  --weekly-window-id weekly-001 `
  --weekly-reset-at 2026-09-01T00:00:00+10:00
```

Immediately before launching an arm, take settled readings and record them. The command derives the pair and position from the registered order:

```powershell
python .agents/skills/sol-luna/scripts/allowance_campaign.py begin-arm `
  --ledger C:\benchmark\campaign.jsonl `
  --route SOL_ONLY --route-revision v0.1.1 `
  --observed-at 2026-08-28T09:00:00+10:00 `
  --five-hour-remaining-percent 100 --weekly-remaining-percent 100 `
  --start-evidence-digest sha256:2222222222222222222222222222222222222222222222222222222222222222
```

End the interval as soon as the tested Agent returns. `--elapsed-seconds` covers only that route interval. Independent acceptance still runs after the interval, but its result and defect count are attached to the route record:

```powershell
python .agents/skills/sol-luna/scripts/allowance_campaign.py end-arm `
  --ledger C:\benchmark\campaign.jsonl `
  --route SOL_ONLY --observed-at 2026-08-28T09:10:00+10:00 `
  --five-hour-remaining-percent 92 --weekly-remaining-percent 99 `
  --end-evidence-digest sha256:3333333333333333333333333333333333333333333333333333333333333333 `
  --elapsed-seconds 600 --independent-acceptance PASSED --defects 0
```

`status` is lock-free and read-only. It reports the active arm, next route, last readings, completed pairs, and cumulative excluded controller/referee consumption for each window. `assess` refuses an active arm and keeps five-hour and weekly results separate:

```powershell
python .agents/skills/sol-luna/scripts/allowance_campaign.py status --ledger C:\benchmark\campaign.jsonl
python .agents/skills/sol-luna/scripts/allowance_campaign.py assess `
  --ledger C:\benchmark\campaign.jsonl `
  --minimum-advantage-multiple 10 --minimum-pairs 4
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

The builder requires verified, fully readable explicit-session receipts with host-observed model, reasoning effort, role, and provider. `SOL_ONLY` is exactly one OpenAI `gpt-5.6-sol/high` controller and no worker. `SOL_LUNA` uses the same controller plus the manifest's explicitly declared one or two OpenAI `gpt-5.6-luna` writers at the declared effort. The production benchmark sets `sol_luna_writer_count` to `1`; `2` is reserved for a separately pre-registered concurrency experiment and does not raise the production routing cap. Every Sol-Luna arm in one campaign must use the same shape and effort. A logical receipt cannot be reused anywhere in the campaign, even when whitespace, indentation, or JSON key order differs. Absolute paths, drive paths, traversal, control characters, Windows device names, symlinks, missing routes, role/model/effort impersonation, self-report proof, unknown fields, and an existing output fail closed.

The output allowlist contains only the campaign and pair identifiers, declared Luna effort and writer count, route, redacted controller/writer identity values, receipt SHA-256 values, verification status, schema version, and a SHA-256 over the canonical index without that digest field. Each `receipt_sha256` is computed over the parsed receipt's sorted-key, compact canonical JSON, so it is stable across equivalent serializations. The index never copies receipt paths, source/thread references, working directories, or agent paths. Output uses a same-directory flushed and `fsync`-ed temporary file followed by `os.replace`.

## Accept or hold

Call the campaign a pass only when independent acceptance is equal, defects do not increase, total Sol-Luna elapsed time is strictly lower, the five-hour conservative aggregate advantage reaches the declared threshold, weekly evidence does not contradict the direction, and the arm order is counterbalanced. Report the displayed ratio and uncertainty interval, both meters separately, all failures and repairs, and any contamination boundary.

The official per-model rate card can estimate purchased credits from complete classified phase usage. It does not reveal the capacity behind a personal plan's five-hour or weekly percentage and cannot replace the account-meter result.
