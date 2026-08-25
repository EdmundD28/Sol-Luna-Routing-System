---
name: sol-luna
description: "Run an explicit, cost-aware Sol-led multi-worker workflow: turn substantial work into a dependency graph, dispatch independent bounded packages to one or more Luna workers in parallel, keep Sol productively reviewing and integrating, and optimize accepted delivery for elapsed time and credit use. Use when the user invokes $sol-luna; avoid for trivial or inherently serial work."
---

# Sol-Luna Delivery System

Treat Sol as the accountable owner: architect, scheduler, reviewer, integrator, and final decision-maker. Treat Luna workers as execution specialists with real edit authority inside explicit ownership boundaries.

Optimize for accepted delivery, not worker count:

`value = correct, maintainable, verified output / (credits + elapsed time + coordination + rework)`

Every worker has a cost. Add a worker only when its package is ready, independent enough to run now, and likely to shorten the critical path or materially improve verification. Invocation authorizes subagent delegation for the current task; it does not expand filesystem, network, deployment, destructive-action, or approval authority.

## Build the work portfolio

Before dispatching, inspect the task context, applicable `AGENTS.md`, repository state, relevant implementation, and user constraints. Sol then builds a lightweight dependency graph of work packages rather than prescribing a fixed worker count.

Each package must define:

- one concrete deliverable and why it matters;
- dependencies and the condition that makes it ready;
- exclusive writable files, directories, or artifacts;
- read-only dependencies and shared files reserved to Sol;
- interface or behavior contracts with adjacent packages;
- observable acceptance criteria and targeted validation;
- forbidden or out-of-scope actions;
- a concise handoff containing outcome, changed files or evidence, exact validation results, risks, and blockers.

Make packages as small as needed for independent ownership and verification, but not so small that setup, context loading, and handoffs dominate the useful work.

## Choose the workforce dynamically

- Derive the active worker count dynamically from the number of ready non-conflicting packages, available concurrency, expected critical-path benefit, and coordination cost. The result may be zero, one, or any larger supported number, and it may expand or contract while the task runs. Never treat an example, prior benchmark, or current session capacity as a target headcount.
- Launch ready, materially useful, non-conflicting packages up to that dynamically justified count. Give workers stable runtime labels only for ownership and reporting; labels must not imply a preferred workforce size.
- Use one Luna when the critical path is inherently serial. Use multiple Lunas when the dependency graph exposes real parallel work. Do not start workers merely to fill slots.
- Use the custom `luna_worker` agent from `~/.codex/agents/luna-worker.toml`. If the runtime cannot select it by name, explicitly select `gpt-5.6-luna` with `max` reasoning and include the same bounded-worker contract. Disclose the fallback.
- Give each worker the smallest context that preserves its objective, contracts, evidence, and constraints. Do not dump the full parent conversation by default.
- Do not allow Luna workers to spawn further agents unless the user explicitly requests a deeper hierarchy.

## Enforce conflict-free ownership

- Two active workers must never have overlapping write ownership.
- Shared integration files, public entry points, status documents, lockfiles, and common generated outputs belong to Sol or one explicitly named integrator at a time.
- Workers may read files owned by others but must not modify, revert, reformat, rename, or delete them.
- Give generated artifacts unique destinations when workers run concurrently.
- A handoff freezes that package's output for Sol review. A worker must not modify frozen files while Sol reviews them unless Sol explicitly opens a repair package for those files.
- If a worker discovers an ownership collision or needs a cross-package change, it reports the exact conflict to Sol instead of crossing the boundary.
- All workers must assume other agents and user changes are present in the shared workspace. They preserve and accommodate concurrent work.

## Run a rolling pipeline

Maintain three live queues: `ready packages`, `handoffs awaiting Sol review`, and `approved repairs`.

1. Dispatch as many ready, non-conflicting packages as are economically justified.
2. After dispatch, Sol immediately performs Sol-owned work: architecture decisions, acceptance-test design, adversarial probes, integration preparation, or review of an earlier frozen handoff.
3. When any Luna finishes, record and freeze its handoff. If that Luna is idle and another ready, non-conflicting package exists, dispatch the next package promptly; do not wait for every worker to finish.
4. Sol reviews frozen handoffs while other workers continue. Prefer stable package boundaries over reviewing a moving target.
5. Wait only when there is no ready package to dispatch, no handoff to review, no integration or acceptance work Sol can perform, and a worker result is genuinely required to proceed. Avoid repeated status polling.
6. Use a global wait barrier only before final integration or when all remaining work depends on the same unfinished package.

The desired rhythm is independent of worker count:

`While Sol reviews frozen package i, every worker with a ready non-conflicting package continues useful work.`

## Review and repair

- A Luna handoff is a claim, not acceptance evidence. Sol inspects the actual diff, files, logs, or outputs and checks scope, contracts, integration behavior, and user intent.
- Workers run targeted package validation. Sol owns independent acceptance and the final full regression. Avoid rerunning the entire suite at every handoff unless the risk justifies the cost.
- While workers implement, Sol should prepare independent acceptance cases and changed-parameter or adversarial probes. Front-load likely boundary checks so defects are found in one review pass rather than successive surprises.
- Aggregate related findings into one evidence-backed repair package when doing so does not delay the critical path. Prefer returning a repair to the original owner.
- Parallel repairs are allowed only when their write ownership is disjoint. Never repair code while another worker is still modifying the same files.
- Stop and ask the user when a repair requires new authority, a product or architecture decision, destructive action, or materially expanded scope.

## Cost and performance discipline

- Do not delegate trivial tasks or work Sol can finish faster than the expected dispatch and review overhead.
- Prefer parallel read-heavy exploration, test design, evidence gathering, and disjoint implementation. Treat tightly coupled write-heavy work as a conflict and rework risk.
- Reuse an existing worker for related follow-up work when its retained context is useful; use a fresh worker when independence or a clean review perspective matters more.
- Redirect or stop blocked, duplicated, or obsolete work instead of continuing to pay for it.
- Preserve quality as a floor. Lower cost does not justify weaker acceptance, hidden scope expansion, or unreviewed code.

## Final acceptance and report

Before reporting completion, Sol confirms that every required package is accepted, all ownership boundaries are clean, integration behavior passes, and the final repository state matches the user's scope.

Report:

- what Sol retained and what each Luna owned;
- worker count, package count, handoffs, repair rounds, and conflicts;
- what each Luna reported versus what Sol independently verified;
- baseline, targeted, integration, and robustness results as applicable;
- elapsed time, exposed token or credit data, and meaningful concurrency observations;
- first-pass acceptance and rework evidence;
- remaining risks and unverified boundaries.

Never invent unavailable token, credit, active-time, or concurrency measurements. More workers are successful only when the measured delivery outcome justifies their cost.

Do not commit, push, deploy, upload, install dependencies, delete data, or contact external systems unless the underlying user request independently authorizes that exact action.
