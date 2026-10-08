# Design

## Why the leak exists

The inventory writer is the only component that holds decrypted key material,
and it holds it for a reason: Ansible authenticates with a key file on disk, so
material stored encrypted in the registry has to become a file for the duration
of a run. That much is unavoidable.

What went wrong is narrower. The writer creates those files, records their paths
in a local list, uses the list only to report a count, and returns a single
path — the inventory file. The caller receives one artifact and can clean up one
artifact. The knowledge that other files exist stops at the end of the function.

The docstring papers over this by describing a cleanup that would work: the
files are deleted, it says, when the caller removes the inventory file's parent
directory. That directory is the process-wide temporary directory. A caller that
followed the instruction would delete every other tenant's temporary files, so
the instruction is not merely unfollowed, it is unfollowable.

## The fix is ownership, not more cleanup calls

The obvious repair is to return the companion paths alongside the inventory path
and unlink them in each caller's existing cleanup block. That works and is a
small diff.

It is rejected as the primary shape because it keeps the property that made the
defect possible: the number of files a caller must remember to remove is a
function of the hosts it passed in, and a future path that forgets one leaks a
private key rather than a harmless temporary. Two callers exist today and both
would be correct on the day of the change; the third is the problem.

Writing the inventory and its companion keys into one directory created per
invocation makes cleanup a single removal of a directory the writer owns
outright. A caller cannot partially clean up, and cannot clean up someone else's
files, because nothing else is in there. The count of files stops being
something a caller has to know.

It also removes a collision the current scheme avoids only by luck. Companion
files are named from the host name plus a nonce, so two concurrent operations
against one host produce distinct files — but the naming is the only thing
keeping them apart, and a per-invocation directory makes separation structural.

## Cleanup must cover the failing paths

The leak is worst where the code is least exercised. A run that succeeds reaches
its cleanup; a run that raises reaches whatever the caller's error handling
provides. The connectivity path already uses a `finally` block, and the job path
cleans up its variables file in one. The requirement is that key material is
covered by the same guarantee rather than by the success path alone, since a
failed authentication is exactly the case that leaves a key behind and exactly
the case an operator retries.

## The renderer's sentinel

Two functions produce inventory text: one on the registry service, which returns
a string, and one on the execution service, which writes a file and its
companion keys. They carry comments requiring that they not drift, because a
host that connects differently depending on which produced its inventory is a
defect visible on only one path.

They have already drifted, in the way those comments were meant to prevent. The
string-returning renderer emits a placeholder for embedded hosts and documents
that the file-writing one replaces it. The file-writing one builds its own text
from the host rows and never reads the renderer's output, so the placeholder is
never replaced by anything.

A string return cannot honestly express an embedded host: the key has to exist
as a file for the inventory line to mean anything, and a function that returns a
string writes no files. So the choice is between making the renderer write files
too — duplicating the execution service's responsibility and its cleanup problem
— or having it state plainly what it cannot express.

The second is preferred. The renderer's callers today are tests and a
human-readable listing; neither needs to authenticate. Making it refuse, or emit
a line that is visibly not a key path and documented as such, keeps one owner
for decrypted material instead of two. A single owner is also what makes the
directory-ownership decision above hold.

## What this change deliberately does not settle

Per-host key material becomes safe to use here. It does not become *used*.
Deciding that a rented host should carry its own key, generating the pair, and
getting the public half into that host's `authorized_keys` before the host is
registered are steps that live with host preparation, outside this repository.

The distinction matters for scope: this change can be verified entirely from
focused tests against the registry and the inventory writer, with no host
involved. The policy question cannot be verified without one.

## Verification

Verifiable from source and focused tests:

- An inventory written for an embedded host produces a readable key file during
  the operation, and no key file survives it.
- The same holds when the operation raises rather than returns.
- Two concurrent operations against one host do not share or remove each other's
  key material.
- A host registered with a key path produces an inventory naming that path and
  writes no key material at all.
- No inventory produced by any path contains an unresolvable placeholder in the
  key file position.

Needs no live host. The encryption round trip, the file lifetime, and the
inventory text are all observable in process.
