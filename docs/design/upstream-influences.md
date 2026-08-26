# Upstream Influences and Rejected Imports

This revision studied current public source at the pinned commits below. The implementation is original to this repository; it adapts narrow design patterns rather than copying the upstream packages wholesale.

| Project | Pinned commit | Pattern adapted | Deliberately not imported | License |
|---|---|---|---|---|
| [Codex PROVE](https://github.com/yehyakin/codex-prove) | `805a236335f44b703d417545dee3cc718e7127fb` | Forward cases for stale evidence, transport-versus-acceptance, bounded correction, and runtime identity | Terra/complex tier, universal one-fix rule, and universal fail-closed identity requirement | Apache-2.0 |
| [Codex Audit](https://github.com/EmergentKnowledgeGroup/Codex_audit) | `57a822e5dca6c3572b0802bd467a03ae5f7b4139` | Redacted run references, matched-pair evidence, explicit `not assessed`, source-aware cost fields | Local Codex database coupling, rate-card estimates as if they were billing, and route promotion from one exploratory pair | MIT |
| [Codex Model Router](https://github.com/capitalparser/codex-model-router) | `3b7859a17cc5ea640f9967221600db9e3a578433` | Allowlisted JSONL records and strict verified-outcome evidence | Terra/Sol worker registry and automatic history override after two passes | MIT |
| [Sol Advisor](https://github.com/DannyMac180/sol-advisor) | `37b75cad535abdd46531f0227483a8842d045ab8` | Explicit-session runtime inspection and rejection of missing or conflicting host fields | POSIX-only shell implementation, global session discovery, Terra and fresh-Sol lanes | MIT |

## Local corrections

- Runtime evidence is redacted by default and requires an explicit session file plus thread ID.
- Strict identity and boundary checks compare caller-supplied expected values with host-observed values; config-file presence alone is not proof.
- The atomic ledger requires five clean matched pairs in one policy, suite, metric, and source cohort before evidence is merely eligible for human review.
- Token cohorts and displayed allowance deltas may diagnose efficiency, but they cannot satisfy the credit-reduction policy gate.
- Even after the threshold is reached, the tool cannot choose or modify a route.
- Terra remains outside the current two-tier stability boundary.

[Official OpenAI model guidance](https://developers.openai.com/api/docs/guides/latest-model) recommends choosing reasoning effort intentionally and comparing representative tasks using success, completeness, evidence, tokens, latency, and cost. Accordingly, this repository predicts among Luna `low`, `medium`, `high`, `xhigh`, and `max`, then requires matched evaluation before a policy change. It does not retain `max` as a universal baseline.
