# Hosted rate library — sections 1–3 evidence

## Scope and prepared first use

This packet covers the interface gates, setup/rate mandate derivation, both compute publication helpers, and the stateless rate adapter. No installed recurring declaration is enabled. Seller notice CLI, re-anchoring, continuation and the complete qualification matrix are not part of this slice.

The prepared target is an invocation-owned in-process payment authority, not a Cloud or hosted deployment. Its persona is deterministic development payer/payee accounts; its authentication/signature method is the fixture signer, never production credentials. It starts with an approved setup/rate commitment, explicit fixture reservation state and an injected clock. No secret environment variables, server, container, tunnel or persistent external state are needed.

From a clean checkout:

```sh
make dist-ci && make -C kit/arkhai-payments first-use-rate
```

The entry point opens the rate library directly, not a shell/menu surface. The [JSON observation](rate-first-use.json) is fixture evidence: exact setup/rate mandate, pure authorization, lost start response, same-key recovery, disclosure, pending notice and winning final stop. It is not live payment or mediation qualification. No screenshots apply.

## Focused validation

Sections 1–3 were validated with the payments kit's typing, unit tests, published
vector and generated-model checks and first use; the servicing, mediation and both
storefronts' publication and payment suites; composition-file typing; packaging and
comment hygiene; and strict OpenSpec validation. Loopback application tests run with
`ALL_PROXY`, `all_proxy`, `HTTP_PROXY`, `HTTPS_PROXY`, `http_proxy` and `https_proxy`
unset. Current test counts are in the change's task notes, which supersede the
counts this packet first recorded; every behaviour now lands with permanent tests.

## End-to-end evidence

The first attempt at the VM compose lane ran in an environment without Docker and
started nothing. Validation runs the compose lanes with Docker and the local Helm
part as the change's end-to-end evidence; section 4's VM compose run
([section 4 evidence](../spot-deals-section-4/index.md#compose-vm-run)) stands as
interim evidence, and a lane unrun at closeout is a blocker, not a pass.

## Review and closeout

The change is in implementation on `dev`; permanent specification promotion and
archival wait for the remaining sections and post-code-review closeout. The kit
README describes the delivered library and its caller-owned journal contract.
