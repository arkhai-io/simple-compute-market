# Harden a relay against hosts its operator does not trust

The change keeps its directory name, `harden-shared-relays`, from when it aimed at
a relay shared between operators.

## Why

The rule is one buyer relay per operator (`docs/development/VALIDATION_RUNBOOK.md`
section 28; `docs/seller-frp-setup.md`). Under it a relay is safe while every party
holding root on a host attached to it is one its operator trusts. Three gaps are
acceptable today only because of that, and each names the condition under which it
stops being acceptable:

- **A relay admits every holder of its one client token at login.** frps admits a
  client by one token, which sits in the root-only client configuration of every
  attached host, so root on any attached host can log in from anywhere and open
  connections. That is a way to exhaust the relay for every host on it, not to
  reach another host's ports: a proxy is still admitted only for the port a signed
  grant names (`openspec/specs/frp-grant-admission/architecture.md`, "Limits").
  Removing an issuer's key from the plugin does not stop its hosts logging in.
  *Trigger:* the first host on a relay whose root is held by a party the relay's
  operator does not trust, where a relay of its own is not acceptable. A host
  another party prepared and registered with its own key material is such a host;
  so is every host of a second operator on a relay shared against the rule.
- **There is no emergency rotation.** The provisioning service refuses a token
  change while the relay holds an unreleased lease, and a host adopts a token only
  by restarting its client, so a leaked client token is replaced only once the
  relay has drained in every provisioning service that registers its server. A
  compromised signing key is either removed from the plugin at once, refusing
  every proxy it signed at its client's next reconnect, or kept until the leases
  it signed end; no operation reissues a live lease's grant. A grant expires at
  its lease's scheduled end plus a grace, and an on-demand or spot deal's lease
  runs to its term end, so either wait lasts as long as the longest deal on the
  relay, and ending a running deal to shorten it is the seller's end, priced by
  the deal's terms. The operator's procedure is `VALIDATION_RUNBOOK.md` section
  28, "Respond to a compromised relay credential". *Trigger:* at the first
  credential compromise, or before relay-backed pools serve buyers whose operator
  cannot accept draining the relay or refusing reconnects at a credential
  compromise.
- **The relay role compares the plugin wheel's digest with nothing.** The role
  installs the wheel it is given. It checks the dependencies against the lock's
  hashes and names the installed release by the wheel's SHA-256, but has no value
  to compare that digest with
  (`provisioning/compute/iac/ansible/roles/relay-server/tasks/plugin-artifacts.yml`).
  A marketplace release records the plugin's image, with its digest, in its bill
  of materials, which serves a relay run in containers; it releases no wheel, and
  a role cannot pin a wheel built from its own commit. *Trigger:* the plugin's
  wheel is released separately from this repository's roles with a recorded
  digest: the plugin moves to a repository of its own, or its wheel joins the
  release's distributions.

They're grouped because they are one theme, a relay whose attached hosts are not
all trusted by its operator, and each is small beside a change of its own. Each
activates at its own trigger.

## What Changes

- **A relay admits a host at login by the host's own credential.** Each host logs
  into its relay with a credential of its own, checked by the admission plugin,
  rather than by the one client token alone.
- **A credential compromise is answered without draining the relay.** The service
  reissues the grants of a relay's live leases under its newly active signing key,
  and a host's login credential is replaced for that host alone. A reissue or a
  replacement interrupts, at most once, the sessions of the party whose credential
  is replaced: an operator's leases for its signing key, a host's deliveries for
  its login credential. Whether it interrupts them at all is for design.
- **The relay role checks the plugin wheel against a pinned release.** The role
  holds the plugin release's version and digest and refuses a wheel whose digest
  differs.

### Decided by the owner

- **D1: one change for the three relay gaps.** The gaps are grouped by theme
  rather than each given a change (2026-11-17).
- **D2: deferred until a trigger.** No work starts on a piece until its trigger
  above holds. The digest pin may be done on its own at its trigger (2026-11-17).
- **D3: the change is not Goal 1's.** Goal 1's value is that the storefront holds
  no physical authority, which the relay work already delivered. These three gaps
  harden an arrangement nobody runs yet, all deferred behind triggers, and a
  deferred change in a goal's gap table keeps the goal open on work that is not
  the goal. The change sits in the change index's lesser goal "Reach hosts and
  VMs that have no inbound route", and its gaps and triggers are stated in its
  index row alone, since the roadmap keeps no rows for a lesser goal
  (2026-11-26).
- **D4: one relay per operator is the rule, and login admission is per host.** An
  operator gives itself a relay today through the relay API, so separating
  operators needs no new mechanism, and the exposure that remains is per host:
  whoever holds root on an attached host holds the token. A credential per host,
  signed by the host's own issuer, answers that, and would also separate
  operators on a relay two of them shared. Rejected: a credential per operator,
  which leaves a host another party prepared, inside one operator's relay,
  holding that operator's credential; and dropping login admission, which leaves
  that host unanswered (2026-11-26).
- **D5: emergency rotation stays deferred, and the per-incident choice is
  accepted against open-ended deals.** The choice — drain the relay for a leaked
  token; refuse reconnects or wait out the leases for a compromised key — was
  first accepted before on-demand and spot deals existed. It now lasts as long as
  the longest such deal on the relay, and the owner accepted it knowing so. The
  operator's procedure for both incidents, over the routes that exist, is in
  `VALIDATION_RUNBOOK.md` section 28. Rejected for now: activating grant reissue
  alone, and activating the whole rotation piece (2026-11-26).
- **D6: the digest pin stays here, and a containerised relay pins the release's
  recorded image digest.** The pin as proposed cannot be built until the wheel is
  released apart from the role that installs it. What a release already gives is
  the image's digest in its bill of materials, which `VALIDATION_RUNBOOK.md`
  section 28 names as the value to pin for a relay run in containers. Rejected: a
  required expected-digest input on the role, whose reference value would come
  from the same operator who supplies the wheel; and making the wheel a release
  distribution for this alone, which is larger than the gap (2026-11-26).

### Open for design, not decided here

Design settles these when the change activates.

- **The login credential's form.** Signed like the port grants, or a token the
  service issues, and how frp's login operation carries it. The plugin's
  specification names no concept of any issuing system and the plugin holds no
  state; a token for a new purpose takes a type of its own, under the
  specification's explicit typing; and client-wide metadata changes only by
  restarting the client.
- **Whether a reissued grant reaches a live proxy without ending its sessions.**
  The real-frp tests show a client reload asking only about a proxy it added, not
  what a reload does to a running proxy whose own metadata changed. Design needs
  that observation from the real-frp gate before it promises a bound.
- **How a rotation is ordered** across the hosts of a relay, and across the
  provisioning services that register one relay server.
- **What deployed relays and hosts do.** Compatibility is owed to
  `marketplace-v0.4.0`, which carried the relay rows, the relay routes, hosts'
  client baselines holding the one token, and relays whose frps consults the
  plugin for `NewProxy` only. Adding an operation to a deployed frps is a
  configuration change that needs a restart of a drained server, so how hosts
  move from the one token to their own credentials without a drain is owed an
  answer.
- **The pin's representation.** It follows the `frp-binary` role: version, source
  and SHA-256 in the role's defaults, an unpinned version refused, the install at
  a path naming the version. Which version it names, the plugin's own or the
  release's, is open.
- **Which requirements the deltas modify.** In `frp-grant-admission`: "The plugin
  holds no state and calls nothing", which requires `NewProxy` only; "Every
  decision is explained and logged"; "The plugin owns its grant specification".
  In `physical-provisioning`: "A relay binding is fixed for a lease's life", under
  which a token change drains the relay; "Relay admission tokens are resolved at
  execution"; "Each relay holds its own grant-signing key"; "Relays are
  administered resources"; "The buyer-facing tunnel client is hardened on every
  host"; "A relay prepared by the family role runs admission and discloses no
  secret", which requires a wheel the role is given.
- **Where the triggers are written.** In the index row's Notes; the roadmap
  states none.

## Capabilities

### Modified Capabilities

Provisional; settled in design.

- `frp-grant-admission`: admission at login, and the plugin's release.
- `physical-provisioning`: grant reissue, per-host login credentials and their
  rotation, and the relay role's pin.
- `compute-provisioning-contract`: only if a relay route or wire model changes.

### New Capabilities

None.

## Non-Goals

- A relay shared between operators who do not trust each other. The rule is one
  relay per operator (D4).
- Host-key checking, which `harden-provisioning-trust-boundaries` delivered.
- Host credential protection, and whether relay tokens and grant keys leave
  `ssh_decryption_key`. `harden-provisioning-trust-boundaries` deferred both to an
  unowned gap in the change index, where they stay: the storage scheme is one
  question for host keys and relay secrets alike.
- Moving an existing delivery between relays.

## Impact

- `tools/frp-grant-admission`: the admission plugin and its README, which is its
  published specification.
- `provisioning/compute/src/compute_provisioning/relays/` (grants, keys, and
  rotation), the relay wire models in
  `provisioning/compute/contracts/src/compute_provisioning_contracts/relays.py`,
  and the administrator's client in `provisioning/compute/client/`.
- The `relay-server`, `relay-client` and `relay-proxy` roles under
  `provisioning/compute/iac/ansible/roles/`.
- `docs/development/VALIDATION_RUNBOOK.md` section 28 and
  `docs/seller-frp-setup.md`.

## Dependencies and Related Changes

- None.
- `harden-provisioning-trust-boundaries` (archived 2026-11-24) hardened the host
  half of the same boundary: a job that sends the relay's client token reaches
  only a host checked against its pinned key.
- `VALIDATION_RUNBOOK.md` section 28 states what D4, D5 and D6 decided for
  today's system: the rule, the procedure at a credential compromise, and the
  image digest a containerised relay pins. `docs/seller-frp-setup.md` states the
  rule too. They were written with this proposal on 2026-11-26 and describe
  existing behaviour; this change's work revises them when it activates.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification: `frp-grant-admission`,
  `physical-provisioning`
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

To be determined at design completion. Expected destinations: the
`frp-grant-admission` and `physical-provisioning` specifications and architecture
companions, the plugin's README (`tools/frp-grant-admission/README.md`),
`docs/development/VALIDATION_RUNBOOK.md` section 28, `docs/seller-frp-setup.md`,
`docs/development/ROADMAP.md`'s Goal 1 current state, which states the relay's
limits, and this change's row in the change index.
