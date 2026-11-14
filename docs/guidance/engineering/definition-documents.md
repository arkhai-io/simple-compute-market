---
tags: [engineering, configuration]
---

# Definition documents

A definition document is a document, given to a service by path, describing
resources the service should hold — network relays, resource pools, hosts, capacity
declarations. These rules cover what such a document may carry, how its path is set,
the method each kind of document follows, and how applying a document relates to the
state the service already holds.

## A document is configuration, not a secret

A definition document is mounted like any other configuration file and is not a
secret: it carries endpoints, addresses, windows, quantities, and the *names* of
secret-profile keys and key files, never a credential.

## Its path is derived from its presence

The setting naming a document's path is derived by the deployment from the presence
of the document it is given, rather than configured beside the document, because two
independent settings can disagree and the failure when they do is silent: the
document renders, the volume mounts, and the service skips an unset path while
everything looks configured.

## The method a document kind follows

Each kind of document is held to this method, and a new kind follows all of it:

- **One path setting, derived by the deployment.** The kind's path setting is set by
  the deployment from the document it is given, rendered into the deployment's
  configuration so that an edit to the document rolls the service, refused where an
  operator would state it directly, and mounted under a name the deployment's
  general file-mounting option refuses.
- **A digest kind, recorded in the apply's transaction.** A startup applies a
  document only when its digest differs from the one recorded under its kind
  ([Reconciliation follows the document, not the process](#reconciliation-follows-the-document-not-the-process)).
- **A session-scoped apply that fails whole.** Validation is strict and runs in two
  stages, reporting every problem with its location; any problem leaves the document
  unapplied, fails startup, and records no digest. An entry equal to stored state
  writes nothing.
- **An explicit import that always reconciles.** The kind's import route records no
  digest and offers a validate-only mode, answering one response: whether it applied,
  the planned or applied changes, and every problem with a path and a code. An
  applying request with any problem answers 422 and applies nothing; a validate-only
  request answers 200.
- **Validate before the release.** A changed document is submitted to its validation
  route — the import route in its validate-only mode, or a route of its own — before
  the release that mounts it. Where a release stops the running service before
  starting its replacement, a document the service refuses at startup leaves nothing
  serving, while the pre-flight reports the same problems against live state without
  applying anything. A clean validation is the release's go-ahead.
- **A stated rule for entries it stops naming**
  ([What a document does to entries it stops naming](#what-a-document-does-to-entries-it-stops-naming)).
- **No credential.** A secret is named by its profile key or file path
  ([Secrets are named, not carried](#secrets-are-named-not-carried)).
- **A slot in startup's dependency order.**
- **A canonical export where the kind round-trips**, so an existing deployment can
  produce a first document that reproduces its state.

## Reconciliation follows the document, not the process

Import treats its document as authoritative. It overwrites entries that differ from
what is stored and, for a kind whose rule disables them, disables entries the
document does not name. That authority belongs to an operator submitting a document.

**A process start is not a submission.** Import is idempotent with respect to the
document, not the database: re-running it against state something else changed
reverts that change, because a diff against the document is exactly what detects it.
Applied on every startup it would silently undo administrative work on eviction,
drain, and crash recovery.

So a service records the digest of the document it last reconciled and applies a
document only when the current one differs. The digest is written in the same
transaction as the apply — recorded separately, a digest that committed after an
already-committed apply is indistinguishable at the next startup from one recorded
before a crash. An explicit import request reconciles regardless of the digest,
because the operator has asked.

The practical consequences for a deployment:

- Editing a mounted document and rolling the deployment applies the edit.
- Restarting against an unchanged document changes nothing, so anything set through
  the API survives.
- A failed apply records no digest, so the next start retries it.

## What a document does to entries it stops naming

Each kind states its rule for the entries a document stops naming, weighing what
removing one would break. A document declaring what a deployment offers may disable
an entry it stops naming, since an entry it does not name should not be offered. An
entry that others depend on, or that may have been registered through the API rather
than by the document, is retained, since disabling it would break what depends on it,
which is not what an operator editing an unrelated entry is asking for; disabling
such an entry is then an explicit state, set in the document or through the API.

## Secrets are named, not carried

A document entry names which key of the deployment's secret profile holds its
credential, such as a relay's admission token. The service resolves that key **when
the resource is created** and never re-reads it, so a credential rotated through the
API is not reverted by a later reconciliation of a document that still names the key
holding the old value.

An entry naming a key the profile does not carry fails the import, naming the key.
Creating the resource with an empty credential instead would defer the failure to the
point of use, where it appears as a remote service refusing a connection rather than
as a configuration error where the configuration is wrong.
