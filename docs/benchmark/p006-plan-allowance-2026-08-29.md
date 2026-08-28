# P006 plan-allowance pair — 2026-08-29

## Decision

`HOLD_SOL_ONLY` for this task family. The single pair does not establish a
general routing policy, but it rejects the tested v0.12 Sol-Luna topology for a
tightly coupled closure-projection task: equal diagnosed quality cost more
displayed allowance and more wall time.

## Frozen comparison

- Starting commit: `625ea22d0937d372ded7255760185ddad0647b0a`
- Task specification:
  `sha256:5dc4aa67acb657b86791ad8be6b502bb29594c3013ad4b6a1c7328dcdb15048e`
- Preregistered referee:
  `sha256:ecf0be37dc1da7e63ed86b74f87221ee26bceaea4281e46cbd517c217a7fc9d3`
- Order: `SOL_LUNA`, then `SOL_ONLY`
- Both controllers: host-selected `gpt-5.6-sol/high`
- Sol-Luna writer: one retained `gpt-5.6-luna/high`; one initial handoff and
  one focused repair; Sol reported no Luna-scope edit or reclaim
- Sol-only: one continuous controller and no subagents
- Meter resolution: one displayed percentage point

The route boundaries exclude commits, referee execution, branch preparation,
and experiment-controller work. No meter movement occurred in the excluded gap
between the Sol-Luna end and the Sol-only start.

## Route-only observations

| Route | Start, Sydney | End, Sydney | Elapsed | Five-hour left | Weekly left | Candidate |
|---|---|---|---:|---:|---:|---|
| `SOL_LUNA` | 02:01:44.278 | 02:22:52.465 | 1268.187 s | 100% to 98% | 81% to 80% | `439b3dac756edc7c0b12c5d79b155b2f8defd91f` |
| `SOL_ONLY` | 02:25:22.052 | 02:44:32.506 | 1150.454 s | 98% to 97% | 80% to 80% | `75a1785817f61388ded9d667194baa3731992423` |

At displayed resolution, Sol-Luna consumed two five-hour percentage points
versus one for Sol-only. It was 117.733 seconds, or 10.23%, slower. The weekly
meter moved one point for Sol-Luna and zero for Sol-only. With one coarse pair,
these are directional readings rather than a stable multiplier.

## Referee audit

The untouched preregistered referee reported 6/8 for both candidates. Its two
common failures were defects in the referee, not demonstrated candidate
failures:

1. its `digest(number)` helper repeated a multi-digit hexadecimal string 64
   times, producing a 128-digit value for `20` where the public contract
   requires exactly 64 digits;
2. it required unpublished output key names even though the task specified the
   evidence value and affected units, not their JSON member names.

The original 6/8 records and referee digest remain authoritative evidence of
that preregistered-suite failure. A disclosed post-hoc wrapper corrected only
those two referee assumptions in memory; both immutable candidates then passed
8/8. This supports functional equivalence but is not relabelled as a clean
preregistered blind pass.

The Sol-Luna writer also disclosed that a broad read-only search accidentally
printed matching lines from the hidden referee before handoff. The candidate
still failed the original two flawed groups, but the exposure invalidates a
claim of strict blind independence for that arm.

## What v0.12 got right and wrong

The same-Luna repair rule was directionally useful: the Sol controller did not
shadow-implement or reclaim Luna work. It did not, however, erase fixed Sol
planning, handoff, review, and integration cost. This task supplied no valuable
path-disjoint Sol work while Luna ran, so the coordination cost could not be
amortized. Forcing Luna participation was therefore the wrong route for this
task even though the repair protocol itself behaved as intended.

The existing policy already rejects a candidate when expected allowance
savings miss 50%, elapsed time does not strictly improve, or coordination cost
is too large. P006 was an experimental forced route, not evidence that those
gates should be relaxed.

## Forward change

The retained implementation adds a replay-only `project` interface to the
closure contract. It converts a frozen event prefix into the current state,
next legal events, remaining repair budget, and exact failed or open-repair
units. This is aligned infrastructure because it can replace repeated Sol
history interpretation with one deterministic compact handoff to the retained
Luna. P006 does not yet prove that this mechanism saves plan allowance.

The next matched family should use a larger path-disjoint architecture task in
which Luna owns implementation and visible repairs while Sol concurrently
prepares independent acceptance and integration. A task without that useful
Sol lane should remain Sol-only rather than using Luna for participation's sake.
