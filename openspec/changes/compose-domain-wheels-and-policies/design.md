## Context

`domains/vms/{listings,negotiation,settlement}` is a namespace with no owning
distribution. Its storefront consumer obtains it by source-tree copy plus
`PYTHONPATH`; its buyer consumer, which ships as a wheel and as a frozen
binary, reassembles it through a per-file `force-include` table that drifted
and broke `market buy`.

The manifest cannot simply be corrected. Directory-level mapping was tried and
rejected on evidence: `force-include` ignores `exclude`, so a directory mapping
ships whatever is present at build time — verified by placing a scratch file in
the source directory and finding it in the wheel, with and without `exclude`
patterns configured. That trades a missing-module defect for an
unbounded-contents defect.

The manifest exists because two things force it. The buyer's dependency is
inflated from two modules to twenty-four by eager cross-package facades. And
negotiation policies resolve through a mutable module-level registry whose
contents depend on import order, which is the reason the storefront needs the
source tree present at all.

`domains/bare_metal` is the counter-example already in the repository: it
imports middlewares as modules, composes them as a literal list, and consults
no registry.

## Goals

- One distribution owns every shipped module; no namespace is assembled from
  another project's files.
- Policy names resolve against a value composed once at startup, not a global
  mutated by import side effects and by resolution itself.
- A broken install, an unknown policy name, and a duplicated policy name each
  fail loudly, before a role serves requests.
- Kit acquires no knowledge of domains. Domains choose their own discovery.
- A future domain's negotiation module is kit imports plus its own guards plus
  an ordering.

## Decisions

### Kit owns the source protocol; the domain owns the choice of sources

Kit defines `NegotiationPolicySource` — `describe()` and
`load() -> Mapping[str, NegotiationMiddleware]` — plus concrete
implementations: an inline source for policies known at build time, an
entry-point source, and a directory source. Implementations are values that
return mappings; they mutate nothing.

The protocol lives in kit rather than core because the vocabulary being loaded
(`NegotiationMiddleware`, `NegotiationContext`, `NegotiationDecision`) is
kit's. Core owning it would require core to depend on `arkhai-kit-policy`,
which it does not today.

A domain returns the sources it permits. A domain that never wants filesystem
loading returns no directory source, and no operator setting can introduce
one. An external team wanting policies from a remote store implements the
protocol; kit gains an implementation and the protocol is unchanged.

### The catalogue is immutable, built once, and validated at build

A builder accumulates loaders; `build()` loads every source, validates that
each offered value is callable, rejects duplicate names with both providers
named, and returns a frozen catalogue. Resolution is then a pure lookup that
mutates nothing.

`build()` is the single point where the failure modes that hid the packaging
defect become visible. Load failure is fatal: a distribution that declares a
policy and cannot supply it is a broken install, not a policy to skip.

### The catalogue is injected, not a module-level singleton

The composition root builds one catalogue and injects it. A static singleton
was considered and rejected. This subsystem already carries three global flags
(`_FILE_DISCOVERY_TRIGGERED`, `_FILE_POLICIES_DISCOVERED`, and a `force`
parameter) that exist only to defeat the caching global state made necessary,
and the E2E suite composes buyer and storefront paths in one process, so one
global catalogue would have to be the union of two roles' policies — which
silently defeats strict conflict detection. Tests must also be able to compose
deliberately invalid catalogues to assert the new errors.

`default_seller_round_hook` already takes four injected collaborators. The
catalogue becomes the fifth and replaces `extra_policy_paths`, which moves up
into composition where sources are chosen. Net signature width is unchanged.

### Name conflicts are strict, with no override mechanism

Two providers offering one name is an error naming both providers. There is no
`overrides` field. A domain that wants different behaviour composes different
sources — including omitting kit's own set — which is a more honest escape
hatch than shadowing, and keeps every error message accurate about provenance.

### `NEGOTIATION` is optional and means one specific thing

The capability declares: *this domain offers named policies that operator
configuration may reference*. It does not mean "this domain negotiates".
`bare_metal` negotiates and declares nothing, because its chain is fixed and
exposes no names. `market-composition` already requires that capability
absence be valid and require no placeholder implementation.

### The namespace is split by consumer, not relocated wholesale

Moving `domains/vms/{listings,negotiation,settlement}` into one shared wheel
would preserve the shape that caused the defect: a shared distribution
containing modules with exactly one consumer. Traced consumption instead
shows roughly fifteen modules used only by the storefront, three used by the
buyer, and `listings/models` used by three consumers. Storefront-only modules
move into `market_storefront`; the buyer's formatting helpers move into the
buyer; genuinely shared models move into `arkhai_vms`. `force-include`
disappears rather than shrinking, and the eager facades disappear because
after the split nothing re-exports across a package boundary.

## Alternatives Rejected

- **Add the five missing manifest entries:** rejected as the resolution,
  though viable as a stopgap. It fixes the symptom and leaves the manifest a
  defect generator, the namespace unowned, and the storefront dependent on a
  copied source tree.
- **Directory-level `force-include` mapping:** rejected on measured evidence.
  `force-include` bypasses `exclude`, so the mapping ships arbitrary files
  present at build time.
- **A test asserting the manifest matches the source tree:** rejected as the
  resolution. It converts a runtime import error into a named test failure,
  which is a real improvement, but it institutionalises the manifest rather
  than removing the need for one.
- **Making the facades lazy via module `__getattr__`:** rejected. It would
  have stopped the buyer importing `reconciler` without shipping fewer
  modules, and it would have silently broken the `market_policy`
  compatibility monkey-patch and any other import side effect. Hiding a
  packaging problem behind deferred instantiation is the same category of
  error as importing functions instead of modules.
- **Carrying policies on `MarketDomainContract` with kit resolving through
  it:** rejected. That requires `arkhai-kit-policy` to import `arkhai-core`,
  teaching kit that domains exist, which `market-composition`'s from-below
  requirement forbids. Structural typing achieves the same startup validation
  with no new dependency in either direction.
- **Declaring the existing entry-point group and stopping there:** rejected as
  the whole answer. It removes import-order dependence but leaves one global
  registry, no conflict detection, and no answer for directory discovery. The
  entry-point mechanism is retained as one source implementation.
- **A static singleton catalogue:** rejected for test isolation and for
  multi-role processes; see the injection decision above.
- **Relocating the namespace into one shared wheel:** rejected; see the split
  decision above.
- **Folding this into `remove-relative-uv-sources`:** rejected. That change
  targets parent-path `tool.uv.sources` entries and is unstarted; this targets
  an unowned namespace assembled by file manifests. Different mechanisms.

## Risks

- The split touches 143 import sites across two Dockerfiles, `compose.yml`,
  and four packages. Mechanical, but broad, and the storefront's policy
  discovery currently depends on the source tree the split removes.
- Strict composition will surface any policy name a domain resolves but does
  not own. `apicredits` was verified independent — all four of its guards are
  its own and its three shared names come from kit — but the check must be
  repeated after the split rather than trusted from this audit.
- `configured_buyer_policy` deliberately tolerates an unknown policy name when
  rendering `market --help` and is strict when loading a chain, because
  "silently negotiating under a policy the user never chose is worse than
  failing." Converting that registry must preserve both modes; a uniform
  strict conversion would break `--help` on a bad config.
- Removing unconditional scanning of `~/.config/arkhai/policies` is a
  behaviour change for any operator relying on it. No repository
  configuration sets `extra_policy_paths` and its declared default is empty,
  but the path is scanned today regardless of that setting.

## Verification Strategy

- Build `arkhai-vms-buyer` and assert every module its shipped code imports
  resolves inside the wheel, with no file present that no distribution owns.
- Compose a catalogue from two sources offering one name and assert the error
  names both providers.
- Compose with a source that raises and assert startup fails rather than
  logging and continuing.
- Configure a chain naming an unavailable policy and assert the error lists
  what is available, without instructing the reader to import any package.
- Compose buyer and storefront catalogues in one process and assert they are
  independent values.
- Run the VM and API-credit storefront negotiation suites and the E2E buyer
  CLI scenario that currently fails at stage B4.
- Start the VM storefront from an image built without `COPY domains/` and
  assert its configured chain resolves.
