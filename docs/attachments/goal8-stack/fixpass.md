# Goal 8 stack repair checkpoint

The PR branches remain unchanged while the corrections are qualified on scratch
branches. No pre-rebase tag was changed.

## Repairs prepared

- Registry publication: convergence bypassed the VM candidate codec and resent
  local JSON null capacity attributes. Full schema validation refused the reopen.
  The runtime now accepts the same candidate factory the VM initial/reopen paths
  use. The second-deal assertion is unchanged.
- API credits: publication failed with HTTP 422 because the registry filter schema
  still required flat `mechanism`, `asset`, `rates`, `params` option fields. The
  seeded listing therefore never reached discovery; the CLI correctly exited on
  no matches before creating a run. The schema now describes the existing nested
  `price`, `settlement`, `lifecycle` carrier. Purchase assertions are unchanged.
- The release guide lists `arkhai-core` and `arkhai-vms` for VM negotiation in the
  resize branch. The VM domain's `arkhai-kit-resource-pools-contracts` addition
  first occurs in the terms branch and is documented there.
- The commit introducing the mixed-selection checkpoint was amended to resolve
  `podman-compose` through PATH. Its additions contain no personal home path.

## Validation

Registry scratch E2E run:
https://github.com/arkhai-io/simple-compute-market/actions/runs/42996260999

All four jobs passed: VM, API credits, bare metal and the native Ansible gate. Existing capacity-publication tests and the focused
VM publication suites passed (92 VM tests). `make check-packaging` and
`make check-comment-hygiene` passed on the registry, resize and terms scratch
branches. The release-matrix suite passed on resize and terms (302 tests each).

## Reserved-purchase scenario boundary

The published deadline absence follows terms D3 and its frozen dependency
contract: the effective pool-facts port, `delivery_deadline_for_pool`, is not
injected in either deployed composition. A raw clause deadline cannot stand in
for it. The reserved-payment scenarios explicitly pass
`--allow-unprotected-terms` and assert that no deadline is promised, retaining
dispute coverage, payment, fulfillment and release checks. A reserved-payment
purchase from these sellers therefore requires that opt-out. Whether a
seller-configured deadline should be the interim source remains open; the terms
design records the hole without changing D3.

Final branch qualification and publication are recorded in the repair handoff.
