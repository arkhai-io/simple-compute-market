---
tags: [engineering, repository-content]
---

# Repository content

What may enter a repository: what holds in every repository, what a public repository
additionally refuses, and what a private one may hold that a public one may not.
Everything a repository holds — code, comments, documentation, design notes,
fixtures, test data, commit messages, and pull request descriptions — is held to
these rules alike: a design note is as public as code.

## In every repository

### No credentials

No key, password, token, or credential of any kind enters a repository, including an
expired one and one believed to be test-only on a private network.

### Fixtures are obviously fixtures

Where a fixture or local development configuration needs an address, a key, or a
host, use a well-known deterministic development value, and say in a comment that it
is one and must never be used on a public network. A value that looks plausible and
is not obviously a fixture is worse than no comment, because a later reader cannot
tell whether removing it is safe.

### Referring to work that is not here

When work in a repository exists because of work elsewhere, describe the requirement
in terms of the repository's own behaviour, not in terms of the external consumer's
identity.

Prefer:

```
Exposes a stable invocation target so an external test harness can run the
suite without reproducing the internal command sequence.
```

Avoid:

```
Needed by the harness runner in <private repo>, see <private plan document>.
```

The first is a durable statement about the repository's interface. The second leaks
what the reader may not be entitled to see, and it also rots the moment the external
caller is renamed.

## In a public repository

Everything in a public repository is world-readable, permanently, including after a
later edit removes it. Beyond what every repository refuses, a public repository
never holds:

- private repository names, branch names, or commit identifiers;
- cloud project, account, cluster, namespace, or host identifiers;
- internal endpoints, private URLs, or non-public service addresses;
- account identifiers, such as wallet addresses;
- filesystem paths from a private repository or a private working environment;
- raw logs, evidence bundles, or run artifacts produced by private tooling;
- the names or contents of private planning documents.

### Private dependencies stay out of its tests

Every test a public repository runs in public CI or a public build passes without
credentials for a private repository, image, or package. A scenario that needs a
private service's internals — its source, images, development-mode authentication,
or operator-held test funds — lives in that service's repository, which may depend
on the public repository's artifacts. The public repository may run its end-to-end
tests against a service's public test deployment, gated on readiness: it reports the
unmet prerequisite when no target is configured or reachable. Otherwise it tests its
client of the service against the service's published contract — schemas and test
vectors — and a test double at the client's boundary.

### Published artifacts are checked with canaries

A public repository's tests seed recognizable secret canaries into configuration and
reject them in every artifact it publishes or renders: public models, persisted
state, logs, command output, error representations, rendered configuration, images,
packages, manifests, fixtures, and evidence. A credential value appears only inside
the component that is meant to hold it.

## In a private repository

A private repository may hold what a public repository refuses beyond the rules for
every repository — the names of other private repositories, infrastructure
identifiers, internal endpoints, account identifiers, private paths, raw evidence
from its own tooling, and its planning documents — since only those entitled to see
them can read it. It still holds no credential, and its fixtures are still obviously
fixtures. Nothing here obliges a private repository to hold any of it.
