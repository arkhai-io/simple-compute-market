# Give a negotiated shape one form

## Why

A VM buyer states a capacity shape in two forms, chosen by where in a negotiation it
speaks.

- **Opening.** A flat, partial mapping, `compute_resource`, of quantities only, in the
  compute family's flat names. The buyer fills it from
  `--shape gpu_count=1,vcpu_count=8,ram_gb=64`
  (`domains/vms/buyer/src/arkhai_vms_buyer/opening_shape.py`, `parse_shape_option`), and
  the seller takes every quantity it omits from the listing
  (`domains/vms/storefront/src/market_storefront/negotiation_runtime.py`,
  `prepare_requested_shape`).
- **A later round.** A whole family-grouped shape, such as
  `{gpu: {model: A100, count: 1}, cpu: {count: 8}, memory: {gib: 64}}`, as the
  provision envelope's entire payload. A family it omits is not taken from the listing
  (`negotiation_runtime.py`, `_decode_vm_revised_terms`).

`negotiation-protocol`'s "A round may revise the capacity shape" requires the
family-grouped form of a round after the first, and of a first round says only that a
shape differing from the listing's is evaluated, not refused.

Both forms travel under one envelope, `kind: compute.v1`, `version: 1`. Its payload
therefore has two schemas, told apart by round position alone: the opening's is
`VmProvisionPayload`, with the lease's duration, start and key beside `compute_resource`
(`domains/vms/domain/src/arkhai_vms/provision_terms.py`), and a revision's is a shape the
capability codec validates.

Whatever the buyer sent, the seller records the effective terms flat. `compute_resource`
then holds the flattened quantities and attributes, with the region. That flat mapping
is what each seller quote stores, what the accepted Agreement's provision terms carry,
what the settlement order is built from
(`domains/vms/storefront/src/market_storefront/services/vm_job_spec_service.py`,
`agreed_vm_order`), and what the buyer's run log keeps for a resumed run
(`domains/vms/buyer/src/arkhai_vms_buyer/buy_cli.py`).

Nobody meets the second form today. No shipped buyer command sends a revised shape: the
core buyer applies one only where a move's proposal carries it
(`core/buyer/src/core_buyer/negotiation_client.py`), and nothing in the VM buyer
produces one. A buyer states a shape in the flat form only, which is also the form it
reads in a listing and writes in a registry query. Bare metal negotiates no shape.

Two things make it real:

- **A buyer tool sends a counter-shape.** `publish-shape-bounds` publishes a listing's
  constraints in the family-grouped form so that a buyer can find a shape its seller
  would sell. A buyer command built on it reads a range in one form, opens in a second,
  and counters in the first.
- **A second implementer of the buyer protocol appears.** It has to learn that one
  version of the envelope means two payloads.

## What Changes

The change decides the form, or forms, a buyer states a shape in across a negotiation,
and writes that down as the provision envelope's contract. Nothing below is settled but
that the question has an owner.

### Decided by the owner

- **D1: a change of its own.** The form of a buyer's opening shape is not left as an
  unowned row in Goal 2's campaign, and it is not part of `publish-shape-bounds`.

### Open for design, not decided here

- **Whether an opening may, or must, be family-grouped**, and whether a family-grouped
  opening is partial, as the flat opening is, or whole, as a revision is.
- **Whether the flat opening stays accepted beside it**, and for how long. A resumed
  run reopens with the flat shape its run log recorded, so what a run begun before the
  change is owed is part of the answer.
- **Whether Agreements and stored quotes go on recording flat effective terms.** They
  are retained and signed, and the flat form is the one a capacity claim is built from.
- **The envelope's version.** The provision envelope carries its own kind and version,
  so a new opening form is a new version each party names as accepted, not an edit to
  `compute.v1` version 1 (`docs/guidance/engineering/versioning.md`, "A versioned
  contract is never changed in place"). Whether version 1's two payloads are then told
  apart by anything but round position is the same question.
- **What `marketplace-v0.4.0` is owed.** Its buyers open flat under version 1, its
  storefronts accept that and a family-grouped revision under the same version, and
  Agreements retained from it carry flat terms. A released buyer is not owed a later
  storefront; a retained Agreement must still be read.

## Capabilities

### Modified Capabilities

Provisional; settled in design.

- `negotiation-protocol`: "A round may revise the capacity shape", which states the form
  of a revision and not of an opening.
- `vm-storefront-fulfillment`: "The agreed shape is reserved", only if what an accepted
  Agreement records changes.
- `buyer-orchestration`: only if `--shape` changes what a buyer types.

### New Capabilities

None.

## Non-Goals

- Respelling the compute family's flat dimension names. They stand, in a listing, a
  query, a claim and a capacity declaration
  (`openspec/specs/market-composition/architecture.md`, "The compute family
  vocabulary").
- The term a listing publishes its shape constraints in. `publish-shape-bounds` owns it.
- Whether the site would admit a requested shape, and what a buyer may ask above the
  advertised one. `negotiation-capacity-feasibility-probe` owns both.
- An automated counter-shape policy for a buyer or a seller.
- Bare metal, which negotiates no shape.
- The form of a capacity claim, a reservation or a capacity declaration, which are flat
  by design.

## Impact

- Provisionally: `domains/vms/domain` (the provision envelope and its codec), the VM
  storefront's negotiation runtime, the VM buyer's `--shape` and its run log, the core
  buyer's effective-terms seam, and `docs/buyer-quickstart.md`.
- No site, registry or provisioning behaviour is expected to change, and no migration
  is expected. Compatibility is owed to the newest release tag when the design is held;
  nothing proposed here alters a form `marketplace-v0.4.0` carries.
- Nothing here needs a GPU, and nothing touches the Ansible layer or how an adapter
  executes it, so no real-host run is owed.

## Dependencies and Related Changes

- None gates this change. Its activation condition is stated in the change index.
- `publish-shape-bounds` publishes the family-grouped term a buyer reads a seller's
  ranges from. A buyer command that then sends a counter-shape is what this change
  waits for; neither change depends on the other.
- `negotiation-capacity-feasibility-probe` edits the function that expands the flat
  opening, `prepare_requested_shape`. The two share a file and not a subject; whichever
  lands second reverifies against the other.
- `settle-capacity-claim-vocabulary` records that the flat dimension names stand. This
  change takes that as given.
- **Builds on**, archived: `negotiation-driven-capacity-resize`, which carried a revised
  shape as a child of `proposal` in the family-grouped form and kept the flat opening
  (its design, D1).

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification: `negotiation-protocol`
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

To be determined at design completion. Expected destinations: the `negotiation-protocol`
specification and its companion's "Negotiating a shape";
`openspec/specs/market-composition/architecture.md`, "The compute family vocabulary",
which lists the shape a buyer opens a negotiation with among the uses of the flat
names; and `docs/buyer-quickstart.md`.
