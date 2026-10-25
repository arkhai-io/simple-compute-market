## Context

### What exists

The api family's buying library (`domains/api/buying`, `arkhai_api_buying`)
runs every API-credit buyer flow. A seller returns an issued key's
`tenant_credentials` — `key_id`, `secret`, `base_url`, `balance` — in its signed
settlement status, and the library keeps it in three places in the buyer's
JSONL run log under `$XDG_STATE_HOME/arkhai/buy-runs/`:

| Writer | Event | What it records |
|---|---|---|
| `buy.py`, after `run_buy` | `credentials_delivered` | the whole mapping, secret included |
| `stages.py` `SettlementResume.finish` | `credentials_delivered` | the whole mapping, secret included |
| `buy.py` `_observe`, the payments stage's `on_event`, the Alkahest stage's `_on_poll` and terminal record | `settlement_poll`, `settle_status`, `settle_terminal` | the seller's status body, whose terminal poll carries the same mapping |

The third row is not in the proposal: the poll bodies carry the secret too, so
removing `credentials_delivered`'s copy alone leaves it in the log. The Alkahest
stage also prints the seller's submit response to the console.

`core_buyer.run_log.RunLog` refuses a set of identity-credential field names
(`private_key`, `credential_reference`, `keyring_value`, …) but not `secret`;
it writes run logs `0600` in a `0700` directory with an atomic writer.

The seller keeps the secret in its private result repository and re-serves it to
the deal's owner on each status read (`arkhai_api_selling.issuance.project_progress`),
so a resumed `settle --from` reads it again. Nothing on the buyer side relies on
that: the seller may purge a private result, and the buyer specification gives no
such promise.

### What governs the design

`buyer-orchestration` "Buyer evidence is separate from private delivery":
credentials stay behind the domain's private result boundary and out of the run
log. No buyer in the repository has such a boundary on its own side, so this
change adds one.

The owner delegated each decision below to the implementer; each records its
rationale and the alternatives rejected.

## Goals / Non-Goals

Goals: the secret is written only to a private store; the run log keeps a
non-secret record that existing waits still match; buyers and scenarios read the
key through a command; a failed private write loses nothing; runs recorded before
this change stay readable.

Non-goals: what the seller delivers or signs; the authority's key handling; the
buyer's mechanism inputs and flags (`derive-buyer-settlement-inputs`); a keyring
store.

## Decisions

### D1. A `CredentialStore` protocol with one file implementation

`arkhai_api_buying.credentials` defines `CredentialStore` — a `scheme`, `save(run_id,
credentials) -> reference`, and `load(reference)` — and `FileCredentialStore`: one
JSON file per run at `$XDG_STATE_HOME/arkhai/buy-credentials/<run_id>.json`. The
root is `core_buyer.run_log.runs_dir()`'s parent, so the store follows the run
log's XDG resolution without restating it, and the directory sits beside
`buy-runs` and names the same role. The directory is created `0700` and
re-tightened to `0700`; the file is written `0600` through a temporary file,
`fsync`, and `os.replace`, then the directory is `fsync`ed. A directory or file
that is a symlink is refused, and reads open with `O_NOFOLLOW`. A run ID that is
not a plain file name is refused before any path is built.

`BuyerSettlementComposition` holds the store (`credential_store`, defaulting to
`FileCredentialStore()`), so the buy, settle, and retrieval paths share one
injection point.

Rejected: a keyring implementation now — it needs a platform dependency and a
headless fallback, and nothing in the repository asks for it; the protocol admits
it under its own `scheme` (deferred, below). Rejected: a single file of every run's
credentials — one file per run keeps writes independent and lets a run's key be
removed alone. Rejected: `$XDG_STATE_HOME/arkhai/credentials/` — that name reads
as the buyer's identity credentials, which `core_buyer`'s profiles own.

### D2. The run log keeps `credentials_delivered` without the secret

The event keeps its name, so a scenario or tool waiting on it still works. Its
fields are `key_id`, `base_url`, `balance`, and `delivery_ref`, the store's
reference (`file:<run_id>`). It never carries `secret`.

Every event the buying library writes passes through `DeliveryRunLog`, a
`RunLog` whose `event` replaces any `tenant_credentials` mapping, at any depth,
with the same mapping without `secret`. `buy` wraps the log it starts and
`SettlementResume.open_log` the log it opens, so the poll and terminal bodies of
both stages are scrubbed where they are written, not at each call site. The
Alkahest stage prints the submit response through the same projection.

The field is `delivery_ref`, not `credential_ref`: `core_buyer`'s run log
refuses `credential_reference` as an identity-credential locator, and a
near-spelling would evade the guard's purpose rather than meet it.

Rejected: adding `secret` to `core_buyer`'s refused field names — the VM buyer
also writes `tenant_credentials` through it, and changing what the core role
refuses is a cross-domain change this one does not own (follow-up, below).
Rejected: redacting at each call site — a stage added later would have to
remember it.

### D3. `credentials show` retrieves the key

`market credits credentials show --from <run-id>` (`--run`, `-r` as on
`settle`), registered by `arkhai_api_buying.commands`, resolves the run's
recovery identity, reads the run's last `credentials_delivered` event with the
signer that owns it, loads the reference from the composition's store, and prints
the key in a panel, or as one JSON object with `--json`
(`run_id`, `key_id`, `secret`, `base_url`, `balance`, `source`). Printing the
secret is what the command is for. A run with no delivered credential, a
reference no store holds, or a reference of another scheme exits 1 with a
message naming the run.

Rejected: a `--print-secret` flag on `settle` — it re-polls the seller, and a
read should not need the seller. Rejected: reading the store file directly from
scenarios — the command is the buyer's interface and the file layout is the
store's.

### D4. A failed private write shows the key once and exits 8

If settlement delivers a secret and `save` fails, the buyer still shows the key
panel, titled as unsaved; records `credentials_unsaved` with the public fields
and the error's class name, never its message or the secret; ends the run with
its settlement status; prints a message telling the buyer to copy the key now;
and exits 8, a code no other buyer exit uses (2 arguments, 3–6 failures,
7 settlement not ready). An unready status still exits 7 when the write
succeeded.

Rejected: failing before display — the seller's re-serving is not a promise, so
the panel may be the only copy. Rejected: falling back to the run log — that is
the defect.

### D5. Runs recorded before this change are read, not rewritten

A `credentials_delivered` event that still carries `credentials.secret` is read
by `credentials show` as a fallback, which reports `source: "run_log"` and says
the secret is held in the run log. Existing logs are not rewritten: run logs are
append-only recovery evidence, and `RunLog` has no rewrite path outside its
identity migration.

Deferred: a `market credits credentials migrate` that moves a legacy secret into
the store and rewrites the log, if a buyer asks for one.

### D6. The secret reaches only the panel

`buy` and `settle` keep their once-shown panel; it now names where the key was
saved and the command that reads it. A canary test drives `credits settle --from`
through the plugin's composition with a seller status, submit response, and poll
body all carrying a canary secret, and asserts it appears in the store file and
in the panel, and nowhere in the run log, captured logging, or the rest of the
output. Store and retrieval errors name the run and path, never the value.

### D7. Both API-credit scenarios read the key through the command

`BuyerCli.credentials(command, run_id)` runs
`market <command> credentials show --from <run_id> --json` in the helper's
hermetic environment and returns the object. `e2e_credits_deal` and
`e2e_credits_payment_deal` use it; their waits on `credentials_delivered` stay.
Validation runs them; they are not run on the implementing machine.

## Versions

| Distribution | Version | Why |
|---|---|---|
| `arkhai-api-buying` | 0.2.0 | new module, command, and run-log contract |
| `arkhai-api-buying-alkahest` | 0.1.1 | submit-response projection; floor on `arkhai-api-buying>=0.2.0` |
| `arkhai-apicredits-buyer` | 0.7.0 | floor on `arkhai-api-buying>=0.2.0`; tests |

## Risks / Trade-offs

- A file store is as private as the account: anyone with the buyer's user can
  read it, as with the run log before. The gain is that the run log, which is
  evidence a buyer may share, no longer holds the key.
- A legacy run keeps its secret in the run log until a migration exists.

## Deferred

- A keyring `CredentialStore` (D1), when a buyer needs it.
- A legacy-run migration command (D5).
- `secret` in `core_buyer`'s refused run-log fields (D2), owned by a core buyer
  change, since it reaches the VM buyer.

## Open Questions

None.
