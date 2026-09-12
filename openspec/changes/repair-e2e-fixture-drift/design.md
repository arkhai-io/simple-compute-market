# Design — repair E2E fixture drift

## Context

Both failures are constructor calls, so they raise during fixture setup and every
test depending on them reports an error rather than a result. That is why a
two-line cause produces 88 errors, and why the count is not a measure of how
much is wrong.

## Decisions

### The suite moves, not the libraries

Each mismatch is a library that gained a capability the suite has not caught up
with.

`SyncProvisioningClient` now takes `(base_url, signer, expected_authorities, *,
timeout, transport)`. The service it drives authenticates per caller — the
compose stack configures `PROVISIONING_IDENTITY__*`,
`PROVISIONING_STOREFRONT_IDENTITY__*`, and `PROVISIONING_ADMIN_IDENTITY__*`, and
the storefront profiles pin it as a `service_peer`. A shared `X-Admin-Key` is
the model that preceded that. Reverting the client would undo per-caller
identity across the provisioning boundary to avoid editing a fixture.

`ProfileStore.revision` is `Field(ge=0)` with no default, and
`ProfileRepository.replace` takes `expected_revision` — together they are
optimistic concurrency on the buyer profile document. The fixture already passes
`expected_revision=0`, so it half-knows about the mechanism; it just does not
set the field on the candidate.

### The initial state has a constructor; use it

`ProfileStore` already exposes a classmethod that returns `cls(revision=0)`.
The fixture should call that and populate it rather than pass `revision=0`
literally: a hard-coded zero is a second place that has to change if the
initial revision ever stops being zero, and the model is the right owner of
that fact.

### Repair, then classify — not repair and chase

Turning 88 errors into 88 results will expose whatever the suite was written to
catch and has not been able to report since mid-August. The temptation is to fix
those findings in the same pass.

It should not. The identities change absorbed five unrelated pre-existing
defects before reaching a boundary, and each one made its proposal less true
than when it was written. This change ends when the fixtures are correct and
the remaining failures are classified — every one either a real finding with an
issue raised, or a genuine pass.

### What the fixture needs, and the one thing to confirm first

The repaired `provisioning_client` needs two values the settings may not yet
carry:

- **A signer.** The provisioning service's admin principal is
  `0x9965507d1a55bcc2695c58ba16fb37d819b0a4dc`, configured as
  `PROVISIONING_ADMIN_IDENTITY__IDENTIFIER` in
  `compose.local-identities.yml`. The e2e settings expose `SELLER.PRIVATE_KEY`
  and `SELLER.ADMIN_API_KEY`, and the second is now the wrong shape entirely —
  it is a bearer key, not a credential.
- **An `expected_authorities` set.** The provisioning service signs as
  `PROVISIONING_IDENTITY__IDENTIFIER`, `0xf39fd6e5…`.

**Confirm before writing the fixture** whether the suite should drive
provisioning as the *admin* principal or as the *storefront* principal
(`0x3c44cddd…`, pinned as `PROVISIONING_STOREFRONT_IDENTITY__IDENTIFIER`).
Those are different callers with different authorisation, and the answer decides
which credential the fixture needs. The retired shared admin key made the
question invisible, which is part of why the drift went unnoticed.

## Risks / Trade-offs

- **[The repaired fixture authenticates as the wrong principal]** → It would
  fail on authorisation rather than construction, which is a clearer signal
  than today's `TypeError` but still not a result. Settling the caller question
  before writing the fixture is what avoids it.
- **[The suite reports many real failures once it runs]** → Expected, and the
  reason this change classifies rather than fixes. A long list of genuine
  findings is a better position than 88 errors that say nothing.
- **[Fixture repairs drift again]** → The root cause was that no working stack
  existed to run against, which the archived identities change fixed. The
  nightly workflow now exercises this path, so the next divergence surfaces in
  a day rather than a month.

## Open questions

- **Admin or storefront principal for `provisioning_client`?** Stated above;
  blocking for that fixture only.
- **Does `SELLER.ADMIN_API_KEY` still have any consumer?** If the provisioning
  fixture was its last user, the setting and its compose plumbing are dead and
  should go rather than linger as a retired-model artefact. Check before
  removing — the storefront's `/admin/*` routes may still gate on it, in which
  case `storefront_admin_client` keeps it and only the provisioning fixture
  stops using it.
