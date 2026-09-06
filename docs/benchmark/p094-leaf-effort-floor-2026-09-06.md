# P094 same-allocation leaf effort calibration

P094 tested whether the existing Medium floor for a five-leaf semantic portfolio could safely move to Low. It was an offline mechanism calibration, not an included-plan allowance experiment.

## Frozen comparison

- Common baseline: `fc802d45d2fdfbb3fd9bc5108d040cb4a8379dc1`.
- Identical ownership: five independent `artifacts`, `cache`, `patches`, `rollout`, and `retention` API files.
- Identical public contract: A068-A117, 50 tests, at most one internal correction.
- Identical external judge: H01-H15, SHA-256 `7332f628e073a8256d7875b111b139f920e4bdc079c7425d3d9c64b06ae01d12`.
- Only the Luna reasoning effort differed.

The first Low launch was excluded before comparison because an invalid edit-tool request changed no file. The allowed fresh Low run produced a candidate but passed only 35/50 public tests and did not use its available correction, so the hidden judge was not run. Its session was about 182 seconds with a 27,858 non-cached input-token delta.

The fresh Medium run passed 49/50 initially, used one internal correction, then passed 50/50 public tests and 15/15 external hidden tests. Its session was 269.188 seconds with a 34,463 non-cached input-token delta. Sol neither implemented nor repeated the public suite.

## Decision

Keep Medium as the lowest supported effort for this five-leaf semantic portfolio. Low was about 19.2% cheaper by the diagnostic non-cached-input measure and faster, but it failed the quality gate, so those savings are ineligible. This result does not exclude Low for genuinely mechanical work and does not establish any subscription allowance result.

Independent review: `REVIEW_PASS`. No normal-path instruction or runtime mechanism changed.
