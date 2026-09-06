# P110 Medium profiled deployment-plan calibration

## Decision

`DO_NOT_FREEZE_ALLOWANCE`.

The corrected candidate passed the complete frozen quality boundary but took
only 252.134 seconds at the route boundary, far below the preregistered
900–2100 second duration gate. No account allowance was read and no account
freeze occurred.

## History and scope

P110 is a `retry_changed_premise` workload in the P085 deployment-plan family,
not a new Sol-Luna mechanism. It starts from the independently calibrated P085
oracle implementation and adds one coherent capability: single-profile overlay,
dependency impact propagation, deterministic bounded waves, and canonical
rendering.

- source oracle: `7ed66ee4115cf534711e8497668cf5a69933ab35`
- corrected frozen baseline: `fc0184d1dc83133461e13ef924bafe1d6a77afbd`
- accepted candidate: `be704a566e2fa53519c7b2c2d7170547cfc69c32`
- public tests: 33 preserved P085 plus 50 P110, `83/83`
- route-external hidden tests: `19/19`
- writer: one fresh `gpt-5.6-luna/medium`
- focused implementation repairs: zero
- Sol implementation, rewrite, full-body reread, or public-suite rerun: zero
- final public-suite executors: one, the Luna writer

The route ran from `2026-09-07T01:41:49.4001317+10:00` to
`2026-09-07T01:46:01.5341029+10:00`, or 252.134 seconds. The writer session
spanned about 170.739 seconds. Host cumulative-counter deltas were 638,895
input, 602,880 cached input, 36,015 non-cached input, 6,824 output, and 401
reasoning tokens. These counters explain workload shape; they are not allowance
evidence.

## Censored first attempt

The first route was censored before quality attribution. Public
`test_12_omitted_existing_fields_retain_values` indexed the result as manifest
order even though the frozen contract requires dependency order. The candidate
correctly returned `db, api`; the test expected `api` at index zero. The
candidate was preserved at
`be65cad2f3ec4f1d1f32959b04ecc0a8deecf3fa`, the test was corrected to select
the service by name, and an independent reviewer approved the refreeze. This is
neither an implementation repair nor a quality failure.

## What this falsifies

P110 falsifies the claim that adding one more deterministic cross-layer feature
to the mature P085 compiler will naturally create a 15–35 minute Medium task.
P085 took roughly 9–12 minutes; P110's extension took only about 4.2 minutes.
Adding rollback, capacity, inheritance, expressions, or more operators solely
to reach a duration target would be artificial task inflation and is prohibited.

The next candidate must obtain duration from a pre-existing substantial
maintenance surface or a naturally defined end-to-end user task, not by growing
P085/P108/P109 or bundling unrelated leaves. Until such a task has independent
acceptance and an offline duration calibration, no new quota experiment is
eligible.
