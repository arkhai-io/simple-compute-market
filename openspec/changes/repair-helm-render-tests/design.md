# Design — repair Helm render tests

## Context

`make -C helm test-render` fails with `values don't meet the specifications of the
schema(s)`, `got null, want object`, on `dev` and under Helm v4.3.0 locally. CI installs
Helm through `azure/setup-helm@v4` with no `version:`, so it takes Helm's latest release.

The storefront chart's `agents` became a map keyed by agent name in
`share-site-projection-state` (archived 2026-10-19), so that an overlay states only what
it changes and a `null` removes a key or an agent. The storefront subchart ships
`agents: {}` and the umbrella's `values.yaml` declares Bob. The bare-metal subchart ships
no `internalRegistryTrust`; the umbrella supplies it. `DEPLOYMENT_AND_CONFIG.md`
("Storefront agents: pass-through configuration") documents `null` removal as the
operator idiom: a values file that replaces Bob states `bob: null`. Every render test that
sets a `null` arrived with that change; that change's validation records the render tests
passing without recording which Helm ran them.

### What Helm 4.3.0 does with a parent's null

Rendered with `helm template` under v4.3.0, the only release available to the design:

| Overlay, through the umbrella | Result |
|---|---|
| `storefront.agents.bob: null`, from a values file or `--set` | Refused by the umbrella's schema at `/storefront/agents/bob` and the storefront subchart's at `/agents/bob` |
| The same with `--skip-schema-validation` | Bob is not removed: the templates range over him with a nil entry and fail (`expected map; got interface {}`) |
| `bare-metal-storefront.internalRegistryTrust: null` | Refused at `/internalRegistryTrust` |
| `bare-metal-storefront.alkahestAddressBook: null`, a key the subchart's own `values.yaml` defines | Removed |
| `alkahestAddressBook: null` on the bare-metal chart rendered alone | Removed |
| `storefront.agents.bob.config.Settlement: null` | Refused by both schemas; without schema validation, rendered as `"Settlement": null` in `storefront.json` |

A `null` aimed at a subchart's values is removed only when the subchart's own defaults
define the key. Otherwise it survives, at any depth, into the parent's and the subchart's
schemas, the templates, and the rendered document. Every agent, every key under an agent,
and the bare-metal `internalRegistryTrust` are supplied from the umbrella or an overlay,
so the documented idiom fails for operators as well as tests: `helm install` and
`helm upgrade` apply the same schemas. The committed values files state no `null`, which
is why `deploy-local` and the two-release topology still render.

Which Helm release, if any, removed these nulls when the render tests last passed is not
known; no Helm 3 binary was available to the design.

### Corrections to the change as first written

1. The `null` idiom and every failing test are new with `share-site-projection-state`,
   not a long-standing idiom a Helm upgrade broke.
2. The failing nulls all target keys the subchart's own defaults do not define; the
   mechanism is how Helm carries a parent's `null` into a subchart's values, as above.
3. Only eight render tests set a `null` — four in the storefront chart's tests, two in
   the bare-metal chart's, two in `helm/tests/test_release_topology.py` — against the
   thirteen failures first reported. The full failing set is established before the fix
   (see "Implementation cadence").
4. `TESTING.md` ("Obtaining Helm where its download host is unreachable") cites "the
   pinned Helm of the release environment", and nothing pinned Helm.
5. Whether an operator's values file that nulls one of these keys fails the same way is
   answered: it does, so this is a deployment defect as well as a test one.

## Decisions

### D1. The cause is how a parent's null reaches a subchart

Established by rendering under Helm v4.3.0, as recorded under "What Helm 4.3.0 does with a
parent's null". Rejected: deferring the diagnosis to an implementation decision gate,
which would have forced the most expensive fix regardless of outcome; and pinning
whichever release passes without knowing why, which leaves operators on other releases
broken without a diagnosis.

### D2. The charts absorb a null; `null` removal stays the idiom

`null` in a values file removes what it names — an agent, an agent's value, or a key at
any depth of its configuration — and the charts make that true whatever the Helm
release's merge did:

- One recursive helper drops nulls from each agent before any template reads it. Every
  reader of an agent reads through it: the storefront chart's `configmap`, `deployment`,
  `service`, `secrets`, `pvc`, and `tests/storefront-environment-test.yaml`, the
  `_helpers.tpl` release checks, and the umbrella's `templates/tests/test-config.yaml`.
  The bare-metal chart applies it to its single agent's values and `config`. No reader
  needs to know about `null`.
- An agent renders as it would had a removed key never been stated. A setting the
  storefront defaults is omitted and defaulted; a value the chart adds when absent —
  `port`, `base_url`, `db_path`, the internal registry and its trust, the provisioning
  URL, the `default` capacity site — is added, the release's value; a setting the
  storefront requires is rendered absent, and the storefront refuses it at startup.
  (09 F1)
- An agent map that names no agent once its nulls are removed is refused at render,
  naming `agents`, by the helper in both the umbrella and the storefront chart, as the
  schemas' `minProperties: 1` refuses an empty map. An enabled storefront has at least
  one agent; `storefront.enabled: false` is how a release runs none. Rejected: rendering
  an agent-free release, which would drop that invariant and leave two ways to say "no
  storefront". The bare-metal chart has one agent, not a map. (09 F2)
- The hand-written schemas — the agent map and `internalRegistryTrust` in the storefront
  chart, the umbrella, and the bare-metal chart — accept `null` where an overlay removes
  something.
- `kit/config`'s values-schema generator gains a form that accepts `null` wherever it
  accepts a key. A key the schema refuses — a secret field, a retired key, a field a
  typed model lacks — stays refused even as `null`, so refusing secrets and retired keys
  never depends on the value an overlay gives. Each storefront's generator opts in; both
  charts' schemas and the umbrella's storefront definition are regenerated with
  `make helm-values-schema`, and each storefront's drift test holds the result.

A `null` always means removal, never a value. The generated definition accepts `null` for
optional typed fields today; after this change the chart removes such a key and the
storefront applies its own default, unless the chart derives it. A typed field whose default is not `None` therefore
cannot be set to `None` through chart values; the Secret overlay or the storefront's own
file still can. This is what `DEPLOYMENT_AND_CONFIG.md` promises, and on Helm 4.3.0 such
a `null` is refused today, so no working deployment changes.

Rejected:

- **Removable things as subchart defaults** (Bob back in the storefront subchart). An
  agent an overlay adds still could not have keys removed, the bare-metal chart alone
  must have no internal-registry trust to default, and `share-site-projection-state`
  found the opposite case failing on its Helm.
- **Explicit forms instead of null** (`enabled: false`, `internalRegistry: false`).
  Release-independent, but a values-shape change reversing the map decision's rationale,
  and keys inside `config` would have no removal form at all.
- **Pinning a Helm release that prunes, the idiom claimed only there.** No such Helm 4
  release is known, and operators on current Helm stay broken.
- **Changing only the tests.** Leaves the documented operator path broken.

### D3. CI pins Helm v4.3.0 exactly

`.github/workflows/tests.yml` passes `version: "v4.3.0"` to `azure/setup-helm@v4`, as
the same job pins uv (`version: "0.11.17"`). Moving Helm forward is a deliberate commit
whose render results are reviewed. Because D2 makes the charts correct under either merge
behaviour, the pin buys reproducibility, not correctness.

Rejected: no pin, which is how `dev` broke with no commit; a Helm 3 and Helm 4 matrix,
which doubles the job for a Helm 3 near the end of its support and not known to prune
these nulls; and a declaration file read by CI, more machinery than one tool needs.

### D4. The supported Helm is stated once, and every render run names its Helm

`TESTING.md` "Chart Render Tests" and `DEPLOYMENT_AND_CONFIG.md` say the supported Helm
is the release `tests.yml` pins; neither repeats the version, so a bump is one edit.
This replaces `TESTING.md`'s citation of a pin that did not exist.
`helm/scripts/test-render.sh` prints `helm version --short` first, so every render log,
including `make validate-helm`'s, names the Helm it ran. The documents claim only that:
they do not say render results are evidence only on the pinned release, since nothing
checks a run's Helm against the pin, and a passed render step is recorded as passed
whatever Helm ran it. (09 F3)

Rejected: prose alone, which leaves a run unable to say which Helm produced it, the gap
that left this change's cause undetermined; a warning when the local Helm differs from
the pin, which couples the script to the workflow's text; a declaration file the
script enforces, which would require exactly one Helm for any local render check; and
(09 F3) a `make validate-helm` check of the logged Helm against the pin, recorded as a
warning or a failure, which the owner declined so that this change leaves the
validation tooling alone.

### D5. `null` removal is a `deployment-state` requirement

"A storefront chart passes service configuration through" is modified: agents are a map
keyed by name, and a `null` removes what it names whatever the Helm release's merge did,
so a removed key never reaches a template or the rendered configuration. The rule stated
only in `DEPLOYMENT_AND_CONFIG.md` is behaviour implementations must satisfy, which
`openspec/README.md` places in `spec.md`. The Helm pin and the printed version are test
conventions and stay in `TESTING.md`.

Rejected: no delta, which leaves the behaviour this change repairs outside the contract
and the requirement's "exactly as written" ambiguous about `null`.

### Owner principles and where they go

No principle was stated that a permanent document lacks. The one the design produces —
chart behaviour does not depend on how a Helm release merges a `null` — is normative
through D5.

## Implementation cadence

One round, one session, then the implementation review:

1. Run `make -C helm test-render` under Helm v4.3.0 and record every failing test and its
   cause. A failure that is not a surviving `null` is reported to the owner before the
   fix proceeds, not folded into it.
2. The charts absorb a `null` (D2): the helper, every agent reader, the hand-written
   schemas, the generator form, the regenerated schemas, and render tests for D5's
   scenarios, including removal of the only agent through the umbrella and through the
   storefront chart alone. Any typed field whose default is not `None` is recorded as a
   finding.
3. The CI pin and the printed Helm version (D3, D4).

Validation: `make -C helm test-render` with both loader interpreters set, `kit/config`'s
unit tests, both storefronts' values-schema drift tests, `make test`,
`make check-packaging`, and `make validate-helm`, which this change unblocks.

## Open questions

None.
