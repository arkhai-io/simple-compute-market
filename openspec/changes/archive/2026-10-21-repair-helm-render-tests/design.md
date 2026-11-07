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

`null` assigned to a mapping key in a values file removes that key — an agent, an
agent's value, or a key at any depth of its configuration, including mapping keys
inside list elements — and the charts make that true whatever the Helm release's
merge did. List elements retain their item schema's meaning; normalization does not
remove a null list element:

- One recursive helper drops nulls from each agent before any template reads it. Every
  reader of an agent reads through it: the storefront chart's `configmap`, `deployment`,
  `service`, `secrets`, `pvc`, and `tests/storefront-environment-test.yaml`, the
  `_helpers.tpl` release checks, and the umbrella's `templates/tests/test-config.yaml`.
  The bare-metal chart applies it to its single agent's values and `config`, and the
  umbrella's test-config, which also reads the bare-metal agent's `config` to find the
  sites it binds, reads that through the same normalization. No reader needs to know
  about `null`.
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
  something. In the storefront chart and the umbrella that is every value of an agent
  (22 F1): its `port`, `component`, `configMapName`, `identity`, `secret` and the keys
  under it, `alkahestAddressBook` and the keys under it, `internalRegistryTrust`, and
  `config`. A removed `component`, `configMapName`, `secret.configKey`, or address-book
  key takes the chart's default; a removed `secret` or `secret.secretName` mounts no
  runtime overlay, and a removed `alkahestAddressBook` no address book. An agent stating
  no `port` or no `identity` once its nulls are removed is refused at render, naming it,
  by the helper in both the storefront chart and the umbrella: the chart has neither to
  default to. The keys inside `identity` keep their schema, since each is required and
  removing one could only be refused.
- `kit/config`'s values-schema generator gains a form that accepts `null` wherever it
  accepts a key. A key the schema refuses — a secret field, a retired key, a field a
  typed model lacks — stays refused even as `null`, so refusing secrets and retired keys
  never depends on the value an overlay gives. Each storefront's generator opts in; both
  charts' schemas and the umbrella's storefront definition are regenerated with
  `make helm-values-schema`, and each storefront's drift test holds the result.

A `null` assigned to a mapping key means removal, never a mapping value. The
generated definition accepts `null` for
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
keyed by name, and a `null` assigned to a mapping key removes that key whatever the
Helm release's merge did, so an agent renders as if the key had never been stated.
List elements retain their item schema's meaning; normalization does not remove
null list elements. The rule stated
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

## Implementation findings

### The failing set before the fix

`make -C helm test-render` on `9fe51bf3e`, after `make dist`, with both loader
environments present (each reinitialized against those wheels by its storefront's test
target). The step could not run `helm version`, so the Helm's release is not recorded for
this run: its refusals are worded by Helm 4's schema validator, and they are the
refusals the design recorded under v4.3.0, but that is not proof of the release. Once
the owner granted it, `helm version --short` reported `v4.3.0+gbec5b06` for the Helm on
`PATH` during Section 3, the binary unchanged since this run. Every
umbrella assertion in `test-render.sh` passes; thirteen Python render tests fail,
matching the thirteen first reported.

Ten fail because a `null` survives into a values schema (`got null`). The last column
names the path the refusal named; a test whose loop stops at its first failing case is
recorded by that case.

| File | Test | The refused `null` |
|---|---|---|
| `helm/charts/storefront/tests/test_render.py` | `test_stated_values_are_rendered_as_stated` | `internalRegistryTrust` |
| same | `test_a_differently_spelled_section_is_read_for_release_checks` | `config.Identity`, `config.Settlement` |
| same | `test_release_disagreements_are_refused_naming_them` | `internalRegistryTrust`, its "trust missing" case; its later "service peer" case, which nulls `config.Identity.service_peers.provisioning_default`, did not run |
| same | `test_release_owned_keys_are_matched_in_any_spelling` | `internalRegistryTrust` |
| same | `test_typed_fields_are_accepted_in_any_spelling` | `config.Identity.service_peers`, `config.Settlement.priority` (it also nulls `config.Identity.principal`, which the generated schema already accepts as `null`) |
| same | `test_a_null_removes_an_agent` | the agent `bob` |
| `helm/charts/bare-metal-storefront/tests/test_render.py` | `test_an_umbrella_release_keeps_a_registry_and_sites_the_config_states` | `internalRegistryTrust` |
| same | `test_an_umbrella_releases_parts_that_disagree_are_refused` | `internalRegistryTrust` ("requires internalRegistryTrust") |
| `helm/tests/test_release_topology.py` | `test_the_smoke_profile_carries_only_what_the_release_states` | `storefront.agents.bob.internalRegistryTrust` |
| same | `test_one_release_running_both_storefronts_on_its_provisioning_service_is_refused` | `bare-metal-storefront.internalRegistryTrust` |

So ten tests set a `null`, six of them in the storefront chart's tests, not the eight and
four "Corrections" 3 counted; the plan's 4.5 names "the four existing tests that set a
`null`" in the storefront chart, which are these six.

Three fail for another cause: each asserts a message the render's refusal does not
contain, while the values schema refuses the same value for the same key in other words.
The asserted wording is presumably an earlier Helm's schema message; which Helm, and
whether that refusal came from the schema or a template, is not recorded.

| File | Test | Asserted | The refusal this run printed |
|---|---|---|---|
| `helm/charts/bare-metal-storefront/tests/test_render.py` | `test_a_stated_port_must_be_a_number_equal_to_the_charts` | `config.port` | `at '/config/port': got string, want integer` |
| same | `test_the_retired_values_shape_is_refused_naming_each_key` | `Additional property siteBindingsSecret is not allowed` | `at '': additional properties 'siteBindingsSecret' not allowed` |
| `helm/charts/storefront/tests/test_render.py` | `test_an_agent_is_named_by_its_key_alone` | `agents.bob.name` | `at '/agents/bob/name': false schema` |

None involves a `null`, and none was in the plan. At task 1.1's gate the owner decided
they belong to this change (option (a)): each test asserts the key its refusal names
rather than a whole message, so it holds however the pinned Helm words a schema refusal;
no chart changes. Rejected: (b), leaving them to another change, under which
`make -C helm test-render` could not pass and this change could not meet its acceptance
boundary. The plan's task 4.5 carries the fix, and its count of the tests that set a
`null` is corrected to the ten above; "Corrections" 3 undercounted them.

### Typed fields a chart `null` cannot set to `None`

None found among the fields the typed models generate. A chart `null` now removes a
typed field, so the storefront applies its default; that differs from stating `None`
only for a field whose type admits `None` and whose effective default is not `None`.

- Every model field typed to admit `None` defaults to `None` in its model: VM's
  `Identity.principal`; bare metal's `Identity.principal`,
  `capacity.source_confirmation_seconds`, `pricing.default_max_duration_seconds`,
  `negotiation.policies`, `Chains.<name>.chain_id` and `.alkahest_address_config_path`,
  and `Delivery`; Alkahest's `address_config_path`; Arkhai payments' `service_url`,
  `service_identity`, `dispute_authority`, `api_key_env`, and `fee_bps`; the delivery
  kit's `timeout_seconds`; and the SMTP sink's `username`. Bare metal's packaged
  `settings.toml` states none of its own.
- One effective default is not the model's: VM's declarations type the section but do
  not parse it at runtime, and VM's packaged `settings.toml` states
  `[Identity.principal]` with an empty scheme and identifier. Removing it therefore
  yields that placeholder, where `None` read as an empty table; both are refused at
  startup as "identity.principal is required and must be canonical", so the outcome
  is the same.
- Every other typed field has a type that refuses `None`, so `None` was never a value
  an operator could set through the chart for it.

Not checked: keys no typed field generates — VM's open root and untyped sections
(`capacity`, `pricing`, `negotiation`, `provisioning`, and `registry` apart from
`auth`), values typed `Any` such as `pricing.settlements[*]`, and instances of sinks the
schema does not type. Their schema accepted `null` already, which rendered as `None`
where Helm kept it; after Section 4 the chart removes them instead, as D2 settles.

### Agent values the hand-written schemas still refuse as `null`

The delta's requirement says a `null` removes "a value of an agent". The charts' helpers
remove any agent value, but D2 and task 4.4 widened the hand-written schemas only for an
agent, its `internalRegistryTrust`, and its `config`, so a values file stating `null` for
an agent's `secret`, `component`, `configMapName`, `alkahestAddressBook`, `port`, or
`identity`, or for a key nested in one of them, is still refused by the schema before
the chart can remove it.

Settled at the implementation triage (22 F1), option (a): every value of an agent
accepts `null`, as the delta's requirement says, and a removed `port` or `identity` is
refused naming it (D2). Rejected: (b) narrowing the delta to the three values the
schemas then accepted, which leaves the operator rule with exceptions and no way to
drop Bob's `component` or runtime `secret`; and (c) widening only the four values whose
absence has a defined rendering, which keeps `port` and `identity` as exceptions to
state rather than refusals the rule already implies.

## Implementation detail retained at closeout

Completion notes were compressed in tasks.md without changing completed task instructions.
The following evidence and review rationale is retained here.

### 1. The failing set under Helm v4.3.0: implementation and review notes

Notes: no code changed. `make test` on the same commit stops at its last suite,
`test-deployment-packaging`, on `make -C helm test-render` with the same failures;
every suite before it, `test-release-tooling` included, passes. End-to-end: none; the
section changes nothing deployed.

### Task 1.1: detailed implementation evidence

Recorded in `design.md` "Implementation findings", "The failing set before the
fix". `make -C helm test-render` (chart render tests, both loader interpreters set):
every `test-render.sh` assertion passes; 13 Python render tests fail — 10 on a
surviving `null` (6 storefront, 2 bare-metal, 2 topology: ten tests set a `null`,
not eight), and 3 on Helm 4.3.0 wording a schema refusal differently from what the
test asserts. After `make dist`, the loader environments were created by
`make test-storefront` and `make -C domains/bare_metal/storefront test` (each
reinits first; 448 unit and integration tests and 438 tests passed), since this
step may not run the `init` targets. The step may not run `helm version`, so this
run's Helm release is not recorded; Section 5's printed version names the Helm of
its own run only.
Gate answered: the owner chose (a); the three wording failures belong to this
change, fixed in 4.5 (`design.md` "Implementation findings").
Correction: VM's 448 were its integration suite; its unit suite passed too
(1101). The Helm on `PATH` is v4.3.0 (`helm version --short`, granted later).

### 2. `kit/config`: the generator accepts `null` wherever it accepts a key: implementation and review notes

Notes: the fresh-context check found keys inside list elements left null-refusing
against the delta's "at any depth"; fixed by recursing into `items` (2.1's note). It also
found a shared `{"type": "null"}` node and unhandled `$ref`; both fixed. Declined: a key
refused by a schema other than `false` (`{"not": {}}`) would be widened; the generator
refuses keys only with `false`, which is the plan's definition of a refused key.

### Task 2.1: detailed implementation evidence

`accepting_null(definition)`. A key's schema is widened by extending its
`type` where it states one and nothing that applies to every type
(`const`, `enum`, a combinator); an `anyOf` alone gains a `null` branch;
anything else is wrapped in `anyOf: [schema, {"type": "null"}]`; a schema that
already accepts `null` is left as it is; a schema with `$ref` is wrapped, since
its siblings are ignored. Every combinator in `_COMBINATORS` and `items` is
recursed into without widening the branch or item itself: the keys they type
accept `null` (under `not` and `if`, as under `properties`, a widened key's
schema reads `null` as absence), while a `null` list element stays refused.
This reads 2.1's "every schema of an array's items keep their meaning" as the
item schema itself, so that keys inside list elements are removable at any
depth, as the delta requires; Section 4's helpers drop `null` keys inside list
elements to match. The result shares nothing with its input. No import added.

### Task 2.2: detailed implementation evidence

Unit tests under "null removal", structural (the kit has no JSON Schema
validator; Section 3's drift tests validate with `Draft7Validator`): typed
section and field, open section, settlement mechanism and `priority`, a
delivery instance named for its sink and one under `additionalProperties`, a
key under `dependencies`; refused keys (secret, role-inapplicable, retired,
misspelled `sink`) stay `false`; an `Optional` field unchanged; a list's item
schema not widened while its keys are; each widening form (an `anyOf` alone,
`enum` or `oneOf` beside a type, `$ref`, `not`, an already-null `enum`, `{}`);
keys under `not`, `if`, and `then`; root and input untouched, and no result
sharing a node with its input or another result. With the refused-key skip
removed, two tests failed; restored.

### 3. Both storefronts accept `null` in the definitions they write: implementation and review notes

Notes: `make helm-values-schema` is outside the unattended implement step's
permissions; the owner ran it. Each refusal test pairs the config refused with the key
stated as `null` with the same config accepted without the key, since jsonschema reports
a `false` schema under `patternProperties` at the parent's path, not the key's. The
fresh-context check's evidence findings are fixed (the 3.3 record, VM's counts);
the section's header does not name the bare-metal `pyproject.toml` and `uv.lock`, which
3.2's note discloses. The VM generator prints a `UserWarning` that
`agent_id` is unset when run outside a configured storefront; it does not affect the
definition.

### Task 3.2: detailed implementation evidence

Unit, validating with `Draft7Validator` over each storefront's generated
definition: a `null` section, field, delivery instance, and key inside a list
element validate; a wallet private key in two spellings, a retired key (VM's
`claims_sweep_interval`; for bare metal, which keeps no retired catalogue, a key
it does not read, `negotiation_timeout`), and a secret sink setting stay refused
as `null`. Moved assertions: a typed sink table's `^sink$` is now
`anyOf: [const, null]`; bare metal's `poll_interval` type is
`["number", "null"]`. The bare-metal storefront gained `jsonschema>=4.0` in its
`dev` group, relocked with `make lock PROJECTS="domains/bare_metal/storefront"`.
The drift tests pass against the regenerated files.

### Task 3.4: detailed implementation evidence

`make test-storefront` (VM unit and integration): passed, 1103 unit and 448
integration. `make test-bare-metal` (domain, storefront 440, buyer, provisioning
adapter): passed. In place of rerunning `make helm-values-schema`, which this
step may not run, each storefront's drift tests run its generator's `check`,
which compares the parsed `storefrontServiceConfig` of each committed file (not
its text or other definitions), and pass. `make check-packaging` passes after the relock.
`make test`: every suite passes up to `test-deployment-packaging`, which fails on
the same thirteen render tests; two of them now get past the generated schema
and fail in the template instead (`test_a_differently_spelled_section_…` and
`test_typed_fields_…`, on the duplicate-spelling check, since the surviving
`null` key still counts as a spelling), as expected until Section 4's helper
drops it. End-to-end confirmed: none.

### 4. The charts absorb a `null`: implementation and review notes

Notes: the fresh-context check found the planned schemas narrower than the delta's "a
value of an agent" (an agent's `secret`, `component`, `configMapName`,
`alkahestAddressBook`, `port`, and `identity` stay null-refusing); recorded under
`design.md` "Open questions" for the owner rather than widened, since D2 and 4.4 name
only three. It also found tests that removed nothing an earlier layer stated, and a
startup check its removal did not cause; each now states the value in one layer and
removes it in the next (`_render_layers`, `_render_umbrella(stated=…)`). The `make test`
run above preceded those test-only fixes; `make -C helm test-render` was rerun after
them and passes. Helm applies a parent's `null` to a subchart only where the
subchart's defaults define the key; closeout 6.9 now corrects the deployment doc's
sentence that says otherwise.

Implementation round 1 fixes (`reviews/22-implementation.triage.md`):
- 22 F1, the owner's option (a): every value of an agent accepts `null` in
  `helm/charts/storefront/values.schema.json` and the umbrella's `storefrontAgent` —
  `port`, `component`, `configMapName`, `identity`, `secret` with `createSecret`,
  `secretName`, and `configKey`, and `alkahestAddressBook` with its three keys; refused
  keys and the keys inside `identity` unchanged. `storefront.agents` and
  `arkhai.storefrontAgents` refuse an agent stating no `port` or no `identity` once its
  nulls are removed ("storefront agent <name> states no <key>"); without it a removed
  `identity` failed on a template nil pointer, as breaking the check once showed. The
  delta's requirement and two scenarios ("An overlay removes a chart-level agent
  value", "… an agent's port or identity") and D2 say so. Render tests: each removal
  falls back as if never stated (component, ConfigMap name, address book and its keys,
  runtime overlay and `secretName`), and a removed `port` or `identity` is refused
  through the umbrella and by the storefront chart alone; the umbrella's own refusal is
  worded the same, so which one fires there is not asserted.
- 22 F2: the removal test compares against Carol rendered with Bob never stated,
  through the storefront chart alone (`_render_chart`, with the umbrella's globals), the
  whole manifest, checksums included; the checksum-stripping `_agent_documents` is
  gone. The chart's checksums are unchanged: per-agent rollout is out of scope.
- Evidence: `make -C helm test-render` (chart render tests and chart-to-loader checks,
  Helm v4.3.0+gbec5b06): every assertion and Python render test passes, the three new
  or rewritten ones included. `make check-packaging`: passes. `make test`: passes,
  through `test-deployment-packaging`. `make check-change`: passes. Fresh-context check:
  no blocking findings; fixed its three test gaps (a positive check before the absent
  overlay, a removed `secretName` alone, a removed address-book `configMapName`) and two
  delta wordings (the refusal names the agent; a removed Secret or ConfigMap name
  mounts none); the umbrella-refusal gap is recorded in the test's docstring rather than
  given a distinct message. `make check-comment-hygiene`: passes.
  End-to-end: none owed; the fix commit's validation reruns `make validate-helm`.

### Task 4.5: detailed implementation evidence

Chart render tests, standard library only. Storefront: Bob removed beside
Carol renders no Bob Deployment, Service, ConfigMap, or PVC (no Secret renders
for any agent, the schema pinning `createSecret` false); through the storefront
chart alone, a release stating Bob and removing him renders exactly the manifest
Carol renders with Bob never stated, rollout checksums included (22 F2); removing
the only agent is refused naming `agents` through the umbrella
(which of the two refusals Helm reports first is not asserted, so the umbrella's
own is not shown to fire there) and the chart alone; a defaulted setting Bob
states, removed at depth, is absent, as are `null` keys in a list element and an
untyped section, and the document holds no `null`; `db_path`, `port`, and
`registry.urls` stated by one values layer and removed by the next carry the
release's values; Bob's `Settlement` in the local release, which starts, removed,
renders absent and the storefront's startup refusal names `[Settlement]`;
removed trust is refused naming it; a wallet private key, a `name`, `agentId`,
and `config.seller` stated as `null` are refused naming their paths. Bare metal:
through the umbrella a key the release states, removed at depth, is absent with
no `null` in the document, and removed trust is refused. Topology: removing the
bare-metal storefront's stated sites in a later values file is refused by the
umbrella's smoke-test profile; without its `null` removal the render succeeds
(checked by removing it once). The three wording tests assert the refused
value's path, dotted or as Helm's JSON pointer, or the property and its parent,
plus a non-zero exit. With the helper keeping a `null` agent, four storefront
tests failed; restored.

### 5. CI pins Helm, and every render run names its Helm: implementation and review notes

Notes: the version prints after `helm dependency update`, before the first render. The
fresh-context check found the script's comment claiming a merge difference between Helm
releases that the change never established; reworded to the reason D4 gives. Closeout
6.9 must replace `TESTING.md`'s "rely on the pinned Helm of the release environment for
anything recorded as evidence", which now reads as the evidence-only-on-the-pin claim D4
rules out.
CI's `release · deployment contracts` job runs `test-render` with no loader interpreter,
so CI never runs the chart-to-loader or startup checks; only local and validation runs
do. The four CI-only storefront pytest failures (5.3) belong to no change on this
branch; 6.8 should not count them against this change. On the owner's word they are
recorded as two rows of the index's "Unowned work left by this campaign" table.
Triage of the orchestrating session's observations (28): R1 and R3, the workflow-tooling
defects this section met (CI evidence no implement session can produce; a one-run grant
that reaches only a resumed run), are recorded with the owner's settled direction as two
more rows of that table, for `parallel-change-workflows`. R2: `[steps.triage]` in
`.claude/change-steps.toml` gains implement's five rules it lacked (`make -C * dist*`,
`make init*`, `make -C * init*`, `make validate-*`, `helm version*`), made by the
orchestrating session on the owner's word. Checks: `scripts/tests/test_change_workflow_steps.py`
(unit) 32 passed; `make test` passed; `make check-packaging`, `make check-comment-hygiene`,
`make check-change-index` and `make check-change` passed. The fresh-context check found
no leak and every cited path resolving; fixed: the new rows now give full test paths and no
longer read as owned; declined: a note in `parallel-change-workflows`' proposal, since the
owner chose the table as the hand-off.
Pre-closeout triage (43 F1), comments only: both charts' document-renderer comments and
`helm/values.yaml`'s note on `storefront.agents` say `config` passes through with its
`null` keys removed, not unchanged; both storefront charts' `dropNulls` comments state the
merge rule as the supported Helm release's behaviour, naming no version (D4). Checks:
`make -C helm test-render` (chart render tests) passed, printing `helm v4.3.0+gbec5b06`;
`make test` passed; `make check-packaging` and `make check-change` passed. The
fresh-context check found the edited comments accurate and free of history or private
detail; fixed: the rewrapped paragraphs ran past the surrounding width, and the storefront
renderer comment's relative clause made its colon ambiguous; declined: the pre-existing
"Helm cannot remove a subchart's default agent" in `helm/charts/storefront/values.yaml`,
outside 43 F1. The owner directed the fix commit's validation as `make validate-helm`, and
is to waive the pipeline's part for the known VM buyer failure (40 V1).

### Task 5.3: detailed implementation evidence

`make -C helm test-render` (chart render tests): prints
`helm v4.3.0+gbec5b06` after `helm dependency update` and before the first
render, and passes. `make test-release-tooling` (release tooling unit tests):
1090 passed. `make test`: passes, its render step printing the version first.
Not run here: CI on the pushed branch, since this step may not
push; validation pushes the branch and records that run, and 5.3 stays open
until it does. End-to-end confirmed: none.
Correction: CI was not recorded by validation; `tests.yml` runs on a push only
to `dev` and `staging`, so the owner dispatched it at `ca8f5f309` (run
39625394342), recorded here. Its `release · deployment contracts` job
passed: `azure/setup-helm@v4` ran `with: version: v4.3.0` and installed
v4.3.0; `make test-release-tooling`'s step passed 1090; `make -C helm
test-render` printed `helm v4.3.0+gbec5b06` after `helm dependency update`,
before the first render, and passed. The job sets neither loader interpreter,
so five checks print `skip:`: the VM storefront chart's startup check twice and
its loader check once, the bare-metal chart's loader check, and the topology
test's bare-metal loader check. The local `make test` at `ca8f5f309`, run while
recording this, printed no `skip:`, so those checks ran there. On dev's run
39614790584 the same job fails at that render step.
Pre-existing and outside this change: the run's `py · vms-storefront` and
`py · bare-metal-storefront` jobs fail at pytest. They fail the same tests
with the same errors on dev's run 39614790584, and this change touches neither
the test files nor the code they test. The VM storefront has three `TimeoutError`
failures in `tests/unit/test_loop_gate_wiring.py`
(`test_a_pause_during_the_idle_wait_reaches_every_gate`,
`test_a_failing_cycle_is_recorded_and_the_loop_keeps_running`,
`test_the_sweep_is_registered_while_contact_exchange_is_composed`): 3 failed
and 1546 passed here, against 3 failed and 1544 passed on dev. The bare-metal
storefront has one failure, `tests/test_publication_cli.py::
test_abort_all_is_not_previewed`, whose expected `--abort-all cannot be combined
with --dry-run` is not found in the Rich-formatted usage error: 1 failed and 439
passed here, against 1 failed and 437 passed on dev. The extra passes on this
branch are its new `test_values_schema` tests. Both suites passed locally under
`make test`, so these failures happen only in CI; no change on this branch owns
them.

## Closeout dispositions — 2026-10-21

The owner directed: "Waive any further validation due to a pre-existing e2e bug."
This continues the waiver already recorded in triage 40 and after pre-closeout
triage 43. No new test suite, packaging build, Helm deployment or end-to-end
pipeline is run for closeout. Documentation, citations, task/index consistency
and the pinned OpenSpec archive checks still run to make the archive coherent.
Waived checks are unrun, not passed.

The last fully passing validation is 30-validation.md at `ca8f5f309`, pipeline
39623742125. The later pipeline 39634190724 at `2d3fb01f2` failed in the VM
introduction CLI scenario; triage 40 attributes it to duplicate root `settlement`
registration by the VM and bare-metal buyer plugins, already owned by
`unbacked-bare-metal-listings`. The final comment-only code commit `f6f091a83`
passed Helm validation, recorded in its existing local Helm summary and workflow
record 66: render on Helm v4.3.0+gbec5b06, deploy, `contracts`, and
`e2e_alkahest_escrow_codecs`. No pipeline result is claimed for that commit.
Eleven compose-only scenarios were not served by that Helm run. The unchanged
code after that commit and the owner's waiver are the basis for closeout;
this is not a new passing validation record.

The previous session left only the index's `in closeout` edit uncommitted. The
owner's instruction to finish closeout authorizes continuing that edit here.
The pre-closeout triage's Next is Advance. No production code needs changing.
The index remains `in closeout` after archival; the closeout review and triage
precede archive cleanup, which releases dependents and sets `archived`.

The operator guide and deployment-state architecture companion also described
pass-through as unchanged. They now say null-valued keys are removed, aligning
existing prose with D2 rather than introducing a new design decision. No
repository-wide architecture, capability-index or roadmap change is required.
The campaign graph does not contain this repair and stays unchanged.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| D1: Helm merge diagnosis | Historical evidence retained in this design; not a permanent architecture claim |
| D2/D5: keyed agents, recursive null removal, empty-map and missing-port/identity refusals, refused keys remain refused | `openspec/specs/deployment-state/spec.md#requirement-a-storefront-chart-passes-service-configuration-through` (merged by archival); `docs/development/DEPLOYMENT_AND_CONFIG.md#storefront-agents-pass-through-configuration` |
| D2: chart normalization and generated-schema rationale | `openspec/specs/deployment-state/architecture.md#settlement-configuration-cutover`; `docs/development/TESTING.md#chart-render-tests` |
| D3/D4: CI owns the supported Helm pin; render logs identify the version without enforcing it | `docs/development/TESTING.md#chart-render-tests`; `docs/development/DEPLOYMENT_AND_CONFIG.md#storefront-agents-pass-through-configuration` |
| Roadmap | No affected goal or gap; `docs/development/ROADMAP.md` unchanged |
| Campaign index | `openspec/changes/README.md#unblocking-work--the-local-end-to-end-stack`; archive link with status `in closeout`, no graph or dependent-row changes |
| Validation waiver | Change-local evidence above and in closeout tasks; not promoted as system behavior |

## Closeout review 48 corrections

The owner accepted 48 F1 and 48 F2 and directed Advance after the corrections.
48 F1 clarifies D2/D5 without changing behavior: only null-valued mapping keys are
removed, including keys inside list elements; list elements keep their item
schema's meaning. The permanent deployment-state requirement and this archive's
delta are corrected together, and D2/D5's wording above is aligned. The operator
guide already states that distinction.

48 F2 removes the false Helm limitation from the comment in
`helm/charts/storefront/values.yaml`. The comment now states that the chart ships
no agent and the umbrella values declare the release's agents. This is a
comment-only correction explicitly directed by the owner while the change is
archived. It supersedes the earlier scope-based deferral in triage 43.

The correction plan touches only those two spec files, this design, the chart
comment, the closeout task notes, and the index's current-state note. It changes
no template logic, schema, dependency, or runtime behavior. Static change checks
are run; the owner's existing waiver continues to cover further test suites,
packaging builds, Helm deployments and pipeline runs. No new passing validation
is claimed. The owner chose Advance because these are corrections to the
existing design rather than a changed representation or authority boundary.
