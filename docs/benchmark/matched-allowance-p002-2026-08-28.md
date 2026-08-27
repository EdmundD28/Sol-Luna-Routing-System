# Matched allowance pilot p002 (2026-08-28)

## Result

`HOLD_SOL_ONLY`. The tested two-Luna High route failed the equal-quality gate, used no less displayed five-hour allowance, and was slower. It is evidence against that route shape, not evidence against every Sol-Luna configuration.

| Measure | Sol-only | Sol-Luna (two Luna High writers) |
|---|---:|---:|
| Hidden test methods passed | 10/10 | 9/10 |
| Independently confirmed implementation defects | 0 | at least 2 |
| Route elapsed time | 1,156.909 s | 1,211.533 s |
| Five-hour meter consumption | 1-2 percentage points | 2 percentage points |
| Weekly meter consumption | 0 percentage points | 0 percentage points |

Sol-Luna was 54.624 seconds (4.72%) slower. Its displayed five-hour consumption was not lower: the conservative Sol-only/Sol-Luna allowance ratio was 0.5-1.0, far below the pre-registered 10x target. Because acceptance differed, no economic win may be claimed from this pair.

## Fair comparison boundary

Both arms received the same complete top-level task from starting commit `ccfb9e2c278dd07041a78d25d1a6f8bbbd2d664e`. Sol-only began as one complete Sol task, not two separately dispatched Sol packages; its two later evidence-backed repair intervals were measured separately and added to its route total. The Sol-Luna controller received that same whole task and chose two independent Luna High packages while retaining documentation and integration.

The route clock and allowance interval started immediately before each tested controller launch and ended at its formal return. The experiment controller's hidden acceptance, review, branch changes, commits, dashboard settling, and preparation for the next arm were excluded and reported as referee work. Repairs were measured as separate route intervals and added to their arm; referee gaps were not charged to either arm.

The allowance hidden suites were amended to remove output-field names that the task specification had not required. The final identity suite still hard-coded `verification_status`, although the specification required only a semantic overall verification status. Its replay check also asserted only that the process failed, so an earlier controller-role rejection could mask a digest-replay defect. These judge flaws weaken the pilot: p002 is a routing failure diagnostic, not final campaign proof.

## Runtime identity and quality finding

Host-observed session receipts verified one `gpt-5.6-sol` High controller in each arm and two `gpt-5.6-luna` High workers in the Sol-Luna arm. Worker labels and prose were not treated as identity proof.

Static review confirms at least two independent Sol-Luna defects: it rejected a host-observed Sol controller whose runtime role was `worker`, and it hashed raw receipt bytes, allowing the same logical JSON receipt to evade replay detection after reformatting. The hidden suite's 9/10 method count does not isolate those two defects and must not be read as a defect count. The Sol-only arm exposed and repaired both defects during its allowed repair intervals. The Sol-Luna arm had already spent its one focused repair on allowance-campaign semantics, so it correctly failed the final gate instead of receiving an unbounded rescue.

## Decision carried forward

This pilot rejects automatic two-High-Luna concurrency. The next production-shaped comparison must:

- give each arm one identical complete top-level task;
- use one Luna writer first, at the lowest task-supported effort;
- keep Sol on complementary architecture, integration, or acceptance work rather than idle supervision;
- measure the full Sol-Luna controller interval, including its Luna child;
- require equal independent acceptance before comparing economics;
- retain the 10x conservative five-hour meter target for the first claimed v0.1.1 advantage.

Policy 1.3.0 therefore lowers the default executable writer cap from two to one and raises the predictive accepted-cost saving floor from 15% to 50%. These are fail-closed routing corrections. They are not yet proof that the revised route beats Sol-only; that requires a new matched account-meter campaign.
