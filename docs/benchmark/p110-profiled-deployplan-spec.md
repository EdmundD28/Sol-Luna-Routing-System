# P110 offline calibration draft: profiled deployment waves

## Purpose and history classification

This is a matched-workload candidate for comparing the installed Sol-Luna
workflow with v0.1.1. It is not a new routing mechanism and does not modify the
Sol-Luna product. It starts from the independently calibrated P085 oracle
implementation at commit
`7ed66ee4115cf534711e8497668cf5a69933ab35`.

Classification: `retry_changed_premise` of the P085 deployment-plan task family.
The changed premise is a mature implementation baseline plus one coherent
cross-layer capability: apply a single environment profile, propagate its
dependency impact, and compile deterministic bounded deployment waves. It must
not grow into rollback, capacity planning, expressions, profile inheritance,
network access, or plugin execution.

## Repository and ownership

Work only in the single formal repository:

`C:\Users\dai_m\Documents\Codex\2026-08-26\new-chat\work\sol-luna-delivery-system`

The route may modify only:

- `benchmarks/p085_fixture/deployplan/__init__.py`
- `benchmarks/p085_fixture/deployplan/errors.py`
- `benchmarks/p085_fixture/deployplan/model.py`
- `benchmarks/p085_fixture/deployplan/normalize.py`
- `benchmarks/p085_fixture/deployplan/graph.py`
- `benchmarks/p085_fixture/deployplan/diff.py`
- `benchmarks/p085_fixture/deployplan/planner.py`
- `benchmarks/p085_fixture/deployplan/overlay.py`
- `benchmarks/p085_fixture/deployplan/impact.py`
- `benchmarks/p085_fixture/deployplan/waves.py`

`benchmarks/p085_fixture/test_profiled_deployplan.py` is pre-existing independent
acceptance and read-only. Do not change, copy, disable, or replace it. Do not
modify product files, commit, switch branches, use network access, install
dependencies, create another agent, clone, copy, or create a worktree.

## Preserved P085 contract

All existing P085 public behavior remains valid. `compile_plan`,
`render_plan`, manifest normalization, dependency ordering and closure, safe
diff ordering, frozen models, canonical JSON, and digest semantics must not
regress.

## Profile overlay

Add `apply_profile(base, profile) -> tuple[Service, ...]`.

- `base` uses the existing manifest contract and is fully validated before the
  profile is applied.
- `profile` is a mapping with exactly one `services` field containing a list of
  override mappings. Unknown top-level fields fail before override fields.
- Every override requires `name`. Names use existing normalization. Normalized
  override names must be unique regardless of input spelling or order.
- Allowed override fields are `name`, `image`, `depends_on`, `env`, `tags`,
  `replicas`, and `remove`.
- `remove` defaults to false and must be a boolean. When true, `name` and
  `remove` are the only allowed fields and the normalized service must exist in
  the base.
- When false and the normalized name exists, every supplied service field
  replaces that complete field; omitted fields retain their base value.
- When false and the name does not exist, the override defines a new service
  and therefore must supply a valid non-empty `image`; other fields use the
  existing service defaults.
- Override field values use exactly the existing service validators. Environment
  values do not merge key-by-key: a supplied `env` replaces the complete
  environment.
- After all overrides are applied, validate the complete resulting manifest,
  including unknown dependencies and cycles. Return services in the existing
  deterministic dependency order: dependencies before dependants, with lexical
  tie-breaking. Existing services do not retain manifest insertion order and
  new services have no special insertion position. The order of override
  mappings and mapping keys therefore cannot affect a successful returned tuple
  or later plan output. Dependency-list member order retains P085 behavior;
  semantic graph and wave results remain deterministic for equivalent graphs.
- Neither the base nor profile object, including nested mappings and sequences,
  may be mutated.

Use deterministic `ManifestError` codes and paths:

- `BAD_PROFILE@$` when the profile is not a mapping;
- `UNKNOWN_FIELD@<field>` for an unknown profile top-level field;
- `BAD_PROFILE@services` when profile services is not a list;
- `BAD_OVERRIDE@services[i]` when an override is not a mapping;
- `UNKNOWN_FIELD@services[i].<field>` for unknown override fields;
- existing `BAD_NAME`, `BAD_IMAGE`, `BAD_DEPENDENCIES`, `BAD_ENV`, `BAD_TAGS`,
  and `BAD_REPLICAS` at the override field path;
- `BAD_REMOVE@services[i].remove` when remove is not boolean or `remove=true` is
  combined with any field other than `name` and `remove`;
- `DUPLICATE_OVERRIDE@services[i].name` with the normalized name;
- `UNKNOWN_OVERRIDE@services[i].name` when removing an absent service.

Error precedence is fixed. First validate that the profile is a mapping; then
reject the lexically first unknown top-level field; then require `services` to
be a list. Process overrides in list order. For each override: require a
mapping; reject its lexically first unknown field; validate `name`; reject a
duplicate normalized name; validate `remove` type; reject `remove=true`
combined with any field other than `name` and `remove`; reject removal of an
absent service; then
validate supplied service fields in this order: `image`, `depends_on`, `env`,
`tags`, `replicas`. A missing name therefore raises existing
`BAD_NAME@services[i].name`. For a new service, the `image` phase requires a
supplied valid image and otherwise raises `BAD_IMAGE@services[i].image` before
later fields. No later validation may mask an earlier error in this order.

## Impact-aware operations

Add operation kind `restart`. A restart binds the same desired `Service` as
both `before` and `after`.

After applying the profile to the desired base manifest:

1. Compute the ordinary add, update, and remove operations.
2. Let directly changed names be all names in those operations.
3. In the final desired graph, transitively mark every unchanged service that
   depends on a directly changed service.
4. Add one restart operation for every marked name that is not already added,
   updated, or removed.

Removals remain first in reverse current dependency order. Adds, updates, and
restarts then share the final desired dependency order. A dependent restart can
never precede the changed dependency that caused it. Multiple paths or multiple
changed ancestors still produce exactly one restart.

## Deterministic waves

Add `compile_profiled_plan(current, desired, profile, *, roots=None,
max_parallel=1) -> ProfiledPlan`.

- `max_parallel` must be a non-boolean positive integer; otherwise raise
  `ManifestError("BAD_PARALLELISM", "max_parallel", ...)`.
- Overlay and full graph validation occur before root selection.
- Without roots, plan the complete final desired graph. With roots, normalize
  roots after overlay and take their final dependency closure. Compare that
  selected desired tuple only with current services having the same selected
  names, exactly preserving P085's rule that a rooted plan never removes an
  unselected current service. Consequently rooted plans contain no removal for
  a service absent from the final selected closure. Compute direct changes and
  restart propagation only inside this selected comparison. A selected service
  may still restart because a changed dependency in the same selected closure
  precedes it.
- Removal operations form removal waves before all forward waves. A removal may
  share a wave only with removals that do not depend on one another in the
  current graph. Dependants are removed before their dependencies.
- Add, update, and restart operations form forward waves. An operation may
  enter a wave only after every operated-on dependency has appeared in an
  earlier forward wave; dependencies without operations are already satisfied.
- Construct removal waves from pending removals whose current-graph dependants
  are no longer pending; construct forward waves from pending add, update, and
  restart operations whose operated-on final dependencies are no longer
  pending. Within either ready set, names sort lexically and are chunked into
  waves of at most `max_parallel`. This defines the operation order for a
  profiled plan; it may differ from P085's harmless lexical tie order while
  preserving every dependency constraint. Input mapping, service, dependency,
  tag, environment, and override order cannot affect wave contents.
- Every operation appears in exactly one wave. Flattening waves yields exactly
  `ProfiledPlan.operations`.

`ProfiledPlan` is a public frozen, slotted dataclass with fields, in order,
`services: tuple[Service, ...]`, `operations: tuple[Operation, ...]`,
`waves: tuple[tuple[Operation, ...], ...]`, and `digest: str`. Its nested
collections are tuples. `ProfiledPlan`, `apply_profile`,
`compile_profiled_plan`, and `render_profiled_plan` must be imported and listed
in `deployplan.__all__`; all P085 exports remain present.

## Canonical rendering

Add `render_profiled_plan(plan) -> str`.

- Return compact canonical JSON with sorted object keys, unescaped UTF-8, and
  exactly one trailing newline.
- Top-level keys are `digest`, `operations`, `services`, and `waves`.
- Services and operations use the existing complete public shape. Every wave is
  a list of its complete operation objects, not references or names.
- The digest is `sha256:` plus SHA-256 of the same canonical object after
  removing only the top-level digest. Rendering recomputes the digest from the
  supplied plan body rather than trusting a manually constructed stale digest.

## Frozen acceptance

The independent public suite preserves all 33 P085 tests and adds 50 P110 tests
covering every rule above, including order permutations and immutability. It is
frozen in corrected fixture commit
`98bd1ae30ea560aa8bd90cb0330a2a3838c87e4f`. The earlier fixture commit
`6aadba66f7d9bd257709924f369a1a1c56b5eed7` is superseded because one test
indexed a dependency-ordered result as if manifest insertion order were kept.

Public test SHA-256:
`9f91a96393fdc2df589c92455f6ab06b48dd541f00dd286cd8363b179496f2a0`.

Run exactly from the formal repository root:

`C:\Users\dai_m\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -B -m unittest benchmarks.p085_fixture.test_deployplan benchmarks.p085_fixture.test_profiled_deployplan -v`

The accepted final signal is `Ran 83 tests` and `OK` with exit code zero. The
frozen unimplemented baseline ran the preserved 33 tests successfully and then
failed importing the absent `ProfiledPlan`; it reported `Ran 34 tests` and one
error. Thus the new suite is not an already-green or empty gate.

The route-external hidden referee remains outside the formal repository at:

`C:\Users\dai_m\Documents\Codex\2026-08-27\sol-luna-c-users-dai-m-3\work\p110\hidden_acceptance.py`

Hidden test SHA-256:
`271bf2b1ce173022cdddfdbbbcc388bdbf08d7ccfb3274f0745f85e498474d5e`.

After the route interval, run this exact PowerShell command from the preparation
workspace root
`C:\Users\dai_m\Documents\Codex\2026-08-27\sol-luna-c-users-dai-m-3`:

`$env:P110_REPO='C:\Users\dai_m\Documents\Codex\2026-08-26\new-chat\work\sol-luna-delivery-system'; & 'C:\Users\dai_m\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -B 'C:\Users\dai_m\Documents\Codex\2026-08-27\sol-luna-c-users-dai-m-3\work\p110\hidden_acceptance.py' -v`

The accepted hidden signal is `Ran 19 tests` and `OK` with exit code zero.
Hidden acceptance may use new combinations but no unstated semantics; neither
route may read it.

## Calibration gate

The offline route is eligible for a later matched allowance comparison only if:

- one real `gpt-5.6-luna/medium` owns the complete implementation;
- public and route-external hidden acceptance both pass;
- at most one focused same-Luna repair is needed;
- Sol does not re-read implementation bodies, rerun the final suite, or rewrite
  Luna-owned code;
- natural route duration is 15–35 minutes;
- the final suite has exactly one executor.

Otherwise record the failure and do not freeze the account or read allowance.
