# Local qualification design

## Decisions

The existing signed registry process, publication environment, loopback server, typed buyer transport and fake SMTP test seams remain authoritative. Add `domains/bare_metal/storefront/tests/test_declared_contact_qualification.py` to join those seams. General publication must invoke the installed executable and discover all six TEST declarations before negotiating one selected option. There is no seeded-listing substitute for this leg.

The test independently retains the advertised option params and conditions, declaration/listing/machine, requested terms and service terms before negotiation. An explicitly supplied `validate_advertised_plan` callback supplements universal core checks; it does not replace them. The shared buyer default intentionally refuses the additional context digest. A self-consistent substituted context must still fail retained-expectation validation. No production buyer imports a storefront validator and no production acceptance adapter is added.

Freeze contact text and separate recipient routes at review/finalization. Restart the storefront after durable exchange and settlement completion; mutate mutable listing/settings and prove frozen reads and two recipient copies. One recipient temporarily refuses SMTP while the other succeeds, then retries under the existing deterministic clock seam. Acceptance and review send nothing. Existing lower-level suites retain exhaustive negative, historical no-outbound, physical and completion-contention jurisdiction.

Installed validation disables pytest's source `pythonpath`, builds/reinstalls repository packages as wheels and compares source/wheel/installed bytes and imported module paths. The registry is an independently locked local application; its service source is intentionally launched as `src.main`, while its internal dependencies remain installed wheels. Evidence distinguishes that source application from wheel-installed seller and buyer libraries. No external release provenance is asserted.

## Alternatives

Chaining existing seeded SQLite suites would not establish the publication-to-acceptance join. Copying their complete negative matrices would obscure that join. Broad production refactoring and a generic buyer contact adapter are outside the approved requirement; the current explicit callback is sufficient for this TEST lane.

## Validation and promotion record

Exact commands, source revision, diff, wheel filenames/versions/hashes, import paths and sanitized outcomes are retained outside the repository. Existing expanded typing and repository-wide OpenSpec failures remain distinct from focused results. Local behavior does not establish physical ownership, availability, deployment, inbox delivery or exactly-once mail.

| Material decision | Permanent destination | State |
|---|---|---|
| Real general publication/discovery as the qualification entry | `openspec/specs/storefront-publication/spec.md` and `architecture.md` | Promoted after independent review |
| Exact retained acceptance and frozen restart behavior | `openspec/specs/contact-exchange-settlement/spec.md` and `architecture.md` | Promoted after independent review |
| Independent recipient outcomes from one frozen capture | `openspec/specs/introduction-delivery/spec.md` and `architecture.md` | Promoted after independent review |
| Local-only qualification and callback scope | `docs/development/ARCHITECTURE.md`, `docs/development/DEPLOYMENT_AND_CONFIG.md` | Promoted after independent review |
| Current state and remaining boundaries | `docs/development/ROADMAP.md`, `openspec/specs/README.md`, `openspec/changes/README.md` | Current state and remaining gaps reconciled |

Independent review found no issues. Parent applied the permanent amendments, reran the six complete package suites and focused boundary/chart/vector checks, verified wheel/import parity, and validated the promoted change/specs and document links. Prior completed/frozen history remains unchanged. The change is archived after this verified source closeout; no release or activation is inferred. The qualification-tool entrypoint friction is recorded in `docs/frictions.md`.

## Observed local qualification

The joined journey publishes and discovers six TEST declarations, accepts one
rateless option with no amount, rejects an internally consistent substituted
machine, and sends nothing at acceptance/review. Withdrawal before finalization
and settings changes after capture do not alter the frozen package. Restart at
completed settlement preserves one capture/two intents; a temporary seller-recipient
refusal leaves the buyer's accepted copy untouched. Both eventual MIME-decoded
context blocks match and contain the frozen package's scalar facts. A terminal
restart sends nothing and retains no routes.

The six complete installed-wheel package suites pass 790 tests without skips;
core dependency boundaries add four and local chart checks add eleven. Bun runs
63 independent scalar/canonical vector cases. Seller parity covers 262 internal
source files plus six supplied external-client wheel files; registry dependency
parity covers 24 files. No external-client source or registry application wheel
parity is claimed. New-test and six-contract-module ty checks pass; wider ty and
repository-wide OpenSpec failures are retained separately, not generalized to a
passing repository. Exact receipts remain external; current behavior and its limits
are promoted to the destinations above.
