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

`arkhai_api_buying.credentials` defines `CredentialStore` — a `scheme`,
`reference(run_id)`, `location(reference)`, `save(run_id, credentials) ->
reference`, and `load(reference)` — and `FileCredentialStore`: one JSON file per
run at `$XDG_STATE_HOME/arkhai/buy-credentials/<run_id>.json`. The root is
`core_buyer.run_log.runs_dir()`'s parent, so the store follows the run log's XDG
resolution without restating it, and the directory sits beside `buy-runs` and
names the same role.

Every directory from `/` down is opened relative to its parent with
`O_DIRECTORY | O_NOFOLLOW`, and the file is created, replaced, and read through
that directory's descriptor (`dir_fd`), so a component swapped for a link after
any check cannot redirect the write. The XDG state root is resolved once. Each
directory above the store must be the user's or root's and closed to others'
writes unless sticky, and is created `0700` when missing; the store's own
directories (`arkhai`, `buy-credentials`) must be the user's and closed to
others' writes — a group-writable one is refused, not changed, since `arkhai`
also holds the run logs — and `buy-credentials` is held at `0700`. A directory
that cannot be opened or created is a store refusal naming it. `/` itself is
not checked; the walk checks from its first child down. A directory the user
owns that its group can write is refused even if the group is the user's own,
which is conservative. The file is written `0600` through a
temporary file, `fsync`, and a rename within the directory, then the directory
is `fsync`ed; a failure of that last `fsync` leaves the record in place under
its name and counts as saved. Each save sweeps the temporaries an interrupted
save of the same run left. Saves take an exclusive `flock` on the store
directory's own descriptor before creating their temporary file and hold it
through the sweep, so concurrent saves of one run are serialized and the sweep
can only remove the temporaries of a writer that has died. Rejected (on
review): sweeping without a lock — a concurrent writer's live temporary was
removed before its rename, and its valid delivery was reported unsaved. On read, a file that is a link, is not the user's, or is open to
group or others is refused, as is a record that is not JSON or has the wrong
shape; refusals name the path, never the content. A run ID that is not a plain
file name is refused before any path is built.

Rejected (on review): path-based checks followed by path-based `mkdir`,
`chmod`, `mkstemp`, and `replace` — a reproduced race swapped the directory for
a link between the check and the write.

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
with the same mapping without `secret`. `buy` and `negotiate` wrap the logs they
start and `SettlementResume.open_log` the log it opens, so the poll and terminal bodies of
both stages are scrubbed where they are written, not at each call site. The
Alkahest stage prints the submit response through the same projection.

A secret can also travel inside text: `core_buyer` quotes an authenticated
non-success response's body into `AuthenticatedHTTPError`'s message, and the
mechanism stages logged and printed `str(exc)`. The buying layer holds the
boundary for text too, without changing `core_buyer`: `error_text(exc)` reduces
an `AuthenticatedHTTPError` to its method, URL, and status, never its body, and
any other error to its text with each quoted `secret` value redacted;
`DeliveryRunLog` redacts every string it writes the same way, and also removes
each secret it has seen delivered in a structured body. Every error the buy and
settle paths log or print goes through `error_text`, and `buy` prints the
result's reason, and `settle` the seller's reason, through the same redaction.
The text redaction is a backstop, not the boundary: it recognises a quoted
`secret` key, not an escaped or differently named one, so the error paths that
could carry a body reduce it away rather than rely on redaction.

A body that carries the key may also fail to be appended. `DeliveryRunLog`
treats that one append as best-effort, so the flow still reaches the save and
the panel; any other failing append raises as before.

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

A disk that refuses the store may refuse the run log as well, so a failure to
write `credentials_unsaved` or the run's end does not stop the panel: the key is
shown and the command exits 8 regardless.

The reverse — the key saved, then the run log refusing `credentials_delivered`
or the run's end — shows the panel and the file's path and exits 9. The key is
not orphaned: `credentials show` looks it up by run ID (the store's
`reference(run_id)`) when the run log records no reference.

A failing disk can also tear that append, leaving an unterminated fragment
at the end of the file. Two rules keep that shape recoverable and nothing
else:

- Once an append fails, `DeliveryRunLog` writes nothing more to that run log,
  because a later append would complete the fragment into a newline-terminated
  malformed record. If a key has been seen, later events are dropped so the
  flow still reaches the save and the panel, and the delivery reports the log
  as unrecorded (exit 9); otherwise each later event raises.
- `credentials show`, when the strict read fails, drops only an unterminated
  final fragment — a file that does not end in a newline — and runs the core
  recovery-identity resolution and `read_run` unchanged over a private `0600`
  copy of the rest, from which any legacy secret is removed, so ownership is
  still checked. A newline-terminated record that does not parse is
  corruption, not an interrupted append, and is refused like any malformed
  record. An incomplete run-log migration blocks the read before any copy is
  made, since the copy carries no migration manifest. No other command
  tolerates a torn record.

Rejected: a `tolerate_torn_tail` option on `core_buyer.run_log`'s readers and
recovery resolver — the buying layer reuses the core reader through its
`directory` and `run_logs_directory` parameters, so the core buyer role, which
`kit-owned-buyer-orchestration` owns, is unchanged. Rejected (on review):
dropping a newline-terminated malformed last line too, and retrying on every
`RunLogError` — the first skipped corruption, the second bypassed the
migration lock.

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
| `arkhai-api-buying-arkhai-payments` | 0.1.1 | its errors pass through `error_text`; floor on `arkhai-api-buying>=0.2.0` |
| `arkhai-apicredits-buyer` | 0.7.0 | floors on the above; tests |

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
- Typer's pretty tracebacks print frame locals by default, and the core buyer
  app (`core_buyer.cli.build_app`) does not turn that off, so an unexpected
  exception raised while a frame holds the delivered mapping could print the
  secret. The buying library catches the failures it anticipates (store and
  run-log writes, unreadable records, unknown runs); setting
  `pretty_exceptions_show_locals=False` belongs to the core buyer app, which
  every domain's buyer shares, and is left to a core buyer change.

## Open Questions

None.
