# Capacity-bound checkpoint

Observed 2026-11-07 from base `752eaf468`, draft PR #351. This completes
task 2.2 only. Recurring option publication, acceptance-time horizon enforcement
and buyer disclosure remain in 2.3 onward.

Bare metal's positive-maximum rule for reserved publication, recorded below, was
replaced before the change landed: in both domains no positive maximum means no
relative limit; see `openspec/specs/storefront-publication/spec.md`, "Unbounded
recurring candidates close independently". The sections below describe the evidence
as observed.

## Behavior

- Pool HTTP writes and document validation recognize optional
  `policy_tags.capacity_bounds.<offering_mode>` with
  `max_duration_seconds` and `available_until_utc`.
  Relative values must be integers, not booleans/coercible text/floats. Nonpositive
  values explicitly remove that tier's relative limit without falling through.
  Absolute values must be aware UTC ISO datetimes (or UTC datetimes from TOML),
  not naive dates, epochs or nonzero offsets; serialization uses Z.
- Each bound resolves independently: override > pool mode hint > configured
  default. VM preserves model-specific pricing hints/defaults beneath the new
  mode hint. A malformed stated bound holds derivation with
  `capacity_bounds_unreadable`, never a guessed lower-tier limit.
- Both domains' listing and override models preserve the absolute term.
  Shared storefront storage adds a nullable column; changing a bound refreshes
  the same capacity/shape identity. Explicit null clears either bound, while an
  omitted update leaves it unchanged. Publication carries the absolute bound
  through the existing opaque listing-level registry extra, outside the option
  and listing resource. Bare-metal resource payloads no longer copy the relative
  maximum; its codec reads listing-level bounds from the envelope and existing
  seller admission retains the relative guard. Old resource copies remain
  readable but are omitted from public responses. No accepted Agreement or lease
  is rewritten.
- Bare-metal reserved publication still requires a positive relative maximum,
  even if it has an absolute date. Its minimum/maximum conflict retains the
  `pool_override_terms_conflict` diagnostic. The shared override kit's
  contribution now judges projection-dependent term conflicts against the
  write's already-fetched live generation before persistence. This avoids both
  ignoring a higher-priority pool maximum and refusing a corrected live hint
  because the storefront still holds a malformed older projection. No extra
  network request or lease operation was added.
- The typed bare-metal configuration and generated Helm values schema include
  `pricing.default_available_until_utc`. Both packaged settings show the
  optional default. VM's domain dependency and affected locks are refreshed
  through repository tooling.

## Owned first-use setup and replay

The target is an invocation-owned in-process storefront app in the verifier's
checkout, with a temporary real SQLite database. The existing harness doubles
site projection, chain and registry boundaries. Persona: signed administrator
using the fixtures' deterministic public development signers, never public-network
credentials. No secrets, login, ignored seed files, containers, tunnels, external
targets or resident servers are required.

The script opens the typed administrator publication/override/read surfaces
directly and reads system status before driving publication. Readiness observed
is that in-process app's signed HTTP surface, not a deployed lane or remote
authority. The lifespan and temporary directory close on exit.

From the repository root:

```sh
make dist-ci
make -C domains/vms/storefront reinit
make -C domains/bare_metal/storefront reinit
(cd domains/vms/storefront && env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy uv run --frozen --no-sync python ../../../openspec/changes/archive/2026-11-12-negotiate-open-ended-compute-terms/capacity_bounds_probe.py vm)
(cd domains/bare_metal/storefront && env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy uv run --frozen --no-sync python ../../../openspec/changes/archive/2026-11-12-negotiate-open-ended-compute-terms/capacity_bounds_probe.py bare)
```

Both entry points were personally run. The probe confirms strict parsing,
independent tiers, nonpositive masking, typed publication/readback and override
writes, unchanged listing identity, unchanged listing on malformed hints, and
absolute-term placement in recorded registry publication requests. VM additionally
withdraws both persisted bounds and republishes without the absolute extra.
Bare metal confirms the preserved reserved-bound hold after an explicit negative
relative override. The probe is temporary change evidence, not a collected
permanent acceptance suite. Recorded registry sends are not deployed registry
persistence or historical-signature evidence.

## Existing regression evidence

After the wheel rebuild, each package was refreshed using its declared
`make reinit`. Commands run from the named package using
`uv run --frozen --no-sync pytest <targets> -q`; the storefront commands
clear proxy variables with the same `env -u ...` prefix as the probes above.

| Package | Existing targets | Result |
| --- | --- | --- |
| `kit/resource-pools-contracts` | `tests/unit` | 426 passed |
| `domains/vms/domain` | `tests` | 60 passed |
| `domains/bare_metal` | `tests` | 224 passed |
| `domains/vms/storefront` | `tests/unit/test_pricing_resolution.py tests/unit/test_pool_descriptors.py tests/unit/test_vm_pool_override_contribution.py tests/unit/test_publication_terms_composition.py tests/integration/test_publication_loop.py tests/integration/test_pool_overrides_api.py tests/integration/test_listing_identity_carryover.py` | 196 passed |
| `domains/bare_metal/storefront` | `tests/test_pool_override_terms.py tests/test_pool_overrides_api.py tests/test_publication_cycle.py tests/test_http_publication_rates.py tests/test_publication_cli.py tests/test_http_system.py tests/test_migrations.py tests/test_config_loader.py tests/test_values_schema.py tests/test_negotiation.py tests/test_negotiation_runtime.py tests/test_http_negotiation.py tests/test_persistence.py` | 281 passed |
| `kit/pool-overrides` | `tests` | 81 passed |
| `core/storefront` | `tests/unit/test_listing_models.py tests/unit/test_identity_migrations.py tests/unit/test_listing_resource_migration.py tests/integration/test_domain_binding_migrations.py tests/integration/test_listing_closure.py tests/integration/test_rate_structure_column.py` | 45 passed |
| `kit/resource-pools` | `tests/unit`, then `tests/integration/test_resource_pool_service.py` | 54 + 87 passed |

The unit suites cover pure vocabulary/resolution; the storefront integration
targets exercise typed application routes and real SQLite with injected external
boundaries. The pool service integration uses its real persistence, not a deployed
site. No permanent tests were added. Kept expectations now recognize the absolute
listing term and D5's deliberate change from fallback/refused-zero to strict
validation/nonpositive-unlimited. The kept bare-metal response/comparison
expectations locate the relative maximum at listing level rather than inside
the resource; negotiation/persistence suites retain the existing admission guard. The shared-service fixture supplies the added
projection judgement. No unrelated assertions were removed or weakened.

Targeted typing from `kit/resource-pools-contracts`:

```sh
uv run --frozen --no-sync --with mypy mypy --follow-imports=silent --ignore-missing-imports src/market_resource_pools_contracts/capacity_bounds.py
```

Result: one source file clean, imported code followed silently and missing stubs
ignored; not whole-repository typing.

Packaging and change validation: `make check-packaging`,
`make check-change CHANGE=negotiate-open-ended-compute-terms` and
`bunx @fission-ai/openspec@1.14.0 validate negotiate-open-ended-compute-terms --strict`.
The packaging gate includes fresh wheels, locks, architecture and amount-read
guard; the change gate includes comment hygiene and documentation checks.

## Resolved attempts and limits

Initial kept expectations treated malformed VM duration hints as fallback,
zero override bounds as invalid, and exact term inventories as lacking the new
field. These expectations now follow the intended D5 behavior. An initial
minimum/maximum hold used a new generic reason; the existing conflict diagnostic
was restored instead. First-use exposed the stale-projection write check, which
was repaired and re-driven against the live projection.

The initial probe lacked the VM harness's explicit domain selection, attempted
an empty override instead of the delete operation, and omitted the bare-metal
fixture's live site-client facade. The committed probe supplies the same public
configuration/site seams as the existing fixtures and uses the typed delete API.
A guessed `tests/test_config.py` target did not exist; the passing targets
are `test_config_loader.py` and `test_values_schema.py`.
These are resolved invocation/fixture mistakes, not passing attempts. The first
change-gate run also caught packet links before this packet was written and missing
reasons for mode-specific lazy imports in the probe; both were corrected before
rerunning the gate. Existing agent-id and websocket deprecation warnings remain.

No deployed E2E, real provisioning, approval, recurring helper, rate servicing,
acceptance-time bound enforcement, complete CLI disclosure, independent review,
final rebase, promotion or archive is claimed. No external resources were started.
Resume at 2.3; bare-metal decoding already merges the listing-level bounds, but
3.2 still owes acceptance-time horizon enforcement against both.
