# Live verification: switch-on-hosted-per-period-vm

The deployment's sanitized summary of the VM live verification run (D9), in the form
section 8.1 states. Raw logs and records stay in the deployment's own storage.

## Provenance

| | |
|---|---|
| Run | 2026-11-23 |
| Source revision | `3b12f82ea699232b90bcb08265a2a1f28f329f13` |
| Target alias | `dev-topology` |
| Payments authority revision | `authority-build-2026-11-23a` |
| Mediation authority revision | `authority-build-2026-11-23a` |
| Provisioning mode | `mock` |
| Run settings | period 72 s, payee notice 120 s, maximum term 720 s, poll bound 120 s |

Both authorities ran from one build of the hosted services. Its label is opaque; the
deployment holds what it identifies.

## Observations

`e2e_vm_live_rate_servicing`:

| Observation | Outcome |
|---|---|
| The buyer's stop | made |
| Funds running out | made |
| The spot preemption | made |
| The term end | made |

`e2e_vm_live_dispute`:

| Observation | Outcome |
|---|---|
| The seller's filing | made |
| The buyer's contested case: the buyer's filing | made |
| The buyer's contested case: the storefront's contest | made |
| The buyer's contested case: the policy's ruling | unproven: the topology applies no ruling policy, and the contested case needs a policy that rules a contested `delivery_end` with a stop returning its period and a reverse (`e2e-tests/README.md`, "Live verification") |

## Threshold (D3)

Met. The buyer's stop, funds running out, the spot preemption, the term end and the
seller's filing are each made; the buyer's contested case is unproven, naming the
requirement it lacked.
