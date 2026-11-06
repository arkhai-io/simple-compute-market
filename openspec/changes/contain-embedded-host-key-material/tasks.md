# Implementation Tasks

Paths are relative to the repository root.

## Replanned against the reviewed design (2026-11-06)

Every section below was replanned against the design settled on 2026-11-06 and
reviewed in design reviews 10 and 19 (`reviews/10-design.triage.md`,
`reviews/19-design.triage.md`). The earlier plan's four sections were never
started. They edited the VM adapter's `services/ansible_service.py`,
`services/host_service.py` and `services/host_operations_service.py`, which
`bare-metal-mock-provisioned-deal` had already moved into the Ansible
distribution (`provisioning/compute/ansible/src/compute_provisioning_ansible/`),
and that move delivered what the earlier sections planned. Decrypted key files
and the variables file are owner-only and removed on every ending of a run, and
no second inventory renderer remains. Its reconciliation note of 2026-10-05 said
as much. What was left of it, a per-invocation directory and a renderer that
refuses, the reviewed design rejects (D3, D8). Git history holds the earlier
text.

Sections 1 to 5 go from the lower layer up: the compute family kit's host
authority (`provisioning/compute`), then the Ansible distribution
(`provisioning/compute/ansible`), then the provisioning service's composition
root (`provisioning/compute/service`). Section 6 is the closeout.

## 1. The host authority's internal execution read

Delivers `HostAuthority.execution_hosts`, the read readiness takes in place of
the public listing. Implements D5 (its input) and the MODIFIED requirement
"Connection secrets stay protected": the host authority returns a protected
envelope only through its internal reads for execution and readiness.

Files: `provisioning/compute/src/compute_provisioning/hosts/service.py`,
`provisioning/compute/tests/integration/test_host_authority.py`.

- [x] 1.1 Add `execution_hosts(self, *, enabled_only: bool = True) -> list[ExecutionHost]`
      to `HostAuthority`, beside `lookup`. It reads in one query, orders by
      `host_id`, and returns each host as an `ExecutionHost` carrying its full
      connection envelope, its protected values included. With `enabled_only`,
      disabled hosts are omitted. No route calls it, and every ordinary read
      (`list_hosts`, `get_host`, `host_definitions`) keeps returning protected
      values by scheme only. (D5)
      *Done:* `lookup` and `execution_hosts` share a module-level
      `_execution_host(host)` builder.
- [x] 1.2 Revise the module docstring's rule, which says that only `lookup`
      returns the full protected envelope. It should now say that only the
      internal reads return it: `lookup` for execution and `execution_hosts`
      for an executor's readiness. Every ordinary read, and every API, log and
      error surface, carries a protected value's scheme only. (MODIFIED
      "Connection secrets stay protected"; `AGENTS.md`, "Python comments and
      docstrings")
      *Done,* and the class docstring names the internal reads too. Left for
      section 4: `hosts/connection.py`'s module docstring says the codec
      decrypts "just in time for execution" only, which stays true until
      readiness decrypts; section 4 widens it to the in-memory readiness check
      the MODIFIED requirement admits (outside that section's file list).
- [x] 1.3 Add library integration tests in `test_host_authority.py`:
      - `execution_hosts()` returns the enabled hosts in `host_id` order. An
        embedded host's protected value is carried with its stored scheme and
        ciphertext, and a key-file host's `key_path` is carried in its public
        fields.
      - A disabled host is omitted by default and included with
        `enabled_only=False`.
      - An empty registry returns `[]`.
      - `list_hosts` still returns the same embedded host's protected value by
        scheme alone.

      (D5, MODIFIED "Connection secrets stay protected")
      *Done:* three tests against the module's real SQLite database and its
      fake codec, which reverses a token for its "protection": the ordered
      read with the embedded host's `ProtectedValue` and the key-file host's
      `key_path` (the listing check sits in the first test), the disabled-host
      filter both ways, and the empty registry.
- [x] 1.4 **Verification checkpoint.** Library integration: the compute family
      kit's suite, `make test-compute-provisioning`. Then `make test`.
      End-to-end: none. Nothing calls the read until section 5, and no
      end-to-end scenario is owed.
      Owed by validation: `tests.yml`, job `test · test-compute-provisioning`.
      The kit suite passes, including the new `execution_hosts` tests.
      *Evidence:* `make test-compute-provisioning` (unit and library
      integration), 530 passed. `make test`, exit 0. End-to-end confirmed:
      none.

*Handoff (section 1):* the fresh-context check found that the module
docstring's mention of readiness reading `execution_hosts` is true of the
read's purpose but not yet of any caller until section 5 wires it; it was kept
as task 1.2 prescribes. `ExecutionHost` is `(host_id, pool_id, connection)`
from `compute_provisioning.hosts`; readiness in section 4 can build its
fixtures with it directly.

## 2. Ansible output is kept only redacted

Delivers D2. Implements the requirement "Ansible output is kept only redacted
unless an operator configures otherwise".

Files: `provisioning/compute/ansible/src/compute_provisioning_ansible/ansible.cfg`,
`provisioning/compute/ansible/src/compute_provisioning_ansible/runner.py`
(`check_connectivity_with_inventory`),
`provisioning/compute/ansible/tests/unit/test_runner.py`.

- [x] 2.1 Remove `log_path = ./ansible.log` from the distribution's packaged
      `ansible.cfg`, so that under the service's default configuration Ansible
      writes no log file. Change nothing that would override an operator's own
      `ansible_cfg`. The runner sets no `ANSIBLE_LOG_PATH` and passes no
      environment of its own to Ansible's subprocesses. The VM domain's IaC
      `ansible.cfg`, used for running playbooks by hand, is not the service's
      configuration and is left as it is. (D2)
      *Done:* the file's header comment says why it names no log file and
      where an operator's own goes. Neither `subprocess.Popen` nor
      `subprocess.run` in the runner is given an `env`.
- [x] 2.2 Add a unit test that the packaged configuration
      (`DEFAULT_ANSIBLE_CONFIG`, read with `configparser`) states no `log_path`
      in any section. This is the lowest level that can prove the scenario "A
      playbook runs under the packaged configuration": without `log_path` or
      `ANSIBLE_LOG_PATH`, Ansible writes no log. The job's logs are already
      redacted, as `test_executor.py`'s redaction cases prove. (D2)
      *Done:* `test_the_packaged_configuration_names_no_log_file` (unit) reads
      the file with `configparser` and checks the defaults and every section.
      It proves the file states no `log_path`; that Ansible then writes no log
      is Ansible's documented behaviour, not something the test observes.
- [x] 2.3 Pass the `detail` that `check_connectivity_with_inventory` returns
      through `redact_ansible_output`, with the generic secret fields only,
      since a probe runs no domain's playbook. Do this in both branches: the
      output of `ansible -m ping`, and the text of an exception raised while
      running it. The timeout's detail is fixed text. (D2)
- [x] 2.4 Add unit tests in `test_runner.py` for the check, with a stand-in
      `ansible` executable placed first on `PATH`
      (`monkeypatch.setenv("PATH", …)`). That stand-in is the seam; the
      `subprocess` import is not patched (`docs/development/TESTING.md`, "Unit
      Tests", mocking convention).
      - A stand-in whose output, in both the reachable and the unreachable
        case, carries `password: hunter2` and an identity-file argument
        `-i /home/appuser/.ssh/id_test` returns a detail holding neither value.
        These are fixture values, never real credentials.
      - The same stand-in prints the `ANSIBLE_CONFIG` and `ANSIBLE_LOG_PATH` it
        received. The first is the test's own value, and the second is absent,
        so the runner passes an operator's configuration through unchanged.
      - A stand-in the operating system cannot execute covers the exception
        branch: its detail is the redacted form of the error's text.

      (D2; the scenarios "A connectivity check's output carries a secret" and
      "An operator configures a log file")
      *Done:* `test_a_connectivity_checks_output_is_returned_redacted`, both
      cases (unit; the stand-in is a `/bin/sh` script, writing to stdout and
      exiting 0 when reachable, to stderr and exiting 1 when not), and
      `test_an_error_running_the_check_is_returned_redacted`, whose stand-in
      has no execute bit and is alone on `PATH`, so `subprocess.run` raises
      `PermissionError`. That error's text names only `ansible` and carries
      nothing credential-shaped, so the exception case proves only that the
      branch answers unreachable with the error's text: it would pass without
      the redactor, and the redaction call on that branch is untested. The
      one seam that could plant a secret there is a contrived settings object
      whose arithmetic raises, which was not written.
      The environment case proves the scenario "An operator configures a log
      file" only for the connectivity check's subprocess: it inherits the
      process's `ANSIBLE_CONFIG` and is given no `ANSIBLE_LOG_PATH`. The
      playbook subprocess's missing `env` rests on reading the code (2.1), and
      the profile's `ansible_cfg` reaching `ANSIBLE_CONFIG` is task 5.3's.
- [x] 2.5 **Verification checkpoint.** Unit: the Ansible distribution's suite,
      `make test-compute-provisioning-ansible`. Then `make test`.
      End-to-end: none in a lane. Every lane runs mocked executors and the mock
      runner, which starts no Ansible. The real-provisioning markers
      `e2e_vm_real_provisioning` and `e2e_bare_metal_real_provisioning` would
      run Ansible under the packaged configuration, but they run in no lane.
      None is owed.
      Owed by validation: `tests.yml`, job `test · test-compute-provisioning-ansible`.
      The distribution's suite passes, including the configuration and
      connectivity-redaction tests.
      *Evidence:* `make test-compute-provisioning-ansible` (unit), 170 passed,
      4 skipped (`test_codec.py`'s real-Ansible cases, skipped without
      `ansible-playbook`, as before). `make test`, exit 0. End-to-end
      confirmed: none.

*Handoff (section 2):* the fresh-context check held that the stand-in
connectivity tests start a real `/bin/sh` subprocess, which `TESTING.md` would
place in integration rather than unit. They stay in `tests/unit/` as task 2.4
prescribes, beside the existing real-subprocess streaming test in the same
module; the distribution has no `tests/integration` (its `testpaths` names
only `tests/unit`). Left for the round's review to weigh, not changed here.
The service's `.venv` holds a built copy of this distribution, so a
service-side run sees the new `ansible.cfg` and runner only after the wheel is
rebuilt and reinstalled, which `make test` does. *Correction (section 4):*
`make test` reinstalls but does not rebuild `.dist`, so this section's
`make test` ran the service against an older wheel; see section 4's handoff.

## 3. A protected key that cannot be decrypted is named at dispatch and at the probe

Delivers D4. Implements the requirement "A protected key that cannot be
decrypted is named, not hidden": the codec's error, the job path, and the
connectivity check.

Files: `provisioning/compute/ansible/src/compute_provisioning_ansible/connection.py`,
`__init__.py` (the export), `runner.py` (`write_inventory`), `probes.py`;
tests in `test_ssh_connection.py`, `test_runner.py`, `test_executor.py` and
`test_probes.py` under `provisioning/compute/ansible/tests/unit/`.

- [x] 3.1 Define `ProtectedKeyUnreadableError`, a `ValueError` subclass, in
      `connection.py`, export it from the distribution, and give it a `host_id`
      attribute. Change the signature to
      `SshConnectionCodec.decrypt_private_key(ciphertext, *, host_id)`.
      - It catches both of Fernet's failures and raises the typed error:
        `InvalidToken` (a key protected under another key, or malformed
        ciphertext) and the key-format `ValueError` (no key configured).
      - The error's message names the host's protected key as unreadable under
        the configured `ssh_decryption_key` and how to recover: restore the key
        it was protected under, or submit the host's private key again.
      - The message carries no ciphertext and no key material.
      - The codec uses `host_id` only for the error.
      - Update the method's docstring to match. (D4)
      *Done, differing from the plan in two ways:*
      - The codec checks for an unconfigured key itself, before Fernet, so
        that cause's message says "because no ssh_decryption_key is
        configured" and names the one recovery that works there, configuring
        the key it was protected under: without a key a private key cannot be
        submitted again (`build` refuses it). Every other cause says "under
        the configured ssh_decryption_key" with both recoveries D4 names. The
        catch is `(InvalidToken, ValueError)`, the `ValueError` being
        `market_config`'s for a configured key that is not a Fernet key; it
        would also catch a plaintext that is not UTF-8, which the codec never
        writes.
      - Catching `InvalidToken` imports `cryptography.fernet`, so the
        distribution now declares `cryptography>=42.0` at runtime (it was in
        the `dev` group only) and `make lock` was run. The locks of the
        distribution, the provisioning service and both domain adapters gained
        the edge; `cryptography` was already in each of them.
- [x] 3.2 Have `write_inventory` pass the target's `host_id` to
      `decrypt_private_key`. Its existing partial-write cleanup stays as it is,
      and the job executor lets the error propagate: the job engine records it
      with its message and never retries it, as it does
      `RelayUnusableAtExecutionError`. (D4)
      *Done:* the executor is unchanged; the engine's catch-all records an
      exception from `execute` as `Internal error: <message>` and fails the
      job without a retry (`jobs/engine.py`). That record is section 5's to
      prove through the application.
- [x] 3.3 Have `probe_connectivity` catch `ProtectedKeyUnreadableError` and
      return `ConnectivityResult(host=<host_id>, reachable=False, detail=<its message>)`.
      Update its docstring. (D4)
      *Done:* only `write_inventory` sits inside the `try`; the ping runs
      outside it, under the inventory's context manager.
- [x] 3.4 Add unit tests:
      - In `test_ssh_connection.py`: each cause (protected under another key,
        malformed ciphertext, a codec built with no key) raises
        `ProtectedKeyUnreadableError` with the given `host_id`. Its message
        names the host and the recovery, and contains neither the ciphertext
        nor the plaintext. Keys come from `Fernet.generate_key()`, and each test
        module says they protect nothing real.
      - In `test_runner.py`, extending
        `test_a_key_that_cannot_be_decrypted_leaves_nothing_behind`: the error
        is the typed one, naming the failing target's host.
      - In `test_executor.py`: a run against a host whose key was protected
        under another key raises the typed error out of `execute`, starts no
        playbook, and leaves no key file, inventory or variables file.
      - In `test_probes.py`: `probe_connectivity` over a real `AnsibleRunner`
        whose codec holds another key answers unreachable, with the error's
        message as its detail, and runs no subprocess.

      (D4)
      *Done (all unit):* `test_a_protected_key_that_cannot_be_decrypted_is_named`
      over the three causes and a configured key that is not a Fernet key,
      asserting each whole message, and that neither the ciphertext, the PEM
      text, nor either Fernet key appears in it; plus a decrypt that
      succeeds; the extended runner
      test also checks the error's cause is Fernet's `InvalidToken`;
      `test_a_key_that_cannot_be_decrypted_fails_the_run_naming_the_host`
      runs the real `write_inventory` over a temporary directory that is empty
      afterwards; `test_a_host_whose_key_cannot_be_decrypted_is_answered_unreachable`
      uses the module's `_ProbingRunner`, a real `AnsibleRunner` whose ping is
      overridden, and shows the ping was never called. "Runs no subprocess"
      is shown that way, not by observing process creation.
- [x] 3.5 **Verification checkpoint.** Unit: the Ansible distribution's suite,
      `make test-compute-provisioning-ansible`. Then `make test`.
      End-to-end: none. No lane registers an embedded host, and the mock runner
      never decrypts. None is owed: section 5 proves the running application's
      behaviour through the canonical client.
      Owed by validation: `tests.yml`, job `test · test-compute-provisioning-ansible`.
      The distribution's suite passes, including the typed-error, executor and
      probe tests.
      *Evidence:* `make lock`; `make test-compute-provisioning-ansible`
      (unit), 177 passed, 4 skipped (the real-Ansible codec cases, as
      before); `make test`, exit 0; `make check-packaging`, exit 0, the
      architecture rules holding. `make test` ran before the fresh-context
      fixes, which changed only the codec's message text and the codec test,
      so the distribution's suite was run again after them. End-to-end
      confirmed: none.

*Handoff (section 3):* the fresh-context check found the error's docstring
and `decrypt_private_key`'s naming readiness before readiness decrypts; both
now describe execution only, and section 4 widens them along with the module
docstrings that say the codec decrypts "only to materialize the connection
for one execution" (`compute_provisioning_ansible/connection.py`) and "just
in time for execution" (`compute_provisioning/hosts/connection.py`). It also
found that "submit the host's private key again" is no recovery when no key is
configured, so that cause names only configuring the key. Two departures from
D4's wording are recorded in 3.1's note rather than in `design.md`, for the
round's review to judge: the no-key cause's own message and recovery, and the
distribution's runtime `cryptography` dependency, which catching Fernet's
`InvalidToken` needs (the alternative, `market_config` raising an error of its
own, would widen this change into `kit/config`). Section 4's readiness calls
`decrypt_private_key(ciphertext, host_id=...)` and reports `str(error)`.

## 4. Readiness checks each host as execution would

Delivers D5's readiness behaviour. Implements the MODIFIED requirement
"Execution readiness is reported in system status", the readiness clause of "A
protected key that cannot be decrypted is named, not hidden", and the in-memory
decryption the MODIFIED "Connection secrets stay protected" admits.

Files: `provisioning/compute/ansible/src/compute_provisioning_ansible/readiness.py`,
`provisioning/compute/ansible/tests/unit/test_readiness.py`.

- [x] 4.1 Change `ansible_readiness_component`'s host input. It takes a
      callable listing the enabled hosts as `ExecutionHost`s, in place of
      `list_hosts`, and the `ssh` codec (`SshConnectionCodec`). Rework
      `collect_ssh_keys_from_hosts` accordingly. If the callable raises, the
      component reports the host registry unreadable, as it does today.
      Imports go at module level. (D5)
      *Done:* the keywords are `execution_hosts` and `ssh_codec`. Only the
      call that lists the hosts sits inside the registry's `try`; the list is
      taken whole first. `collect_ssh_keys_from_hosts(hosts, ssh_codec)` now
      returns a `HostKeyReport` (`ssh_keys`, `host_reasons`), exported from
      the module. The imports are at module level, including `inventory_target`
      from `runner.py`, which raises no cycle.
- [x] 4.2 Read each host as execution reads it:
      - Skip a host whose connection kind is not `ssh`: no Ansible executor
        reaches it.
      - Read each `ssh` host through `runner.inventory_target`. For a host it
        refuses (an unserved version, such as `ssh` version 1, or a connection
        naming no key), add a not-ready reason naming the host and carrying the
        refusal, and leave the host out of `ssh_keys`.
      - Group a key file by path and examine it, as today.
      - Decrypt an embedded key in memory with
        `decrypt_private_key(…, host_id=…)`, discard the plaintext at once, and
        write nothing. Report `exists: true` when it decrypts. When it fails,
        report `exists: false` with a reason naming the host, from the typed
        error's message.
      - Report every other host as it would be without the failing one.

      (D5, 19 F1)
      *Done:* a refusal's reason reads `host '<id>' cannot be executed
      against: <inventory_target's message>`, unless that message already
      names the host, as the no-key refusal does; for version 1 it names the
      version served and says to re-register at it. A decryption failure's
      reason is the typed error's message as it is. The decrypted plaintext is
      never bound to a name; that nothing is written rests on reading the
      code, since no test observes the filesystem around a status read.
- [x] 4.3 Make these reasons count as a missing key file's do: once any
      composed Ansible executor is real. Mocked executors need no keys. The
      detail keeps its fields and schema version 1. Rewrite `SshKeyInfo`'s
      field descriptions:
      - for an embedded key, `exists` means it decrypts under the configured
        key;
      - the module and class docstrings name the hosts' stored connections as
        execution reads them.

      The detail carries no plaintext and no ciphertext. (D5)
      *Done:* host reasons follow the key-file reasons in `not_ready_reasons`.
      `SshKeyInfo` gained a class docstring saying a refused host has no
      entry. *Outside the plan's file list:* the module docstrings of
      `compute_provisioning_ansible/connection.py` and
      `compute_provisioning/hosts/connection.py`, and `decrypt_private_key`'s,
      now also name the in-memory readiness check, as section 3's handoff
      left for this section.
- [x] 4.4 Add unit tests in `test_readiness.py`. Rewrite its host fixtures as
      `ExecutionHost`s with `ConnectionEnvelope`s protected by a real codec,
      under a `Fernet.generate_key()` key that the module says protects nothing
      real. Cover each case:
      - an embedded key that decrypts reads `exists: true`, and the component
        is ready when the other checks pass;
      - a key protected under another key reads `exists: false`, with a reason
        naming the host, and another host is reported unchanged;
      - malformed ciphertext, and a codec built with no key;
      - an `ssh` version-1 host whose key file exists gives a reason naming the
        host and the version served, is absent from `ssh_keys`, and leaves the
        other host's entry unchanged;
      - a host of another connection kind is skipped;
      - an empty host list is ready;
      - with mocked executors only, a key that will not decrypt is reported but
        is not a reason;
      - a raising host read reports the registry unreadable;
      - the detail's JSON contains neither the ciphertext nor the plaintext
        (extending `test_the_detail_discloses_no_key_material`).

      (D5; the readiness scenarios of the delta)
      *Done (unit):* every existing test rewritten onto `ExecutionHost`s
      whose embedded keys a real `SshConnectionCodec` protected, plus eight
      new test functions (ten cases) covering the listed ones; the three
      failing causes are one parametrized test whose expected reason is the
      codec's own message for that ciphertext, and whose other host is a key
      file. Beyond the list: a version-1 host whose protected key decrypts
      (the delta scenario's second form), and a connection naming no key. The
      raising host read is the existing parametrized test, both mocked and
      real. The delta's "nothing is written to storage" is not observed by a
      test (see 4.2).
- [x] 4.5 **Verification checkpoint.** Unit: the Ansible distribution's suite,
      `make test-compute-provisioning-ansible`. Then `make test`.
      End-to-end: none in this section. The composition root is not yet wired
      to the new input; section 5 wires it and names the smoke that reads it.
      Owed by validation: `tests.yml`, job `test · test-compute-provisioning-ansible`.
      The distribution's suite passes, including the reworked readiness tests.
      *Evidence:* `make test-compute-provisioning-ansible` (unit), 187 passed,
      4 skipped (the real-Ansible codec cases, as before). `make dist`, then
      `make test`, exit 0, the provisioning service's suite (644 unit, 579
      application integration) passing against the rebuilt wheels with
      section 5's wiring (see the handoff). After the version bumps:
      `make lock`, `make dist`, `make test` exit 0, `make check-packaging`
      exit 0.
      *End-to-end, corrected:* with 5.1 and 5.2 in this commit the
      composition root is wired, so the `provisioning_readonly` smoke
      `test_status_reports_execution_and_the_ansible_component`
      (`e2e-tests/tests/smoke/test_provisioning_smoke.py`) reads the new
      readiness on a deployed release, as regression evidence only: no lane
      registers a host whose connection readiness would refuse.
      *Owed by validation, corrected:* also `tests.yml`, job
      `test · test-provisioning`; the service suite passes with the new
      composition.

*Handoff (section 4):* the component's new signature breaks the provisioning
service's composition root, which passed `list_hosts=`, so `make test` could
not pass at this section's commit with the plan's file list. Tasks 5.1 and 5.2
(the container's `_make_status_components` and its provider, and the
integration harness's call) were therefore implemented in this section's
commit, and are checked under section 5 with a note saying so. Neither
`make test` nor `make test-provisioning` rebuilds `.dist`: the service installs
the internal wheels last built there, so a run after a source change proves
nothing about the service until `make dist` (CI runs `make dist-ci`) rebuilds
them. A first `make test-provisioning` here passed against section 3's wheel,
and a first `make test` failed on the stale readiness; both are void. Sections
1 and 2's `make test` runs had the same blind spot for the service: section
1's read was not yet called, and section 2's `ansible.cfg` and probe were not
exercised by the service's suite against the new wheel until this section's
run. Section 3's `make test` followed a `make lock`, which rebuilds `.dist`,
so its service run had section 3's code as it stood before that section's
message fixes.

The fresh-context check found no version bump for packages whose published
API changed: `arkhai-compute-provisioning` gained `execution_hosts` (section
1), and `arkhai-compute-provisioning-ansible` changed
`decrypt_private_key`'s and `ansible_readiness_component`'s signatures
(sections 3 and 4). Per `docs/development/RELEASING.md`, "Versioning policy",
this commit bumps `arkhai-compute-provisioning` to 0.26.0 (new API, minor),
`arkhai-compute-provisioning-ansible` to 0.8.0 (incompatible before 1.0,
minor), and `arkhai-compute-provisioning-service` to 0.24.0, its readiness
reporting differently, as an earlier change bumped it for a behaviour change;
the service's floors on the two move to the new versions, and `make lock`
refreshed the locks. The domain adapters call neither changed function, so
their floors stay. The readiness detail keeps schema version 1, as D5 decided;
the fresh-context check flagged that `RELEASING.md` says a versioned envelope
is never changed in place, which is for the round's review to weigh against
D5. Under
mocked executors only, a host whose connection execution refuses appears
nowhere in the detail (no entry, and host reasons count only once an executor
is real); the docstring says so.

## 5. Composition and the running application

Delivers the composition root's wiring of D5, and proves D2, D4 and D5 through
the canonical client. Implements the scenarios of "A protected key that cannot
be decrypted is named, not hidden" and of the MODIFIED readiness requirement at
the application level, and the connectivity-redaction scenario of "Ansible
output is kept only redacted unless an operator configures otherwise".

Files: `provisioning/compute/service/src/compute_provisioning_service/container.py`
(`_make_status_components` and its provider);
`provisioning/compute/service/tests/integration/conftest.py`, which composes
readiness as the container does; a new integration module
`provisioning/compute/service/tests/integration/test_unreadable_host_key_api.py`;
and, if no test covers `apply_ansible_config`, a unit test in
`provisioning/compute/service/tests/unit/`.

- [x] 5.1 Make `_make_status_components(job_executors, host_authority, connection_codecs)`
      pass readiness `host_authority.execution_hosts(enabled_only=True)` and the
      `ssh` codec, `connection_codecs.codec(SSH_CONNECTION_KIND)`, in place of
      the public listing. Add `connection_codecs` to its container provider,
      and update its docstring. (D5)
      *Done in section 4's commit,* so that commit's `make test` could pass
      (section 4's handoff). The codec is looked up once, when the components
      are composed; the hosts are read on each status read.
- [x] 5.2 Have the integration harness's `conftest.py` call
      `_make_status_components` with the harness's own `connection_codecs`, so
      status is composed there as it is in production. (D5;
      `docs/development/TESTING.md`, "Integration Tests")
      *Done in section 4's commit,* for the same reason; the harness's codecs
      hold `TEST_CONNECTION_KEY`.
- [x] 5.3 Add a unit test of `app_runtime.apply_ansible_config` if none exists.
      It exports the profile's `ansible_cfg` verbatim when set and
      `DEFAULT_ANSIBLE_CONFIG` otherwise, and sets no `ANSIBLE_LOG_PATH`. (D2;
      the scenario "An operator configures a log file")
      *Done:* none existed. *Outside the plan's file list:*
      `apply_ansible_config` gained optional `config` and `environ`
      parameters, the service's settings and `os.environ` when omitted (the
      startup step passes neither), so the test injects both rather than
      replacing the module's imported `settings` or touching the process
      environment (`TESTING.md`, "Unit Tests", mocking convention).
      `tests/unit/test_apply_ansible_config.py` (unit): an operator
      configuration stating a `log_path` is exported verbatim; empty, blank,
      null and absent `ansible_cfg` export the packaged configuration; in
      every case `ANSIBLE_CONFIG` is the only variable written, so no
      `ANSIBLE_LOG_PATH`. With section 2's connectivity test this proves the
      scenario for the exported configuration and the check's subprocess;
      that the playbook subprocess inherits it rests on the runner passing no
      `env`.
- [x] 5.4 Add application integration tests in
      `test_unreadable_host_key_api.py`, through the canonical client.
      **Setup:**
      - Seed an enabled host whose protected key was encrypted under a
        `Fernet.generate_key()` key other than the harness's
        `TEST_CONNECTION_KEY`, the way `test_hosts_api.py`'s
        `TestHostsStoredAtVersion1._seed` seeds a protected row.
      - Register a second host with an embedded key under
        `TEST_CONNECTION_KEY`.
      - Hand `fake_ansible.write_inventory` to a real `AnsibleRunner` holding
        `TEST_CONNECTION_KEY`, as `TestHostsStoredAtVersion1` does.

      **Cases:**
      - A VM create job against the first host ends `failed`. Its error names
        the host and the recovery and carries no ciphertext, and no retry is
        scheduled.
      - Its connectivity check answers unreachable, with that message as its
        detail.
      - System status's `ansible` component lists a reason naming the first
        host, and reports its key `exists: false` and the second host's
        `exists: true`. The status JSON carries neither host's ciphertext.
      - A host seeded at `ssh` version 1 gives a reason naming it and the
        version served.
      - A connectivity check of a registered host is handed to a real runner
        whose stand-in `ansible`, first on `PATH`, prints a credential-shaped
        value. The route returns it redacted.

      (D2, D4, D5)
      *Done (application integration, through the canonical clients):* five
      tests. The unreadable host is seeded directly in each test that needs
      it (the API protects every key under the configured key, so cannot
      store one protected under another); the second host is registered
      through `client.family.register_host` in the status test, the one that
      reads it. The job test asserts the whole message is in the job's error
      (the engine prefixes `Internal error: `), `retry_count` 0 and no
      `next_retry_at`, and no playbook started. The connectivity test asserts
      the detail equals the message and that the ping was never called. The
      status test asserts the host's reason, both keys' `exists`, no reason
      naming the second host, and that neither ciphertext nor the PEM text is
      in the status JSON. The harness's playbook path does not exist, so the
      component is not ready in every harness test; the tests assert the
      host's own reason, not readiness alone. The redaction test hands both
      `write_inventory` and `check_connectivity_with_inventory` to a real
      runner over a `/bin/sh` stand-in `ansible`, as the task prescribes. The
      fresh-context check noted that this reaches below the point
      `TESTING.md` says to mock at (the runner, which wraps the subprocess
      boundary) and repeats section 2's unit proof; it is kept as planned and
      left for the round's review.
- [x] 5.5 **Verification checkpoint.** Application integration: the
      provisioning service's suite, `make test-provisioning`, including the
      existing `test_system_api.py`, `test_hosts_api.py` and
      `test_vms_api.py`. Then `make test`.
      End-to-end: `provisioning_readonly` smoke —
      `test_status_reports_execution_and_the_ansible_component` and
      `test_connectivity_check_on_first_host_if_available` in
      `e2e-tests/tests/smoke/test_provisioning_smoke.py`. The validation's Helm
      part runs them, and they exercise the new readiness wiring and the probe
      on a deployed release as regression evidence. No lane scenario registers
      a host whose key cannot be decrypted, and the lanes' executors are
      mocked, so none exercises the new failure behaviour. None is owed:
      application integration proves it.
      Owed by validation: `tests.yml`, job `test · test-provisioning`. The
      service suite passes, including `test_unreadable_host_key_api.py`.
      *Evidence:* `make dist`, then `make test`, exit 0. After the
      fresh-context fixes (the `apply_ansible_config` seam and its unit test,
      service code only): `make test-provisioning`, 649 unit passed, 584
      application integration passed; `make check-packaging`, exit 0;
      `make check-change`, every check passed. *End-to-end, confirmed with
      qualifications:* both smoke tests exist under `provisioning_readonly`,
      unrun until validation. `test_status_reports_execution_and_the_ansible_component`
      checks only that the `ansible` component is present, so it shows the
      readiness wiring (in place since section 4's commit) composes and
      answers on a deployed release, not what it reports; under the lanes'
      mocked executors host reasons do not count.
      `test_connectivity_check_on_first_host_if_available` skips when no host
      is registered, so it reaches the probe only on a release with a host.

*Handoff (section 5):* sections 1 to 5 are implemented; closeout (6) remains.
For closeout's comment check (6.1), the change also added or revised
comments outside the files 6.1 names: `hosts/connection.py`'s module
docstring, `compute_provisioning_ansible/connection.py`'s module docstring,
`runner.py`'s `write_inventory` and `check_connectivity_with_inventory`
docstrings, and `app_runtime.py`'s `apply_ansible_config`. For 6.3, the
readiness detail's `exists` and its omission of a refused host are the
behaviour to check "Execution readiness is reported in system status"
against. Three items are left for the round's review, recorded in their
sections: the stand-in-subprocess tests' test level (section 2's and 5.4's),
the departures from D4's wording and the distribution's runtime `cryptography`
dependency (3.1), and the readiness detail keeping schema version 1 against
`RELEASING.md`'s rule on versioned envelopes (section 4's handoff). To prove
anything about the service after changing a package it installs, run
`make dist` before `make test` (section 4's handoff).

## 6. Closeout

Per `openspec/README.md#plan-closeout-requirements`, in this order. Closeout
changes documentation only: a part needing a code edit returns the change to
implementation.

- [ ] 6.1 **Comment hygiene — confirm.** Run `make check-comment-hygiene`, and
      read the comments and docstrings this change added or revised for any
      that narrate the review or migration that introduced them. These are:
      `hosts/service.py`'s module docstring and `execution_hosts`;
      `connection.py`'s typed error and `decrypt_private_key`; `probes.py`;
      `readiness.py`'s docstrings and field descriptions; `ansible.cfg`; and
      `container.py`'s `_make_status_components`. Anything to rewrite returns
      the change to implementation.
- [ ] 6.2 **Import placement — confirm.** Check the imports this change added,
      in `readiness.py`, `probes.py`, `connection.py`, `container.py`, and the
      new tests, for any still local without a recorded reason. One that should
      move returns the change to implementation.
- [ ] 6.3 **Documentation compliance.** Re-check D1–D8 against
      `openspec/README.md`'s placement rules, and the permanent documents
      against the code they describe:
      - "Connection secrets stay protected" and "Execution readiness is
        reported in system status" against `execution_hosts` and `readiness.py`;
      - the operator handbook's host-definitions section against the export and
        the import route.
- [ ] 6.4 **Narrative compression.** Compress completed-task notes to final
      behaviour, material validation evidence, deferred work (D3's revisit
      trigger stays in `design.md`), and permanent-documentation destinations,
      moving durable rationale into `design.md` first.
- [ ] 6.5 **Roadmap currency (D7).** In `docs/development/ROADMAP.md`, "Goal 1 —
      Consolidate physical-resource authority in the provisioning service":
      - Remove the gap row "One SSH key reaches every host in an environment,
        so a host prepared by another party cannot be registered with its own
        credential".
      - Add to the goal's current state that a host may be registered with its
        own key material through the host API, decrypted only for the
        operation that uses it, and that a key that cannot be decrypted is
        named at dispatch, at the connectivity check, and in readiness.

      Name the edit in the design-promotion record.
- [ ] 6.6 **Campaign index currency (D6).** In `openspec/changes/README.md`,
      "Lesser goal — Reach hosts and VMs that have no inbound route":
      - Update this change's row.
      - Remove the graph line `contain-embedded-host-key-material ──►
        relay-vm-access-without-a-dashboard §8 live verification`.
      - Rewrite the paragraph that begins "`contain-embedded-host-key-material`
        is what allows a host prepared by someone else to be registered at
        all" to what is true: per-host keys are registered through the host
        API, and this change names a key that cannot be used.
      - Correct the relay row's Notes, which say task 2A.7 "is implemented in"
        this change: its requirement is met by the existing variables-file
        handling, and the per-operation directory is rejected in this change's
        D3.

      Leave other rows' `Depends on` alone. Run `make check-change-index`.
- [ ] 6.7 **Packaging.** Run `make check-packaging` and resolve every failure it
      reports. A failure needing a code or lock change returns the change to
      implementation. Then run
      `make check-architecture-change CHANGE=contain-embedded-host-key-material`.
      No exception row is expected, since no new edge crosses a layer.
- [ ] 6.8 **End-to-end pipeline.** Record the passing run the latest validation
      names, its result, and the scenarios that exercise this change: the
      `provisioning_readonly` smoke of section 5, as regression evidence for
      the readiness wiring and the probe. Record also that no lane scenario
      exercises an unreadable key, the log file, or connectivity redaction,
      which application integration proves. If the pipeline cannot run, record
      an explicit blocker naming its cause and the change that owns it, with
      the validations it gates treated as unrun.
- [ ] 6.9 **Promotion.** Write the permanent documents this change owes, and
      complete the design-promotion record from the destinations below.
      - In `docs/operator-handbook.md`, a new section "## Ansible configuration",
        placed before "## Payments access". It covers:
        - the service runs Ansible under its packaged configuration, which
          keeps no log file, unless the profile's `ansible_cfg` names another;
        - a `log_path` in an operator's own configuration receives Ansible's
          unredacted output, in the provisioning container;
        - a job's logs and a connectivity check's result are kept redacted.

        (D2)
      - In `docs/operator-handbook.md`, under "### Host definitions", a new
        subsection "#### A host's protected key no longer decrypts". It covers
        what the job error, the connectivity result and readiness show, and the
        recovery: restore the `ssh_decryption_key` the key was protected under,
        or submit the host's private key again through `POST /api/v1/hosts`,
        `PUT /api/v1/hosts/{host_id}` or the INI import's `embedded` mode. (D4,
        D5)
      - In `openspec/changes/relay-vm-access-without-a-dashboard/`, revise these
        to the requirement the existing handling meets:
        - `tasks.md` task 2A.7: the variables file is created owner-only and
          `O_EXCL` and removed on every ending of the run, which meets
          `physical-provisioning`'s "Relay admission tokens are resolved at
          execution". Note that a per-operation directory was weighed and
          rejected in this change's D3, with D3's revisit trigger.
        - The handoff note under "## Implementation progress", the "*Owned
          elsewhere:*" item.
        - `design.md`'s paragraph beginning "The resolved variables file is
          secret material".

        Ticking 2A.7 stays with that change's closeout. Apply the same
        correction to the two other places that change states this change's
        old role:
        - its design-promotion row "One SSH key currently reaches every host…;
          the fix is owned by `contain-embedded-host-key-material`";
        - its sequencing paragraph calling this change "a practical
          prerequisite for section 8".

        (D6)
      - `openspec/specs/physical-provisioning/spec.md` is written by the
        archive in 6.11, not by hand. The record names it all the same.

      `physical-provisioning` has no `index.md`, so no index entry is written.
      No `architecture.md`, `docs/development/ARCHITECTURE.md` or
      `openspec/specs/README.md` change is owed.
- [ ] 6.10 **Documentation citations.** After promotion, run
      `make check-doc-citations CHANGE=contain-embedded-host-key-material` and
      resolve every match. Then run
      `openspec validate contain-embedded-host-key-material --strict`.
- [ ] 6.11 **Archival.** Last, once every other part is checked, run
      `openspec archive contain-embedded-host-key-material -y`. It merges the
      two ADDED and two MODIFIED requirements into
      `openspec/specs/physical-provisioning/spec.md`, with no `--skip-specs`,
      and moves the change under `openspec/changes/archive/`. Point the index
      row at the archived directory, and run `openspec validate --specs --strict`.

Planned promotion destinations (6.9):

| Accepted decision | Permanent location |
|---|---|
| D1 — the change covers the secret-lifetime gaps that remain | no permanent destination; the index row and the promoted requirements carry its scope |
| D2 — the packaged configuration names no log file, an operator's own is not overridden, and the connectivity result is redacted | `openspec/specs/physical-provisioning/spec.md#requirement-ansible-output-is-kept-only-redacted-unless-an-operator-configures-otherwise`; `docs/operator-handbook.md#ansible-configuration` |
| D3 — the existing transient files keep their layout | no permanent destination; "Connection secrets stay protected" governs the layout, and the revisit trigger stays in `design.md` |
| D4 — a protected key that cannot be decrypted is named at dispatch and at the probe | `openspec/specs/physical-provisioning/spec.md#requirement-a-protected-key-that-cannot-be-decrypted-is-named-not-hidden`; `docs/operator-handbook.md#a-hosts-protected-key-no-longer-decrypts` |
| D5 — readiness reads hosts through `execution_hosts`, decrypts embedded keys in memory, and refuses a stored connection as execution does | `openspec/specs/physical-provisioning/spec.md#requirement-execution-readiness-is-reported-in-system-status`; `#requirement-connection-secrets-stay-protected`; `docs/operator-handbook.md#a-hosts-protected-key-no-longer-decrypts` |
| D6 — relay task 2A.7's requirement is met by the existing variables-file handling; no prerequisite edge | `openspec/changes/README.md` (the relay row, graph and paragraph); `openspec/changes/relay-vm-access-without-a-dashboard/tasks.md` (2A.7, the handoff note, the promotion row, the sequencing paragraph) and `design.md` |
| D7 — per-host keys are registered through the host API and diagnosed when unusable | `docs/development/ROADMAP.md#goal-1--consolidate-physical-resource-authority-in-the-provisioning-service` |
| D8 — two added and two modified requirements | `openspec/specs/physical-provisioning/spec.md`, by the archive |

## Validation evidence

| Suite | Baseline |
|---|---|
| `make test` unit, `provisioning/compute/service` | 522 passed |
| `make test` integration | 196 passed |
| `make test`, `domains/vms/provisioning/iac` | 52 passed |

The earlier plan measured these baselines on the delivered tree before any work
in this change. No suite here needs Ansible or a live host.
