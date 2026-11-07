# Alkahest release-model first use

Nonvisual setup and implementation evidence for section 4 of the active change.
Implementation revision: `0c8d22560` (configuration, publication and migration),
with documentation and the kept non-ERC20 scenario's option accessor updated in
this packet's commits. This is implementer self-check evidence, not independent
acceptance.

## Owned setup and entry point

Required and prepared environment: a checkout-local CLI, plus disposable local
container lanes for blockchain/API regression. No hosted deployment is required.
The CLI persona is the seller operator; migration needs no authentication,
credentials, chain, database or running storefront. The seed is the public
[legacy recipient fixture](legacy-recipient.toml). Copy it into a fresh temporary
directory; never migrate the checked-in fixture or an operator's real config.

From the repository root:

```sh
unset ALL_PROXY all_proxy
export NO_PROXY=localhost,127.0.0.1 no_proxy=localhost,127.0.0.1
make dist
make -C domains/bare_metal/storefront reinit
sandbox=$(mktemp -d)
cp docs/attachments/alkahest-release-models/legacy-recipient.toml "$sandbox/storefront.toml"
cli="$PWD/domains/bare_metal/storefront/.venv/bin/bare-metal-storefront"
"$cli" config migrate --config "$sandbox/storefront.toml" --scope settlement --check
"$cli" config migrate --config "$sandbox/storefront.toml" --scope settlement --write --backup
"$cli" config migrate --config "$sandbox/storefront.toml" --scope settlement --write --backup
```

The first invocation opens the actual public CLI. Preview reports the old keys
removed and the new list set, without showing credentials or changing bytes.
Write produces `release_models = ["recipient"]`, removes both flags and leaves
an original-byte `storefront.toml.bak` with mode `0600`. Repeating write reports
`No settlement configuration migration changes.` and leaves the migrated bytes alone.
All three invocations were opened successfully. A conflicting list was also
tried: the CLI refused before changing the config or creating a backup.

## Publication and selection

The existing VM application integration journey
`domains/vms/storefront/tests/integration/test_buyer_selection_negotiation.py`
uses a disposable database, an injected local chain boundary, deterministic
public development identities and a temporary address book. It now publishes
recipient and interruptible options, chooses the second option, passes the real
buyer plan validator and negotiates to acceptance. Both options have distinct
IDs, their own `settlement.accepted_escrow.demand`, and no `lifecycle`. The
bare-metal publication journey offers recipient and oracle-gated choices.
Unsupported domain release models refuse startup. Existing kept assertions
follow these deliberate behavior changes; no new test functions were added.

Reproduce the VM journey after `make dist`:

```sh
make -C domains/vms/storefront reinit
(cd domains/vms/storefront && .venv/bin/pytest \
  tests/integration/test_buyer_selection_negotiation.py -q)
```

## Validation and limits

- Alkahest kit: 447 passed.
- Shared configuration migration: 272 passed, including each old flag,
  absent/false flags, conflicting configuration and byte-identical replay.
- VM storefront unit/integration regressions: 1,189/501 passed after updating the
  duplicate-list error expectation; targeted multi-model buyer journey passed.
- Bare-metal storefront: 522 passed. API-credit storefront: 248 passed.
- Architecture, packaging, locks, comment hygiene and strict OpenSpec validation
  pass. No dependency declarations changed. Moving the option builder's local
  release-condition import to module scope in a temporary package copy reproduced
  the initialization cycle; the production import retains its local rationale.
- The first VM container lane passed 35 stages, including the complete ERC20 deal,
  but the two non-ERC20 cases failed because their kept scenario still indexed
  the removed top-level `mechanism`. The accessor now reads `settlement.schema`;
  the re-drive passed all 37 selected stages (ERC20, native token and ERC1155).
  Repair commit: `7d7d41ad5`.
- The required citation command reports three planned closeout destinations,
  the deal-lifecycle spec and architecture companion cited by the active design
  and tasks. Existing owner: [issue 325](https://github.com/arkhai-io/simple-compute-market/issues/325).
  No placeholder permanent document was created and no check was weakened.
- `e2e_bare_metal_deal` needs an operator-supplied real whole host and SSH
  credentials. This checkout has neither. A mock-provisioned deal can validate
  the API/chain path but cannot establish real SSH delivery or revocation.

The first aggregate run reached Helm rendering and refused old release flags in
three checked-in values files. Those files now use `release_models: [recipient]`;
`make -C helm test-render` passes. Repair commit: `013995f18`.

The bare-metal container lane passed all 39 mock-provisioned stages. The required
real-host scenario was selected too, but skipped with
`BARE_METAL.REGISTRY_URL is not configured`. This is not evidence that real SSH
access or revocation worked. The real-host environment and role-scoped SSH
credential remain an acceptance blocker.

Reproduce the container checks on a host with the repository's Docker-compatible
container tooling, running the two stacks sequentially:

```sh
make -C e2e-tests test-e2e-vm \
  E2E_VMS_PROJECT=release-models-vm \
  E2E_VMS_ENV="$PWD/.e2e-release-models-vm.env" \
  E2E_MODULE='e2e_deal or e2e_non_erc20_settlement' PYTEST_ARGS=-q
make -C e2e-tests e2e-vm-down \
  E2E_VMS_PROJECT=release-models-vm \
  E2E_VMS_ENV="$PWD/.e2e-release-models-vm.env"
make -C e2e-tests test-e2e-bare-metal \
  E2E_BARE_METAL_PROJECT=release-models-bm \
  E2E_BARE_METAL_ENV="$PWD/.e2e-release-models-bm.env" \
  E2E_BARE_METAL_MODULE='e2e_bare_metal_deal or e2e_bare_metal_mock_deal' \
  PYTEST_ARGS='-q -rs'
make -C e2e-tests e2e-bare-metal-down \
  E2E_BARE_METAL_PROJECT=release-models-bm \
  E2E_BARE_METAL_ENV="$PWD/.e2e-release-models-bm.env"
```

The final `make test` aggregate, with the local Podman-compatible Docker shim
and proxy exclusions, passed in 7m45s on `013995f18` plus the documentation in
this packet. This includes release tooling and the repaired Helm rendering.
Each self-check lane's Compose project was torn down and its build-time Anvil
child stopped. There is no persistent CLI server to stop.
