---
tags: [repository, testing, repository-content]
---

# Lane doubles

What this repository's tests do in place of a private service, and what its doubles
answer, as instances of
[`repository-content.md`](../engineering/repository-content.md) and
[`test-doubles.md`](../engineering/test-doubles.md). The doubles themselves — the
payments and mediation lane doubles, their controls, and the payments helper — are
[`TESTING.md`, "Private Service Dependencies"](../../development/TESTING.md#private-service-dependencies).

## Private dependencies stay out of the tests

This repository is public, so its tests keep private dependencies out ([`repository-content.md`, "Private dependencies stay out of its tests"](../engineering/repository-content.md#private-dependencies-stay-out-of-its-tests)): here a scenario needing a private service's ledger reads lives in that service's repository, and SCM tests its client kit against the service's published contract and a test double at the kit's boundary.

## A double mirrors its producer

The doubles here mirror their producers
([`test-doubles.md`, "A double mirrors its producer"](../engineering/test-doubles.md#a-double-mirrors-its-producer)),
as mock provisioning takes a job's outcome as a programmed answer, and the end-to-end
lanes' payments double, `tools/payments-lane-double`, and mediation double,
`tools/mediation-lane-double`, mirror the payments service and the dispute authority.

## A mock's default output

A mock's default output is what the shipped configuration prints for the job
([`test-doubles.md`, "A double answers as its producer would"](../engineering/test-doubles.md#a-double-answers-as-its-producer-would)):
the role's `debug: var:` fact in the YAML result format, then the `debug: msg:`
JSON copy the shared fact reader reads, rendered from the job's own parameters
— its guest or host, its tenant account, its action, and booleans where the
role prints booleans. A fact naming another guest or tenant therefore yields no
delivery evidence in a mock lane either. The VM scenarios arm no
create output of their own; every create reads that default. A test that needs
an output the role would not print for its job states it in a rule.
