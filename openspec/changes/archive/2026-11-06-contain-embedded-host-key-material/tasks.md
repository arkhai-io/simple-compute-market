# Implementation Tasks

Paths are relative to the repository root.

## Replanned against the reviewed design (2026-11-06)

Every section below was replanned against the design settled on 2026-11-06 and
reviewed in design reviews 10 and 19 (`reviews/10-design.triage.md`,
`reviews/19-design.triage.md`). The earlier plan's four sections were never
started: `bare-metal-mock-provisioned-deal` had moved their files into the
Ansible distribution (`provisioning/compute/ansible/src/compute_provisioning_ansible/`)
and delivered what they planned, owner-only decrypted key files and variables
file removed on every ending of a run, and a single inventory renderer. What was
left of it, a per-invocation directory and a renderer that refuses, the reviewed
design rejects (D3, D8). Git history holds the earlier text.

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
      *Done:* `lookup` and `execution_hosts` share `_execution_host(host)`.
- [x] 1.2 Revise the module docstring's rule, which says that only `lookup`
      returns the full protected envelope. It should now say that only the
      internal reads return it: `lookup` for execution and `execution_hosts`
      for an executor's readiness. Every ordinary read, and every API, log and
      error surface, carries a protected value's scheme only. (MODIFIED
      "Connection secrets stay protected"; `AGENTS.md`, "Python comments and
      docstrings")
      *Done,* in the module and class docstrings.
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
      *Done:* three library integration tests over the module's SQLite
      database and fake codec; the listing check sits in the first.
- [x] 1.4 **Verification checkpoint.** Library integration: the compute family
      kit's suite, `make test-compute-provisioning`. Then `make test`.
      End-to-end: none. Nothing calls the read until section 5, and no
      end-to-end scenario is owed.
      Owed by validation: `tests.yml`, job `test · test-compute-provisioning`.
      The kit suite passes, including the new `execution_hosts` tests.
      *Evidence:* `make test-compute-provisioning`, 530 passed; `make test`,
      exit 0.

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
      *Done;* neither subprocess call in the runner is given an `env`.
- [x] 2.2 Add a unit test that the packaged configuration
      (`DEFAULT_ANSIBLE_CONFIG`, read with `configparser`) states no `log_path`
      in any section. This is the lowest level that can prove the scenario "A
      playbook runs under the packaged configuration": without `log_path` or
      `ANSIBLE_LOG_PATH`, Ansible writes no log. The job's logs are already
      redacted, as `test_executor.py`'s redaction cases prove. (D2)
      *Done:* `test_the_packaged_configuration_names_no_log_file` (unit). That
      Ansible then writes no log is its documented behaviour, not observed.
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
      *Done (unit):* `test_a_connectivity_checks_output_is_returned_redacted`
      (both cases) and `test_an_error_running_the_check_is_returned_redacted`.
      The exception case's `PermissionError` text carries nothing
      credential-shaped, so the redaction call on that branch is untested;
      the branch's unreachable answer is. The environment case covers the
      check's subprocess; the playbook subprocess's missing `env` rests on
      reading the code, and the exported configuration is 5.3's. The test
      level of the stand-in subprocess is recorded in `design.md`.
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
      *Evidence:* `make test-compute-provisioning-ansible`, 170 passed, 4
      skipped (the real-Ansible codec cases, without `ansible-playbook`);
      `make test`, exit 0, though against the service's previously built
      wheel (section 4's correction).

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
      *Done,* with two refinements recorded in `design.md`, D4: the no-key
      cause has its own message and recovery, and the distribution declares
      `cryptography>=42.0` at runtime (`make lock` run; the locks of the
      distribution, the service and both domain adapters gained the edge).
- [x] 3.2 Have `write_inventory` pass the target's `host_id` to
      `decrypt_private_key`. Its existing partial-write cleanup stays as it is,
      and the job executor lets the error propagate: the job engine records it
      with its message and never retries it, as it does
      `RelayUnusableAtExecutionError`. (D4)
      *Done;* the executor is unchanged, and the engine records the error as
      `Internal error: <message>` without a retry (proved in 5.4).
- [x] 3.3 Have `probe_connectivity` catch `ProtectedKeyUnreadableError` and
      return `ConnectivityResult(host=<host_id>, reachable=False, detail=<its message>)`.
      Update its docstring. (D4)
      *Done;* only `write_inventory` sits inside the `try`.
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
      *Done (unit):* `test_a_protected_key_that_cannot_be_decrypted_is_named`
      over the three causes and a configured key that is not a Fernet key,
      asserting each whole message and that no ciphertext, PEM text or key
      appears; the extended runner test; `test_a_key_that_cannot_be_decrypted_fails_the_run_naming_the_host`;
      and `test_a_host_whose_key_cannot_be_decrypted_is_answered_unreachable`,
      which shows the ping is never called.
- [x] 3.5 **Verification checkpoint.** Unit: the Ansible distribution's suite,
      `make test-compute-provisioning-ansible`. Then `make test`.
      End-to-end: none. No lane registers an embedded host, and the mock runner
      never decrypts. None is owed: section 5 proves the running application's
      behaviour through the canonical client.
      Owed by validation: `tests.yml`, job `test · test-compute-provisioning-ansible`.
      The distribution's suite passes, including the typed-error, executor and
      probe tests.
      *Evidence:* `make lock`; `make test-compute-provisioning-ansible`, 177
      passed, 4 skipped; `make test`, exit 0; `make check-packaging`, exit 0.

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
      *Done:* keywords `execution_hosts` and `ssh_codec`;
      `collect_ssh_keys_from_hosts(hosts, ssh_codec)` returns a
      `HostKeyReport` (`ssh_keys`, `host_reasons`); imports at module level.
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
      *Done:* a refusal reads `host '<id>' cannot be executed against:
      <refusal>` unless the refusal already names the host. The plaintext is
      never bound to a name; that nothing is written rests on reading the code.
- [x] 4.3 Make these reasons count as a missing key file's do: once any
      composed Ansible executor is real. Mocked executors need no keys. The
      detail keeps its fields and schema version 1. *Corrected (27 F1):* it
      is published as schema version 2 (D5). Rewrite `SshKeyInfo`'s
      field descriptions:
      - for an embedded key, `exists` means it decrypts under the configured
        key;
      - the module and class docstrings name the hosts' stored connections as
        execution reads them.

      The detail carries no plaintext and no ciphertext. (D5)
      *Done:* host reasons follow the key-file reasons. The module docstrings
      of both `connection.py` modules and `decrypt_private_key`'s also name
      the in-memory readiness check.
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
      *Done (unit):* every listed case, plus a version-1 host whose protected
      key decrypts and a connection naming no key.
- [x] 4.5 **Verification checkpoint.** Unit: the Ansible distribution's suite,
      `make test-compute-provisioning-ansible`. Then `make test`.
      End-to-end: none in this section. The composition root is not yet wired
      to the new input; section 5 wires it and names the smoke that reads it.
      Owed by validation: `tests.yml`, job `test · test-compute-provisioning-ansible`.
      The distribution's suite passes, including the reworked readiness tests.
      *Evidence:* `make test-compute-provisioning-ansible`, 187 passed, 4
      skipped; `make dist`, then `make test`, exit 0 (644 unit, 579
      application integration in the service). After the version bumps
      (`design.md`): `make lock`, `make dist`, `make test`,
      `make check-packaging`, each exit 0. *Correction:* 5.1 and 5.2 landed in
      this section's commit, since the new signature broke the composition
      root, so `test · test-provisioning` is owed here too. A service run
      proves nothing about a changed internal package until `make dist`
      rebuilds `.dist` (`BUILD_AND_PACKAGING.md`); sections 1 and 2's `make
      test` runs predate the rebuild. End-to-end evidence is 5.5's.

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
      *Done in section 4's commit;* the codec is looked up once at
      composition, the hosts read on each status read.
- [x] 5.2 Have the integration harness's `conftest.py` call
      `_make_status_components` with the harness's own `connection_codecs`, so
      status is composed there as it is in production. (D5;
      `docs/development/TESTING.md`, "Integration Tests")
      *Done in section 4's commit;* the harness's codecs hold
      `TEST_CONNECTION_KEY`.
- [x] 5.3 Add a unit test of `app_runtime.apply_ansible_config` if none exists.
      It exports the profile's `ansible_cfg` verbatim when set and
      `DEFAULT_ANSIBLE_CONFIG` otherwise, and sets no `ANSIBLE_LOG_PATH`. (D2;
      the scenario "An operator configures a log file")
      *Done:* none existed. `apply_ansible_config` takes optional `config`
      and `environ` (the settings and `os.environ` when omitted), so
      `tests/unit/test_apply_ansible_config.py` injects both: an operator
      configuration is exported verbatim, an empty, blank, null or absent one
      exports the packaged configuration, and `ANSIBLE_CONFIG` is the only
      variable written.
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
      *Done (application integration):* five tests, one per case. The
      unreadable host is seeded directly, since the API protects every key
      under the configured key. The job test asserts the whole message in
      the job's error, `retry_count` 0, no `next_retry_at`, and no playbook
      started; the status test asserts the host's own reason rather than
      readiness alone, since the harness's playbook path does not exist. The
      redaction test's level is recorded in `design.md`.
- [x] 5.5 **Verification checkpoint.** Application integration: the
      provisioning service's suite, `make test-provisioning`, including the
      existing `test_system_api.py`, `test_hosts_api.py` and
      `test_vms_api.py`. Then `make test`.
      End-to-end: `provisioning_readonly` smoke —
      `test_status_reports_execution_and_the_ansible_component` and
      `test_connectivity_check_on_first_host_if_available` in
      `e2e-tests/tests/smoke/test_provisioning_smoke.py`, which would exercise
      the new readiness wiring and the probe on a deployed release as
      regression evidence. *Corrected (28 A1):* no validation part runs that
      smoke: the provisioning chart's smoke hook runs only under
      `make -C helm test` or `make -C helm test-module MODULE=provisioning`,
      and validation's Helm part runs the e2e-scenarios pod and the payments
      check alone. The readiness wiring's regression evidence is the
      pipeline's stage 00c (`Stage00c_ProvisioningHealth`,
      `e2e-tests/tests/e2e/roles/helpers/compute_deal_stages.py`), which
      asserts every status component ready, in `e2e_deal`,
      `e2e_deal_buyer_cli` and `e2e_bare_metal_mock_deal`. Under the lanes'
      mocked executors host reasons do not count, so it shows the wiring
      composes and reads ready, not what it reports for a host. No lane
      exercises the new failure behaviour; application integration proves it.
      Owed by validation: `tests.yml`, job `test · test-provisioning`. The
      service suite passes, including `test_unreadable_host_key_api.py`.
      *Evidence:* `make dist`, `make test`, exit 0; `make test-provisioning`,
      649 unit and 584 application integration passed; `make
      check-packaging`, exit 0; `make check-change`, every check passed.

*Round fixes (triage of review 27 and validation 28):*
- **27 F1:** the readiness detail is published as schema version 2 (D5);
  `arkhai-compute-provisioning-ansible` was already at 0.8.0.
- **27 F2:** the delta's "A protected key that cannot be decrypted is named,
  not hidden" covers ciphertext the configured key cannot read, and states
  what a stored protected value with no ciphertext does. No code change.
- **28 A1:** 4.5, 5.5 and 6.8 corrected: the `provisioning_readonly` smoke is
  not evidence, stage 00c is.

*Evidence:* `make dist`; `make test-compute-provisioning-ansible`, 187 passed,
4 skipped; `make test-provisioning`, 649 unit and 584 application integration
passed; `make test`, `make check-packaging`, `make check-comment-hygiene` and
`make check-change`, each passing.

*Pre-closeout (triage of review 35):* **35 F1:** the delta's redaction
requirement and scenario, and D2, name the three values a connectivity result
replaces, and why no domain secret reaches a probe's output. No code change.

## 6. Closeout

Per `openspec/README.md#plan-closeout-requirements`, in this order. Closeout
changes documentation only: a part needing a code edit returns the change to
implementation.

- [x] 6.1 **Comment hygiene — confirm.** Run `make check-comment-hygiene`, and
      read the comments and docstrings this change added or revised for any
      that narrate the review or migration that introduced them. These are:
      `hosts/service.py`'s module docstring and `execution_hosts`;
      `connection.py`'s typed error and `decrypt_private_key`; `probes.py`;
      `readiness.py`'s docstrings and field descriptions; `ansible.cfg`; and
      `container.py`'s `_make_status_components`. Anything to rewrite returns
      the change to implementation.
      *Confirmed:* `make check-comment-hygiene` passes. Every comment and
      docstring in the diff from `origin/dev`, including those in
      `hosts/connection.py`, `runner.py` and `app_runtime.py`, describes
      current behaviour and names no review, task or migration.
- [x] 6.2 **Import placement — confirm.** Check the imports this change added,
      in `readiness.py`, `probes.py`, `connection.py`, `container.py`, and the
      new tests, for any still local without a recorded reason. One that should
      move returns the change to implementation.
      *Confirmed:* every import the change added, in source and tests, is at
      module level; the diff adds no function-local import.
- [x] 6.3 **Documentation compliance.** Re-check D1–D8 against
      `openspec/README.md`'s placement rules, and the permanent documents
      against the code they describe:
      - "Connection secrets stay protected" and "Execution readiness is
        reported in system status" against `execution_hosts` and `readiness.py`;
      - the operator handbook's host-definitions section against the export and
        the import route.
      *Done:* normative behaviour (D2, D4, D5, D8) goes to
      `physical-provisioning/spec.md` through the deltas; operating procedure
      (D2's log, D4's recovery) to the operator handbook; goal state (D7) to
      `ROADMAP.md`; campaign state (D6) to the index; D1 and D3 need none.
      The two MODIFIED requirements match `execution_hosts` (internal, served
      by no route) and `readiness.py` (refusal through `inventory_target`,
      in-memory decryption, other kinds skipped). The handbook's export
      section matches `HostAuthority.host_definitions`. No other permanent
      document states the packaged log file or embedded keys reported present.
- [x] 6.4 **Narrative compression.** Compress completed-task notes to final
      behaviour, material validation evidence, deferred work (D3's revisit
      trigger stays in `design.md`), and permanent-documentation destinations,
      moving durable rationale into `design.md` first.
      *Done:* moved to `design.md` first: D4's two refinements (the no-key
      message, the runtime `cryptography` dependency), the stand-in-subprocess
      tests' level, and the version bumps. Removed: section handoffs and the
      fresh-context check narratives, and the stale-wheel narrative, which
      `BUILD_AND_PACKAGING.md` already states ("Run make dist first"). No
      work is deferred beyond D3's revisit trigger.
- [x] 6.5 **Roadmap currency (D7).** In `docs/development/ROADMAP.md`, "Goal 1 —
      Consolidate physical-resource authority in the provisioning service":
      - Remove the gap row "One SSH key reaches every host in an environment,
        so a host prepared by another party cannot be registered with its own
        credential".
      - Add to the goal's current state that a host may be registered with its
        own key material through the host API, decrypted only for the
        operation that uses it, and that a key that cannot be decrypted is
        named at dispatch, at the connectivity check, and in readiness.

      Name the edit in the design-promotion record.
      *Done:* the row is removed, and a current-state paragraph after the
      host-definitions paragraph says both, and that Ansible's output is kept
      only redacted by default.
- [x] 6.6 **Campaign index currency (D6).** In `openspec/changes/README.md`,
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
      *Done:* the row reads `in closeout` with its evidence; the graph line
      names this change as independent; the paragraph and the relay row's
      Notes are rewritten, and so is the campaign's introduction, which said
      registering a host with its own credential was remaining work. No other
      row's `Depends on` or status changed. `scripts/change-workflow check
      index` passes.
- [x] 6.7 **Packaging.** Run `make check-packaging` and resolve every failure it
      reports. A failure needing a code or lock change returns the change to
      implementation. Then run
      `make check-architecture-change CHANGE=contain-embedded-host-key-material`.
      No exception row is expected, since no new edge crosses a layer.
      *Done:* `make check-packaging`, exit 0 (locks, Python selection, layer,
      scope, dependency and kind rules all OK); `make
      check-architecture-change`, "owns no architecture row". The change
      touched no `.agents/`, `.claude/` or `.codex/` file, so
      `make check-agent-skills` is not owed.
- [x] 6.8 **End-to-end pipeline.** Record the passing run the latest validation
      names, its result, and the scenarios that exercise this change: the
      pipeline's stage 00c in `e2e_deal`, `e2e_deal_buyer_cli` and
      `e2e_bare_metal_mock_deal`, as regression evidence that the readiness
      wiring composes and reads ready under mocked executors. Record also
      that no lane scenario exercises an unreadable key, the log file, or
      connectivity redaction, which application integration proves, and that
      the `provisioning_readonly` smoke of section 5 is not evidence, since no
      validation part runs it (28 A1). If the pipeline cannot run, record
      an explicit blocker naming its cause and the change that owns it, with
      the validations it gates treated as unrun.
      *Done:* validation 40 (`reviews/40-validation.md`) passed at
      `c76f66488`, the merge of `origin/dev` after the pre-closeout triage,
      which is the commit closeout starts from: pipeline run 42264437201,
      success, lanes `e2e-vm`, `e2e-bare-metal` and `e2e-apicredits`; stage
      00c ran in `e2e_deal` and `e2e_deal_buyer_cli` (VM lane) and
      `e2e_bare_metal_mock_deal` (bare-metal lane), passing. No lane
      exercises an unreadable key, the log file or connectivity redaction,
      and the `provisioning_readonly` smoke is not evidence. CI: `tests.yml`
      run 42264444169, success; the owed jobs `test · test-compute-provisioning`
      (531 passed), `test · test-compute-provisioning-ansible` (191 passed)
      and `test · test-provisioning` (653 unit, 589 application integration)
      passed, every one of the 24 jobs passing, against `dev`'s baseline run
      42251889872 at `20aa47dfe`, also all passing. Local (`check-packaging`,
      `test`) and Helm parts passed too. Closeout changes no code, so these
      runs describe the code the closeout commit carries.
- [x] 6.9 **Promotion.** Write the permanent documents this change owes, and
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
      *Done:* the handbook's "Ansible configuration" section and "A host's
      protected key no longer decrypts" subsection are written; the recovery
      names `PUT /api/v1/hosts/{host_id}` and the INI import's `embedded`
      mode, not `POST /api/v1/hosts`, which registers a new host only. The
      handbook's version-2 bullet also says readiness names a version-1
      host. In the relay change: 2A.7 (left unchecked), the progress summary
      and its 2A.7 item, the promotion row, the sequencing paragraph, the
      design paragraph, and a correction note on its completed 11.5, which
      said Goal 1's gap table names this change. The design-promotion record
      is in `design.md`.
- [x] 6.10 **Documentation citations.** After promotion, run
      `make check-doc-citations CHANGE=contain-embedded-host-key-material` and
      resolve every match. Then run
      `openspec validate contain-embedded-host-key-material --strict`.
      *Done:* `make check-doc-citations`, every cited path resolves in the
      change's 4 documents; `make check-change`, every check passed,
      `openspec validate --strict` with the pinned validator among them.
- [x] 6.11 **Archival.** Last, once every other part is checked, run
      `openspec archive contain-embedded-host-key-material -y`. It merges the
      two ADDED and two MODIFIED requirements into
      `openspec/specs/physical-provisioning/spec.md`, with no `--skip-specs`,
      and moves the change under `openspec/changes/archive/`. Point the index
      row at the archived directory, and run `openspec validate --specs --strict`.
      *Done:* archived with the pinned validator (through `npx`, since `bunx`
      is not installed here), with no `--skip-specs`: the permanent spec did
      not yet carry the deltas. The diff of `physical-provisioning/spec.md`
      holds the two added requirements once each, the two modified ones as the
      deltas state them with their added scenarios, and nothing else. The
      index row links `archive/2026-11-06-contain-embedded-host-key-material/`;
      `make check-change` on the archived change passed, `openspec validate
      --specs --strict` among its checks.

*Closeout review 42's corrections, made after archival on the owner's
direction:* the permanent requirement "Execution readiness is reported in
system status" now states the Ansible detail's kind and schema version 2 and
their meanings (42 F1). With no `ssh_decryption_key` configured, the handbook
and the codec's message name both recoveries, configuring the original key or
configuring any key and submitting the host's private key again; the unit
test's expected text and the design's D4 refinement follow (42 F2). Evidence:
unit, `make test-compute-provisioning-ansible` (187 passed, 4 skipped);
`make check-packaging` passed; `make test` exit 0; `make check-comment-hygiene`
and `make check-change` passed. The fresh-context check of the diff found
nothing to fix; it offered the spec sentence's field meanings as MUST clauses,
declined since the spec states such definitions plainly elsewhere.

The design-promotion record is in `design.md`, "Design promotion record".
Closeout ran its parts in the order above.

## Validation evidence

| Suite | Baseline |
|---|---|
| `make test` unit, `provisioning/compute/service` | 522 passed |
| `make test` integration | 196 passed |
| `make test`, `domains/vms/provisioning/iac` | 52 passed |

The earlier plan measured these baselines on the delivered tree before any work
in this change. No suite here needs Ansible or a live host.
