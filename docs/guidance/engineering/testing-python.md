---
tags: [engineering, testing, python]
---

# Testing Python

The Python forms of the testing rules. Each section names the neutral rule it
applies.

## Doubles for injected collaborators

Use `unittest.mock.MagicMock` and `AsyncMock` for injected collaborators, passed in
through the constructor ([Test seams](test-seams.md), "Injected collaborators").

## A command module's factories are its seam

A command module — a command-line or operator command set whose framework calls its
module-level functions — has no constructor. It is its own composition root instead,
and builds its collaborators through module-level factory functions it defines, named
for what they provide; those factories are its one seam. A test replaces a factory on
the module that defines it and nothing else — no library name, no name the module
imports from another, no name inside a shared package — because an import-style
change can silently undo such a patch, and the test then runs the real collaborator.

```python
# cli.py
def mail_client() -> MailClient:
    return MailClient(settings().mail_url)

# test_cli.py
monkeypatch.setattr(cli, "mail_client", lambda: fake_mail)
```

## Integration test setup

Drive the real application with `httpx.AsyncClient` over `ASGITransport`, injected
through the service's canonical typed-client constructor
(`FooClient(transport=...)`). Override the dependency container's provider for the
one collaborator being doubled before the test, and restore it after
([Integration tests](integration-tests.md)).

## Waiting on a background job

Synchronize on an injectable callback rather than `asyncio.sleep`
([Deterministic tests](test-determinism.md), "No sleeps"): set an `asyncio.Event`
from the callback and wait on it with a bound.

```python
started = asyncio.Event()
queue = JobQueue(on_job_started=lambda job_id: started.set())  # None in production
await queue.submit(job)
await asyncio.wait_for(started.wait(), timeout=5)
```

A real server a test cannot replace with an in-process transport, whose library stops
only at its next poll, is the one standing exception to waiting on events: run
`socketserver`'s `serve_forever` with `poll_interval=0.01`, and stop a loopback
server on an event rather than at its library's poll.

## Contract fixtures

A contract fixture's builder and validator are `build_*()` and `validate_*()`
([Contract fixtures](contract-fixtures.md)). For a boundary inside one package they
live in `tests/fixtures/<module>.py`, importable as `tests.fixtures.<module>` by any
test in the package. For a boundary a separate, higher-level package consumes they
live in `src/<package>/fixtures/<module>.py` inside the producer's own source
package, installed with the producer's wheel, so the import mirrors the client import
it sits beside. A validator no test calls yet says in its module docstring which test
file is expected to call it.

## Test layout

A project's tests split into `unit/` and `integration/` under its own `tests/`, its
test target running both; a library's integration tests are in its
`tests/integration` ([Test levels](test-levels.md)). The `integration/` directory is
a package, so a module there may share a basename with one in `unit/`.

## Building tables

A test that needs a migrated database migrates it through the chain; building its
tables with SQLAlchemy's `create_all` proves nothing about the chain's schema
([Migration tests](migration-tests.md)).
