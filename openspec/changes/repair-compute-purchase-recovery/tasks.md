# Tasks — repair compute purchase recovery

Replanned against the reviewed design after its second design review
(`reviews/02-design.md`) and that review's triage. No task had been completed before
the replanning, so none was preserved as done. The design gates in Section 1 record how
the design was settled.

Sections are ordered by real dependencies, lowest layer first: the shared Ansible kit
before the domain adapters that compose it, the fulfillment kit before the compute
lifecycle that calls it, and domain vocabulary before the storefront that publishes
it.

Paths under `provisioning/compute/ansible/` are the shared Ansible kit
(`compute_provisioning_ansible`), and paths under `provisioning/compute/service/` are
the compute provisioning service. Test levels are those of `docs/development/TESTING.md`:
unit, library integration, application integration (the running service through its
typed client), and system.

**Packaging, in every section.** Every section that changes a package does three
things:
- bumps the package's minor version;
- updates the exact pins its dependants hold;
- refreshes the locks with `make lock`, using uv at or above the repository minimum
  (`make check-uv-version`).

Its verification then runs `make check-packaging`, which includes
`make check-architecture`. A section that changes only tests changes no version.

**Fixtures are synthetic (D2).** Every test fixture uses development values:
- a reserved documentation address (`192.0.2.0/24`);
- a synthetic tenant account;
- a zeroed identifier;
- a placeholder key.

No output, identifier, address, or key from a real host or purchase enters a test.

**End-to-end evidence.** Validation runs the Helm checks and the pipeline on every
commit. Each section names the scenarios (pytest markers in `e2e-tests/`) that
exercise it, or says that none does. No section owes evidence from a CI workflow that
only a push produces.

## 1. Design

- [x] 1.1 **Decision gate.** Resolve the independent design reviews of `design.md`,
      the deltas, and this plan. Record each accepted finding in `design.md`, and
      amend these sections before Section 2 starts.
      - The first review's triage (`reviews/01-design.triage.md`) amended the
        design and asked for another round.
      - The second review (`reviews/02-design.md`) found no blocking issue. Its
        triage (`reviews/02-design.triage.md`) recorded `Advance`, and carried its
        corrections into `design.md` (D1, D4, D10), the deltas, and this plan.
- [x] 1.2 **Decision gate.** Confirm D7's ownership split with
      `gpu-optional-compute-shapes`:
      - Its proposal records, under "Dependencies and Related Changes", that this
        change delivers the schema and VM stated-shape slice and gates its planning.
      - Its index row names this change in `Depends on` as
        `` `repair-compute-purchase-recovery` (planning) ``.

      `make check-change-index` holds the column. It checks that each dependency
      the column names is a change the index lists and is not `archived`, with a
      phase from the legend's list. It passed when this plan was written. It reads
      no `Notes` text and no proposal, so the proposal's record was checked by
      reading it.

## 2. Read a printed fact in either form, for the job's action

Delivers D1's reader ("Block boundaries", "What the reader takes and ignores") in the
shared Ansible kit, for the delta requirement "A create succeeds only with readable
delivery evidence". Files:
- `provisioning/compute/ansible/src/compute_provisioning_ansible/runner.py`
- its `__init__` exports
- `provisioning/compute/ansible/tests/unit/test_runner.py`

- [x] 2.1 Add a reader that takes the output, the fact name, and the expected action:
      - It returns the fact printed in JSON `var:` form, when one is printed.
      - Otherwise it reads each `msg: |` or `msg: |-` literal block alone. A block
        is the indented lines after its key, up to the first non-blank line indented
        no deeper than the key. The reader parses the dedented block as one JSON
        document, and never reads past the block's end.
      - It ignores a block that is not JSON, a document that is not an object, a
        document with no `action`, and a document naming another action.
      - It returns the last document whose `action` equals the expected action. With
        none, it returns nothing.
      - It logs at debug level how many blocks it ignored and why, never their
        content.

      `extract_fact` stays for callers that pass no action, and reads the JSON form
      only.

      Done: `read_fact(stdout, fact_name, *, action)` in `runner.py`, exported from
      `compute_provisioning_ansible` and `compute_provisioning_ansible.runner`. A JSON
      `var:` fact is returned as `extract_fact` reads it, with no action check, since
      judging the fact is the codec's (D1). A block's key line is a whole line
      `msg: |` or `msg: |-` after spaces. Scanning resumes after a block's end, so no
      line belongs to two blocks. Each block is dedented and parsed with `json.loads`.
      The debug line names the fact, the action, found or absent, and counts per
      reason (`not_json`, `not_object`, `no_action`, `other_action`), and is logged
      only when a block was ignored. `extract_fact` is unchanged; its docstring now
      says it reads the JSON form only. No caller uses `read_fact` yet.
- [x] 2.2 Unit tests, on synthetic output in each form the shipped configuration and
      the JSON configuration print:
      - YAML `var:` plus `msg: |-` JSON;
      - JSON `var:`;
      - several `msg:` blocks for different actions, the expected one not last;
      - two blocks for the expected action, the last taken;
      - the play's human-readable summary block (`msg: |` with prose lines), alone,
        and followed by another task's JSON document, which is not adopted;
      - a malformed block followed by an unrelated task's JSON document, neither
        taken;
      - a document with no `action`;
      - no fact at all;
      - a debug log that carries no block content.

      Done (unit): thirteen tests, 19 cases, in `test_runner.py`, on pure strings
      with no collaborators. Each case listed above has a test. Further cases:
      - 2- and 4-space key indentation, under `|` and `|-`;
      - the JSON format's escaped `msg:` string, which is not a block;
      - a JSON list, string, or `null` document;
      - a block that keeps a blank line and ends at a sibling key;
      - the malformed block's neighbour, read on its own;
      - a block nested too deeply to parse, on which `json.loads` raises
        `RecursionError` rather than `ValueError`, is ignored as `not_json`.

      Each fixture's shape follows ansible-core 2.18's default callback under the
      packaged `ansible.cfg`, in both result formats. That output was printed once
      from a local playbook of `debug` tasks against `localhost` and kept out of the
      repository. Under the YAML format it indents results four spaces, and prints
      even a prose `msg:` with a trailing newline as `|-`. Values are development
      values: `192.0.2.10`, `tenant0000`, a zeroed identifier, and a placeholder key.

      Red, before the reader existed: a stub returning `extract_fact`'s answer, which
      is today's behaviour, gave 10 failed and 101 passed. The shipped YAML form read
      as `None`. This is the reader's behaviour on synthetic output, not a replay of
      the captured run. Green: 111 passed. The deep-nesting case was added after
      that run, with the `RecursionError` catch; the suite then passed 112, listed
      under 2.3.

      Corrections after the section's precommit compliance check. The suite now has
      fourteen tests and 21 cases.
      - **The JSON format's escaped `msg:`.** The note above credited this case to
        a test where the `var:` fact is present. There the reader returns before it
        reads any block. A new case gives the escaped `msg:` alone, with no `var:`
        fact, and reads no fact. It passed on its first run, so no defect was found.
      - **The summary followed by another task's JSON.** That test is now
        `test_a_later_document_outside_a_msg_block_is_not_adopted`. It shows that a
        later document under another key, or bare in the output, is not adopted, as
        a forward scan from the summary's `msg:` would adopt it. It does not by
        itself show where a block ends. The malformed-block and sibling-key cases
        show that.
      - **The fixtures' source.** The earlier capture printed plain `debug` tasks,
        not the roles' own pattern, and the summary fixture used `|` while the
        capture printed `|-`. The summary now uses `|-`, and `|` remains a
        parametrized variant, as it does for JSON blocks. Both are valid forms.
        Neither is claimed as the output of a deployed run.
      - **The roles' own pattern.** A second local experiment, kept out of the
        repository, repeated the roles' printing pattern:
        - `set_fact` of the mapping, then `set_fact` of its `to_nice_json`;
        - `debug: var:` of the mapping;
        - `debug: msg: "{{ ..._json }}"`;
        - the play's prose summary.

        It ran on `localhost` with synthetic values, under the packaged
        `ansible.cfg`, on ansible-core 2.17.14, 2.18.19, and 2.19.14. The last is
        what the service image's `ansible-core>=2.17,<2.20` resolves to today. Each
        version printed both facts' `msg:` as a `|-` literal block, and the summary
        as `|-` too. `read_fact` read the grant fact and a nested VM create fact
        from every output, and `extract_fact` read `None` under the YAML format.
        This is a local playbook's output, not the deployed roles on a host. Their
        structured grant and VM results remain the live lanes' evidence (14.8).
- [x] 2.3 Verification:
      - `make -C provisioning/compute/ansible test` (unit);
      - `make check-packaging`.

      End-to-end: none directly. Sections 4 and 5 carry the reader through the mock
      lanes.

      Done. The final evidence below was run on the final tree, after the wheelhouse
      was rebuilt with the last source change. It supersedes the earlier passes
      recorded under 2.2.
      - **The wheel.** The 0.5.0 wheel's eleven package files equal their source byte
        for byte.
      - `make -C provisioning/compute/ansible test`: 112 passed (unit).
      - `make check-packaging`: passed, the architecture rules included.
      - `make test`, which every section runs (`change-implement`, step 5) beyond
        the focused list above: passed, exit 0. Four skips stand in the core and VM
        storefronts' suites, outside this section's files. An earlier full run,
        against a wheel built before the last source change, was interrupted inside
        the VM storefront's suite with no exit recorded. It is not counted as
        evidence.
      - `make check-change CHANGE=repair-compute-purchase-recovery`, which includes
        comment hygiene: passed.

      What this proves is unit-level: the reader's behaviour on synthetic output.
      No application, pipeline, or live run exercises it, because no caller uses
      it yet.

      **Packaging.** `arkhai-compute-provisioning-ansible` goes from 0.4.1 to 0.5.0.
      No exact (`==`) pin of it exists in the tree. Its dependants — the VM and
      bare-metal provisioning adapters and the provisioning service — keep their
      `>=0.4.0` floors, since none imports `read_fact` yet. `make lock` refreshed
      the four locks that resolve it; only the version changed.

      **End-to-end, confirmed.** No caller of `read_fact` exists outside the kit, so
      no pipeline scenario exercises this section. Owed by validation: none.

      **Handoff to Sections 4 and 5.**
      - Each codec calls `read_fact(output.stdout, fact_name, action=...)`, with the
        action from its own mapping (D1's table), and raises its adapter's floor on
        this kit to `>=0.5.0` with its own minor bump.
      - A JSON `var:` fact comes back without an action check, so the codec's
        linkage check is what refuses another action's fact in that form.
      - `extract_vm_fact`'s forward scan is what Section 5 replaces.
      - A fact's templated port is a string before ansible-core 2.19 and may be an
        integer on 2.19. In the local experiment, a `default(22)` printed `"22"`
        and `22` respectively. The grant fact's `port` is detail only (D3), so a
        codec should not compare it as text.

      Corrections after the section's precommit compliance check. The check found
      evidence-precision gaps and no parser defect; see 2.2's corrections.
      - **What changed.** `read_fact`'s docstring now gives the reason the YAML
        form is not read. The tests and the notes changed as 2.2 says. Nothing else
        changed. With docstrings stripped, `runner.py`'s syntax tree equals the
        source that the full `make test` above ran on. So that pass still covers
        the reader's runtime logic, and the full suite was not run again for these
        edits.
      - **Evidence for the edits** (focused):
        - `make -C provisioning/compute/ansible test`: 114 passed (unit).
        - `make dist` and `make lock`: the locks changed only in version.
        - The rebuilt wheel's eleven files equal their source.
        - `make check-packaging`, `make check-change`, `make check-comment-hygiene`,
          and `make check-tasks`: all passed.

## 3. A tenant-facing port beside the tenant-facing address

Delivers D3's connection, inventory, and INI changes, for the delta requirement "The
tenant-facing host address falls back to the connection address". Files:
- `provisioning/compute/ansible/src/compute_provisioning_ansible/connection.py`
- `runner.py` (`InventoryTarget`, `inventory_target`, and inventory rendering)
- `inventory.py` (INI `public_port=`)
- their unit tests, including `provisioning/compute/ansible/tests/unit/test_inventory.py`
- `provisioning/compute/service/tests/integration/test_hosts_api.py`

- [x] 3.1 `SshConnection` gains an optional `public_port`, validated as 1–65535 and
      additive to version 1. `InventoryTarget` carries it. Rendering emits
      `public_port=` when set, as it emits `public_host=`. The INI format reads
      `public_port=`, and refuses a malformed port as it refuses a malformed
      `ansible_port`. Each connection field's comment states its fallback.

      Done, in `connection.py`, `runner.py`, and `inventory.py`.
      - **The stored form.** An envelope that states no `public_port` is stored
        without the key: `SshConnection.public_fields()` drops a null
        `public_port`, and `build`, `validate`, and `ssh_connection()` all store
        through it. A `model_dump()` would write `public_port: null`, which a reader
        that does not know the field refuses as surely as a port (see 3.3). So a host
        stating no route is stored exactly as before, and only a host that states a
        port needs D3's rollback step.
      - `public_host` is still stored as `null` when absent, as before.
      - **Rendering.** `InventoryTarget.public_port` is the last field, with default
        `None`. A line gets `public_port=` after `public_host=`, only when set. The
        rendering comment says an unstated value is the connection's own. No
        playbook reads `public_port` yet; the bare-metal codec uses it in Section 4.
      - **INI.** `public_port=` is parsed with the same rule as `ansible_port=`, by
        one `_port` helper: an entry whose value is not an integer from 1 to 65535
        is skipped with a warning naming the variable, and the other entries are
        imported. The `ansible_port` warning keeps its wording.
- [x] 3.2 Unit tests:
      - a connection with and without `public_port`;
      - a malformed port refused;
      - rendering;
      - an INI round trip, including a malformed entry rejected while the others
        are imported.

      Done (unit). At the section's start the kit's suite passed 114. With the new
      tests and no source change, the red run had 10 failed and 115 passed. Those
      115 are the 114 and the round-trip case below, which passes vacuously then.
      The ten failed on the missing field. Green: 125 passed.
      - **Connection** (`test_ssh_connection.py`):
        - no `public_port`, stored exactly as before, through `build`,
          `validate` of a stored envelope, and `ssh_connection()`;
        - a null `public_port`, stored as absent;
        - a port beside `public_host`, and a port without one;
        - 0, 65536, -1, and `22x`, each refused by the codec and by
          `ssh_connection()`.
      - **Rendering** (`test_runner.py`): `public_host=` and `public_port=`
        render when set, and neither renders when not.
      - **INI** (`test_inventory.py`): a port is read; the entries `ssh`, `0`, and
        `70000` are skipped while the others are imported. The entries use RFC
        5737 documentation addresses.
      - **Round trip:** parsed hosts are stored through the codec, rendered by
        the real runner, and parsed again, and read back equal. This case passed
        in the red run too, since no port was parsed on either side then. It
        fails now only if rendering or parsing drops the port.

      New routed inputs use RFC 5737 documentation addresses. The tests that
      extend an existing sample keep its address. All are development fixture
      values that must never be used on a public network. Key paths are
      placeholders.
- [x] 3.3 Application integration: register a host through the typed host client
      with `public_host` and `public_port`. Read it back, and see both in the
      rendered execution inventory. A host without them reads unchanged.

      Done (application integration), as `TestTenantFacingRoute` in
      `test_hosts_api.py`, through the typed host and VM clients.
      - **The routed host.** It is registered at `ssh_host` 198.51.100.1 over
        `ssh_port` 6000, with `public_host` 192.0.2.10 and `public_port` 22. The
        test reads it back, and checks the stored `connection_public` row. A VM
        create job is then run on it.
        - Job execution reaches the real runner's inventory rendering: the
          fixture's runner mock hands `write_inventory` to a real `AnsibleRunner`,
          so the job's actual inventory text is read.
        - The mock still replaces playbook execution, so no command or subprocess
          is built.
        - The job's inventory line is
          `ansible_host=198.51.100.1  public_host=192.0.2.10  public_port=22  ansible_port=6000`.
      - **The plain host.** Its stored public mapping equals the pre-change form,
        with no `public_port` key, and its rendered line carries neither field.
      - **Red.** The service environment held the kit wheel built in Section 2,
        without the field. There, the routed case failed with a `TypeError`:
        `ssh_connection()` took no `public_port`. The plain case passed.
        - This was the older installed kit's client-side helper refusing the
          argument before any request was sent. It is not a proof that the
          server or API refuses the field.
        - The green run does exercise the typed client, the API, storage, and
          the job's real inventory rendering.
        - The service's floor rests on its own production edges, given under
          3.4, not on this red.
      - **The rollback rule.** Its reproducible basis is in the repository:
        - The unit test `test_a_connection_stating_no_public_port_is_stored_as_before`
          pins a connection stating no route to the pre-change stored mapping.
          This module's plain-host case pins the stored row.
        - The older reader's `SshConnection` is `extra="forbid"`, as the section's
          base revision of `connection.py` shows. So it refuses any key it does
          not know, a null `public_port` as surely as a port.
        - A host stating no route therefore reads under the older reader, and only
          one stating a port needs D3's rollback step.

        A private experiment, kept out of the repository and not an automated
        test, corroborated this against the 0.4.1 wheel the wheelhouse held,
        built from the base revision. Its
        `SshConnectionCodec.validate` read the envelopes the new codec stores:
        - no route, and `public_host` alone: accepted;
        - a stated `public_port`, and an explicit `public_port: null`: refused.
- [x] 3.4 Verification:
      - `make -C provisioning/compute/ansible test` (unit);
      - `make -C provisioning/compute/service test` (application integration);
      - `make check-packaging`.

      End-to-end: no pipeline scenario registers a tenant-facing route. The live
      bare-metal lane is the system evidence.

      Named checks passed on the final source:
      - `make -C provisioning/compute/ansible test`: 125 passed (unit);
      - `make -C provisioning/compute/service test`: 669 unit and 542 application
        integration passed;
      - `make check-packaging`: passed.

      Consumers of the changed kit also passed:
      - `make -C domains/bare_metal/provisioning/adapter test`: 57 passed (unit);
      - `make -C domains/vms/provisioning/adapter test`: 37 passed (unit).

      Left unchecked at first: the full `make test` and the section's
      fresh-context compliance check were still owed.

      **Final evidence**, after the tests', comments', and notes' corrections. No
      production code changed in that round.
      - `make -C provisioning/compute/ansible test`: 125 passed (unit).
      - `tests/integration/test_hosts_api.py`: 44 passed, both
        `TestTenantFacingRoute` cases included (application integration).
      - `make check-packaging`: passed.
      - **The wheels.** The kit's 0.5.0 wheel (11 files) and the service's 0.19.0
        wheel (45 files) equal their source.
      - `make test` on those final artifacts: passed, exit 0. The four skips are
        the same ones in the core and VM storefronts as in Section 2's run.
      - `make check-change` and `make check-comment-hygiene`: passed.

      This task is checked on that evidence. The section's fresh-context
      compliance check is still owed before the section commits.

      **Corrections after the section's fresh-context compliance check.** The
      check found no blocking defect.
      - **The INI and rendering rules for `public_port` had no normative home.**
        The `physical-provisioning` delta now modifies "Host registry records the
        connection port". It keeps every existing `ansible_port` paragraph and
        scenario, and adds:
        - `public_port` preserved from the INI format;
        - a malformed or out-of-range value rejecting its entry, with a warning,
          while the others are imported;
        - rendering when stated and omission when not;
        - a record stating none stored with no field.

        `design.md`'s D3 promotion row names this requirement beside the
        fallback requirement. Both reach `openspec/specs/` by the archive.
      - **`test_hosts_api.py`** declared the rendered format outside its scope,
        and named a function that does not exist. Its docstring now names
        `AnsibleRunner.write_inventory` and allows one representative case. The
        two route cases read the rendered line's variables by name, with `shlex`,
        instead of its exact layout, which stays the runner's unit tests'.
      - **The rollback rule's basis** is restated in 3.3: the in-repository
        tests and the older reader's `extra="forbid"`, with the private
        experiment as corroboration.
      - **The INI port's `int()` leniency** (`+22`, `2_2`) was left as it is.
        `ansible_port` has the same rule, and a non-numeric or out-of-range
        value still rejects its entry.

      None of these edits touches production code, a dependency, or a lock; see
      the evidence below. The full `make test` above ran on that unchanged
      runtime. The edited tests and documents were checked afterwards with
      focused runs:
      - the `TestTenantFacingRoute` cases in `test_hosts_api.py`: passed
        (application integration);
      - `make check-packaging`, `make check-change` (strict OpenSpec validation
        and citations included), `make check-comment-hygiene`, and
        `make check-tasks`: passed;
      - the 0.5.0 kit and 0.19.0 service wheels equal their source.

      **Packaging.**
      - **The kit** stays at 0.5.0. This change already bumped it once, and these
        additions need no larger bump (`docs/development/RELEASING.md`,
        "Versioning policy").
      - **The provisioning service** runs the kit's code wherever a host route is
        stored or used. A 0.4 kit's codec refuses `public_port`, and its renderer
        emits none, so the service's floor rises to `>=0.5.0`. It takes this
        change's one bump, from 0.18.0 to 0.19.0. The edges:
        - `container.py` composes the kit's `SshConnectionCodec` into the host
          authority, which builds and validates every stored connection, on the
          host API and on import;
        - `app_runtime.py` seeds hosts with the kit's `parse_inventory_ini`;
        - jobs run through the kit's `AnsibleJobExecutor`, which renders each
          job's inventory with `inventory_target` and `write_inventory`.
      - **The adapters** keep `>=0.4.0`. Neither needs the new runtime behaviour
        in this section. Section 4 raises the bare-metal adapter's floor when its
        codec reads `public_port`.
      - **Locks.** `make lock` changed only the service's lock, for its version
        and floor. The 0.5.0 wheel's files equal their source.

      **End-to-end, confirmed.** No scenario in `e2e-tests/` registers
      `public_host` or `public_port`, so the pipeline does not exercise this
      section. The live bare-metal lane remains the system evidence. Owed by
      validation: none.

      **Handoff to Section 4.** The endpoint reads `InventoryTarget.public_host or
      ssh_host` and `public_port or ssh_port`. The bare-metal codec already
      receives the `InventoryTarget`.

## 4. Bare-metal grants yield evidence linked to their job, on the buyer's route

Delivers D1's bare-metal linkage, D2's shipped-form mock, and D3's endpoint, for the
delta requirements "A create succeeds only with readable delivery evidence" and "The
tenant-facing host address falls back to the connection address". Files:
- `domains/bare_metal/provisioning/adapter/src/bare_metal_provisioning_adapter/codec.py`
- `domains/bare_metal/provisioning/adapter/src/bare_metal_provisioning_adapter/services/mock_output.py`
- `domains/bare_metal/provisioning/adapter/tests/test_bare_metal_codec.py`
- `domains/bare_metal/provisioning/adapter/tests/test_bare_metal_mock_output.py`
- `provisioning/compute/service/tests/integration/test_bare_metal_mock_profile.py`

- [x] 4.1 The codec reads its fact through Section 2's reader, with the job's action.
      A grant yields evidence only when its fact names:
      - the job's action and host;
      - the parameters' tenant account;
      - the parameters' physical machine, when they name one;
      - status `success`.

      Otherwise the result carries no evidence, and a detail naming the mismatch.
      - The evidence endpoint is the execution host's `public_host`, else
        `ssh_host`, and its `public_port`, else `ssh_port`, with the confirmed tenant
        account.
      - The fact's own host and port are detail only.
      - A reclaim's fact is checked the same way.

      Done, in `codec.py`.
      - **Reading.** `interpret` reads the fact with
        `read_fact(stdout, BARE_METAL_RESULT_FACTS[action], action=run.action)`.
      - **Linkage.** `fact_mismatch` compares the fact with the job:
        - `action` with the run's action;
        - `host_id` with the execution host's `InventoryTarget.host_id`, which
          the role echoes as `executor_target`;
        - `ssh_user` with the parameters' tenant account;
        - `physical_host_id` with the parameters' machine, only when they name
          one;
        - `status` with `success`.
      - **Reporting a mismatch.** Every mismatch is named in one string. A job
        naming no tenant account is itself a mismatch. Fulfillment always derives
        one (`materialization_to_access_grant`), and the role refuses a grant
        without one.
      - **The grant's result.** On any mismatch it carries `evidence: null` and
        the fact's named fields as detail, plus `mismatch`. Otherwise
        `grant_evidence` builds the endpoint from the `InventoryTarget`
        (`public_host or ssh_host`, `public_port or ssh_port`) with the confirmed
        account, and the fact's `timestamp` as `ready_at`. An unusable time
        still yields no evidence, as before. The fact's `host` and `port` stay
        detail.
      - **The reclaim's result.** When linked, it is its fact, unchanged in
        shape. When not, its value is only `{"mismatch": ...}`, so an unlinked
        document is never recorded as the reclaim's result.
      - **Why a reclaim mismatch fails nothing.** Nothing reads a reclaim's
        result value, and a teardown's success is its job's status, so this
        refuses no teardown. That choice is this section's, as D1 says "checked
        the same way" without naming the reclaim's mismatch shape; it is flagged
        for review.
      - `grant_evidence` now takes the host and the confirmed account, and
        `fact_mismatch` is exported. Nothing outside the adapter used either.

      Correction after the section's fresh-context compliance check: the reclaim's
      result shape is no longer only this section's choice. D1 now states it in
      `design.md`:
      - a linked fact is the result;
      - a mismatched fact is replaced by `{"mismatch": ...}`;
      - no fact is no result.

      It also states that the mismatch is diagnostic only, with the reclaim job's
      status still deciding the teardown. The `physical-provisioning` delta adds
      "A bare-metal reclaim's printed fact is a diagnostic". The code is
      unchanged.
- [x] 4.2 The mock output prints the form the shipped configuration prints, a YAML
      `var:` block and the `msg: |-` JSON document, rendered for the job as it is
      today.

      Done, in `mock_output.py`.
      - **The form.** `shipped_output(host_id, fact_name, fact)` prints the
        `debug: var:` fact as YAML under an unquoted key, its values
        single-quoted, then the `msg: |-` `to_nice_json` copy at the 4-space
        indentation ansible-core 2.17 to 2.19 print (Section 2). The YAML part is
        display only; the reader reads the JSON block.
      - **The values.** `bare_metal_mock_output` renders them for the job, as
        before. A grant still prints the provisioner's route, the host's
        `ssh_host` and `ssh_port`, as the role prints `ansible_host` and
        `ansible_port`.
      - **A job naming no tenant.** The default still names `mocktenant` for
        one. That fact matches no account the job names, so the grant yields no
        evidence, as the role, which refuses such a grant, would.

      Correction after the section's fresh-context compliance check: the sentence
      above overstates the mock's fidelity.
      - **The role** fails such a grant's job: it refuses a grant naming no
        tenant account.
      - **The mock** succeeds the job, and the codec yields no evidence.
      - **The outcome is the same:** the fulfillment fails either way.
      - **The route differs**: a failed job versus a succeeded job without
        evidence. This is a known limitation of the mock and is left as it is.
      - A fulfillment always derives a tenant account, so a real grant job never
        names none.
- [x] 4.3 Unit tests:
      - a grant from shipped-form output;
      - each mismatch: action, host, tenant, machine, and status;
      - another action's document only;
      - the endpoint from a host with and without a tenant-facing route;
      - a reclaim in both forms.

      Existing JSON-form cases stay.

      Done (unit). At the section's start the adapter suite passed 57. With the
      rewritten and new tests and no source change, the red run had 22 failed and
      55 passed. Green: 77 passed.
      - **The shipped-form cases** failed at red because the previous codec read
        nothing from that form. That is the purchase's regression at the codec,
        on synthetic output.
      - **`test_bare_metal_codec.py`:**
        - a grant in the shipped form and in the JSON form, each with its
          endpoint on the host's tenant-facing address;
        - the endpoint falling back field by field: both stated, the port
          alone, neither;
        - each mismatch (action, host, tenant, machine, status), in the JSON
          form, since the reader returns that form whatever action it names;
        - all mismatches named together;
        - no machine compared when the job names none;
        - a job naming no tenant account;
        - another action's document alone, which is no fact;
        - the existing case of a fact that cannot say how to connect;
        - an unusable time;
        - a reclaim in both forms;
        - a reclaim mismatch, on host, tenant, and status.

        Correction after the section's fresh-context compliance check: "the
        existing case of a fact that cannot say how to connect" overstates that
        test. Its fact names no host, tenant, or status, so the mismatch is found
        before any endpoint is built. It shows that a mismatched fact yields no
        evidence and that unnamed fields are not kept. It is now named
        `test_a_grant_whose_fact_does_not_name_its_job_reports_no_evidence_and_drops_unvetted_fields`,
        with its body unchanged. The fact that cannot say when access became
        ready is the separate unusable-time case.
      - **`test_bare_metal_mock_output.py`:**
        - the default output in the shipped form for both actions, read by
          `read_fact` and not by `extract_fact`;
        - a grant's endpoint on the host's tenant route;
        - a job naming no tenant, failing closed.
      - **One test outside the plan's file list** pinned the old endpoint:
        `test_bare_metal_fulfillment_plan.py`, the family provider with the mock.
        It now expects the tenant-facing address `203.0.113.5` with the
        connection port. It also shows that a fulfillment's derived tenant
        account passes linkage.
      - **Fixtures.** New fixtures extend `tests/execution.py`'s sample host,
        whose addresses stay as they were, with `shipped_output`, `json_output`,
        and `host_with`. New routes use RFC 5737 addresses. All are development
        values that must never be used on a public network.
- [x] 4.4 Application integration, through the provisioning service's typed client
      under the mock profile:
      - A grant whose mock output is the shipped form reaches an `active`
        fulfillment, and its result's endpoint is the host's tenant-facing route.
      - A grant whose output names another tenant leaves the fulfillment `failed`,
        with no evidence.

      Done (application integration), in `test_bare_metal_mock_profile.py`,
      through the typed clients under the mock profile.
      - **`test_a_shipped_form_grant_becomes_active_on_the_hosts_tenant_route`.**
        The host is registered with `public_host` 198.51.100.20 and
        `public_port` 22. Begin and one convergence step make the fulfillment
        `active`. Its delivery's endpoint is the tenant route and the job's
        confirmed account. The fact's host and port are the connection's, in
        detail.
      - **`test_a_grant_naming_another_tenant_leaves_the_fulfillment_failed`.** A
        bare-metal rule supplies shipped-form output naming another tenant. The
        job succeeds with `evidence: null` and a `ssh_user` mismatch, and
        convergence fails the fulfillment for lack of delivery evidence.
      - **The shared helper.** `bare_metal_deal.bare_metal_capacity` takes an
        optional route, and its other callers are unchanged.
      - **No integration red.** The service environment's previous adapter lacks
        `shipped_output`, so these cases could fail there only at import, which
        is not behavioural evidence. The behavioural red is the unit one, 4.3.
- [x] 4.5 Verification:
      - `make -C domains/bare_metal/provisioning/adapter test` (unit);
      - `make -C provisioning/compute/service test` (application integration);
      - `make check-packaging`.

      End-to-end:
      - `e2e_bare_metal_mock_deal` and `e2e_bare_metal_payment_deal` (the
        bare-metal lane) arm no rule's stdout, so every grant and reclaim there
        reads the shipped-form default through the real read path.
      - The live bare-metal lane is the system evidence of a real grant.

      Named checks passed on the final source:
      - `make -C domains/bare_metal/provisioning/adapter test`: 77 passed (unit);
      - `make -C provisioning/compute/service test`: 669 unit and 544 application
        integration passed;
      - `make check-packaging`: passed.

      **End-to-end, confirmed.** No bare-metal scenario in `e2e-tests/` supplies
      a rule's `result_stdout`, so `e2e_bare_metal_mock_deal` and
      `e2e_bare_metal_payment_deal` read the shipped-form default. Neither
      registers a tenant-facing route. The payment lane asserts that the
      delivered host is the registered connection address, which still holds
      through the fallback. Owed by validation: none.

      **Packaging.**
      - `arkhai-bare-metal-provisioning-adapter` goes from 0.10.0 to 0.11.0, and
        its floor on the Ansible kit rises to `>=0.5.0`: its codec now needs
        `read_fact` and `public_port`.
      - The provisioning service's two floors on the adapter, its `adapters`
        extra and its dev group, rise to `>=0.11.0`, since it composes this
        adapter's codec and mock. The service is not bumped again: it is already
        at 0.19.0 for this change.
      - `make lock` changed only those versions and floors.

      **The full `make test`, and a test fixture it needed.**
      - **The first full run failed in one test**, outside this section's
        packages:
        `domains/apicredits/storefront/tests/unit/test_startup_seed_quota.py::test_the_seed_waits_while_the_credits_service_does_not_answer_its_availability_read`.
        That test asserts that nothing logged an error. It caught asyncio's
        "Task was destroyed but it is pending!" for a
        `SettlementJobCoordinator.run_once` task that an earlier test had left
        unfinished.
      - **The same test failed again** in one of two reruns of that project's
        suite. A further full run was stopped on purpose, and none of these
        counts as a pass.
      - **The producer.** It is a test in the same project's
        `test_settlement_fulfillment.py`. The settlement coordinator's task
        persists its outcome and then wakes servicing in a thread.
      - **The race.** The tests waited only for the outcome to be stored, so a
        test could end while its coordinator task was still waking servicing.
        pytest-asyncio closes a test's event loop without cancelling its tasks,
        so such a task could never finish. A later garbage collection then
        destroyed it, inside whichever test was running.
      - **The fix**, test-only, in `test_settlement_fulfillment.py`:
        - The composition helper's injected `persist` registers a done
          callback on the coordinator's own task, `asyncio.current_task()`
          there, before it persists.
        - The three tests that start a background settlement wait for that
          task to finish, with a timeout, and take its `result()`, so a failure
          or cancellation fails the test. They also assert that it fulfilled.
        - The two tests that start no background work are unchanged. No
          production code, dependency, or lock changed.
      - **Evidence** (unit): a two-test reproduction, the producer and then
        the seed test, with a real garbage collection forced when each test
        starts:
        - before the fix, red in about one run in six, each time with exactly
          that record;
        - after it, 0 red in 30 runs, with no task left pending on a closed
          loop;
        - the module and the project's suite then passed.
      - The full `make test` on the fixed source then passed, exit 0.

      **Still owed:** this section's fresh-context compliance check, before it
      commits.

      Corrections after the section's fresh-context compliance check, which found
      no blocking defect:
      - **The two-test reproduction's level.** It drives the coordinator and the
        settlement runtime directly against a real SQLite database, with no
        application or HTTP. So it is library integration, though its tests sit
        in the project's `unit/` folder. The module's 19 and the suite's 241
        counts mix unit and integration levels.
      - **The fixture renderer.** `tests/execution.py` keeps a shipped-form
        renderer of its own, independent of the adapter's production one. Its
        docstring now says why.
      - **The task notes** under 4.1, 4.2, and 4.3 carry the corrections for
        the reclaim's result, the mock's fidelity, and one test's name.
      - **No runtime change.** Only `design.md`, the `physical-provisioning`
        delta, this file, and two adapter test files changed: a renamed test and
        two docstrings. The full `make test` above therefore stands for the same
        runtime and test bodies, and these edits were checked by focused runs.

## 5. VM reads facts through the shared reader, linked to its guest

Delivers D1 and D2 for VM ("The VM pipeline scenarios use that default"), for the
delta requirement "A create succeeds only with readable delivery evidence". Files:
- `domains/vms/provisioning/adapter/src/vm_provisioning_adapter/codec.py`
- `domains/vms/provisioning/adapter/src/vm_provisioning_adapter/services/mock_output.py`
- a new `domains/vms/provisioning/adapter/tests/unit/test_vm_mock_output.py`
- the VM codec tests
- `e2e-tests/tests/e2e/roles/scenarios/vms/compute_deal_driver.py`, used by
  `test_full_deal.py`
- `e2e-tests/tests/e2e/roles/scenarios/vms/test_full_deal_buyer_cli.py`
- `e2e-tests/tests/e2e/roles/scenarios/vms/test_listing_shapes.py`
- `e2e-tests/tests/e2e/roles/scenarios/vms/test_buy_oneshot_buyer_cli.py`
- `e2e-tests/tests/e2e/roles/scenarios/vms/test_non_erc20_settlement.py`

The VM codec tests are in
`provisioning/compute/service/tests/unit/services/test_vm_codec.py`. They stay there
until `resolve-compute-family-findings` moves them to
`domains/vms/provisioning/adapter/tests/unit/`. Add the cases wherever the file is when
this section starts, and record in this section's notes where they went.

- [ ] 5.1 Replace `extract_vm_fact`'s private `msg:` fallback with Section 2's
      reader. The codec supplies the expected action from its own mapping, beside
      `VM_RESULT_FACTS`: the job's `vm_action`, which is `create` for a create and
      `vm_remove` for a remove, as each VM role prints it. The shared reader holds no
      VM knowledge. Behaviour on JSON-form output is unchanged.
- [ ] 5.2 A create's fact yields evidence only when:
      - its `action` is `create`;
      - its `vm_name` is the job's `vm_target`;
      - its `status` is `success`.

      The tenant account and forwarded port are read from that fact
      (`tenant_user`, `external_ssh_port`) or its `frp` block, no longer by
      searching the whole output. The fact's `host` is not compared. Otherwise the
      result carries no evidence, and a detail naming the mismatch.
- [ ] 5.3 `vm_mock_output` renders the shipped form for the job, from the job's
      stored parameters, as bare metal's does:
      - **A create.** The provided-key create fact, with:
        - `vm_name` set to the job's `vm_target`;
        - `tenant_user` derived from that name as the role derives it, by removing
          every non-alphanumeric character and lower-casing;
        - `status` `success` and a `timestamp` of the run;
        - a forwarded `external_ssh_port`, and no relay.
      - **A remove.** `vm_remove_data` naming the job's guest.

      The fixed `mock-vm` create, whose status is `running`, is removed.
- [ ] 5.4 Drop `result_stdout` from the create rule in each of the five scenario
      modules. Each rule keeps its `rule_id`, `match`, and `pause_before_result`, so
      every create there gets the per-job default:
      - remove `compute_deal_driver.py`'s `_CREATE_RESULT_STDOUT`, and correct the
        comments that describe the fixed fact;
      - before changing any assertion, re-run
        `rg -n "vmuser|e2e-test-vm|e2e-shapes-vm|e2e-buy-vm" e2e-tests/` and adjust
        any assertion that pins a fixed tenant user or guest name. When this plan
        was written, nothing asserted on them.

      None of the five rules is a deliberate invalid-output case. A test that needs
      invalid create output stays at the codec's or the provider's level (5.5,
      Section 4.4).
- [ ] 5.5 Unit tests:
      - each VM action from shipped-form output;
      - another action's `msg:` document no longer taken, including a `vm_remove`
        run whose output also carries a create document;
      - a create fact naming another guest yields no evidence, and so does one
        reporting another status;
      - a create fact whose `host` differs from the registry's address still yields
        evidence at the registry's address;
      - the mock's create output for a job yields evidence through the codec, with
        `tenant_user` derived from the job's `vm_target`, and its remove output
        names the job's guest;
      - existing cases kept.
- [ ] 5.6 Verification:
      - `make -C domains/vms/provisioning/adapter test` (unit);
      - `make -C provisioning/compute/service test` (unit and application
        integration, including the VM codec tests and the service's mock-profile
        cases that use `vm_mock_output`);
      - `make -C e2e-tests test-unit` (the scenario helpers still import and pass);
      - `make check-packaging`.

      End-to-end: once this section lands, five VM-lane scenarios read every create
      through the shipped-form default and the `msg:` path:
      - `e2e_deal`, through `compute_deal_driver.py`;
      - `e2e_deal_buyer_cli`;
      - `e2e_listing_shapes`;
      - `e2e_buy`;
      - `e2e_non_erc20_settlement`.

      `e2e_deal` and `e2e_deal_buyer_cli` also arm a `vm_remove` rule with no
      stdout, which already reads the default and now prints `vm_remove_data`. No
      VM-lane scenario still supplies a rule's stdout. None is relay-backed. The
      live VM lane is the system evidence of a real guest.

## 6. Recover what `buy` recorded, and qualify the payments upgrade

Delivers D5 and the payments qualification in "Context". Files:
`domains/bare_metal/buyer/tests/test_cli_completion.py`, or a new test module beside
it.

- [ ] 6.1 Test: `buy_bare_metal` writes a real run log under one temporary XDG state
      directory, with its module factories replaced:
      - `fresh_identity`, `registry_client`, and `payment_approval` for the write;
      - `recovery_identity` for the read.

      `_recovered_deal`, the path `access`, `result`, and `teardown` share, reads the
      log back under the same directory. It recovers the same publisher principals,
      publisher, and registry binding. The test fails if the producer's form changes
      without the consumer's.
- [ ] 6.2 Qualify the payments upgrade with no code change:
      - run `make -C kit/arkhai-payments test`;
      - rebuild the bare-metal buyer environment through `make dist` and its
        `reinit`;
      - record in this section's notes that the kit verifies `livemode`, refuses a
        mismatched mode, and refuses unknown receipt fields.
- [ ] 6.3 Verification:
      - `make -C domains/bare_metal/buyer test` (unit);
      - `make -C kit/arkhai-payments test` (unit).

      No package changes, so there is no packaging step. End-to-end:
      `e2e_bare_metal_payment_deal` re-drives a recorded run.

## 7. The fulfillment kit begins a compensating teardown

Delivers D4's kit half ("The kit operation", "The compensation marker"), for the
`fulfillment` delta requirement "Scheduling and assignment". Files:
- `kit/fulfillment/src/market_fulfillment/transitions.py`
- `kit/fulfillment/src/market_fulfillment/fulfillment.py`
- `kit/fulfillment/src/market_fulfillment/fulfillment_persistence.py`
- `kit/fulfillment/src/market_fulfillment/provider.py` (the refusal error)
- the package exports
- `kit/fulfillment/tests/unit/test_transitions.py`, `test_fulfillment.py`, and
  `test_settlement_repository.py`
- a library integration case under `kit/fulfillment/tests/integration/`

- [ ] 7.1 Add the transition `failed` → `teardown_dispatch_pending`, and the constant
      `CREATE_COMPENSATION = "create_compensation"`.
- [ ] 7.2 Add `FulfillmentOrchestrator.begin_compensating_teardown(fulfillment_id,
      *, authorize)`, with two new types:
      - `CompensationCandidate`: the state, the failure reason, and the provider
        metadata, which stays opaque;
      - `CompensationRefusedError`, a `FulfillmentConflictError`.

      In one write transaction it answers by state, as D4's table states:
      - unknown: not found;
      - a teardown already begun or finished: the current view, writing nothing;
      - `failed`, and either refused by `authorize` or the provider's
        `prepare_teardown` raises `ProviderConfigInvalidError`:
        `CompensationRefusedError`, writing nothing;
      - `failed`, and any other preparation error: that error propagates, writing
        nothing;
      - `failed`, authorized, and prepared: the prepared teardown is recorded, and
        the row moves to `teardown_dispatch_pending` with `failure_reason`
        `create_compensation` and its message kept;
      - any other state: `FulfillmentConflictError`, writing nothing.

      `begin_fulfillment_teardown` still refuses `failed`.
- [ ] 7.3 Tests:
      - **Unit:**
        - the transition table;
        - each row of the state table;
        - `authorize` receives one `CompensationCandidate` carrying the record's
          fields, and nothing is written when it refuses;
        - another preparation error propagates, writing nothing.
      - **Library integration (real SQLite):**
        - the operation and a concurrent ordinary teardown request on one
          aggregate settle on one prepared teardown;
        - `recovery_diagnostics` before, during, and after a compensation counts the
          row as `failed`, then in its teardown state, then under `teardown_failed`
          after a failure, and finally under `torn_down`. It never counts a
          compensated `torn_down` as failed.
- [ ] 7.4 Verification:
      - `make -C kit/fulfillment test` (unit and library integration);
      - `make check-packaging`.

      End-to-end: none. No pipeline scenario fails a create deliberately.

## 8. Release compensates eligible failed creates

Delivers D4's compute half ("Eligibility", "The compute-owned seam", "Release paths"),
for the `physical-provisioning` delta requirement "An undelivered lease is released by
what its fulfillment proves". Files:
- `provisioning/compute/src/compute_provisioning/release.py`: `compensable`,
  `TeardownRefused`, the executor, the status port, and the teardown port
- `provisioning/compute/src/compute_provisioning/lease_lifecycle.py`: refusal handling
  in `_begin_recorded_teardown` and the releasing pass, and
  `_mark_release_failed`'s expected handle
- `provisioning/compute/service/src/compute_provisioning_service/services/fulfillment_convergence.py`:
  the teardown-failure write keeps `create_compensation`
- `provisioning/compute/service/src/compute_provisioning_service/container.py`: the
  status port is given the repository and the session factory
- `provisioning/compute/tests/integration/test_release.py`
- `provisioning/compute/service/tests/integration/test_lease_release_api.py`,
  `test_fulfillment_convergence.py`, and `test_compute_contract_api.py`
- `provisioning/compute/service/tests/unit/services/test_ledger_lease_lifecycle.py`

`resolve-compute-family-findings` plans edits to `lease_lifecycle.py` and
`fulfillment_convergence.py`. This section edits other functions in them, and changes
neither `TERMINAL_FAILURE_STATES` nor `_TERMINAL_RESERVATION_STATES` (`design.md`,
"Coordination with `resolve-compute-family-findings`"). Record in this section's notes
whether either change landed first.

- [ ] 8.1 Add `compensable(state, failure_reason, provider_metadata)` to
      `compute_provisioning.release`. It is true when the state is `failed`, the
      reason is `provider_reported_failure`, and the metadata parses as
      `JobFulfillmentMetadata` with `operation` `create`.
- [ ] 8.2 `submit_release` calls `compensable` with the record's fields. It answers
      `TEARDOWN` for a compensable `failed` aggregate, and `UNRELEASABLE`
      (`fulfillment_failed`) for any other `failed` one.
- [ ] 8.3 `FulfillmentServiceTeardownPort.begin_teardown` reads the current state:
      - for `failed`, it calls `begin_compensating_teardown` with
        `authorize=lambda candidate: compensable(candidate.state,
        candidate.failure_reason, candidate.provider_metadata)`;
      - for any other state, it calls `begin_fulfillment_teardown`.

      It translates `CompensationRefusedError` into `TeardownRefused`
      (`compensation_refused`), and passes every other error through.
- [ ] 8.4 `FulfillmentReleaseStatusPort` reads the record through the repository and
      calls `compensable` with its fields. It answers by D4's state table, with
      `READY_FOR_TEARDOWN` for a compensable `failed` aggregate. The composition
      gives it the repository and the session factory the executor holds.
- [ ] 8.5 When `begin_teardown` raises `TeardownRefused`, the lease lifecycle records
      `release_failed` with the refusal's reason and message, under the release
      handle, through the site's conditional write. `_mark_release_failed` gains an
      explicit expected-handle argument:
      - On the release path, `_begin_recorded_teardown` passes the decision's
        `fulfillment_id`, which `begin_release` has just recorded. Its reservation
        was read before that write, so it is not used without the handle.
      - In the releasing pass, the reservation read in that cycle supplies its
        recorded `release_job_id`, as today.

      Every other error stays transient, as today.
- [ ] 8.6 Convergence's teardown-failure write keeps a `create_compensation` reason
      and replaces only `failure_message`. For every other aggregate it writes
      `provider_reported_failure`, as today.
- [ ] 8.7 Update the tests that pin the old behaviour. The design found the set
      below; re-list it at section start:
      - `provisioning/compute/tests/integration/test_release.py`
      - `provisioning/compute/service/tests/unit/services/test_ledger_lease_lifecycle.py`
      - `provisioning/compute/service/tests/integration/test_lease_release_api.py`
      - `provisioning/compute/service/tests/integration/test_compute_contract_api.py`
- [ ] 8.8 Unit and library integration tests:
      - `compensable` for each eligible and ineligible row: quarantined,
        `invalid_provisioned_resource_metadata`, no metadata, unreadable metadata,
        and another provider's metadata;
      - the status port's answer for every state in D4's table;
      - the teardown port: `active`, already begun, compensable `failed`, refused,
        and a state that changed between its read and the kit's transaction;
      - the release path records a refusal under the decision's `fulfillment_id`,
        and a refusal under a handle another release has since replaced is refused
        by the site and left as it is;
      - convergence:
        - a compensating teardown that fails keeps `create_compensation`, and its
          message becomes the teardown's detail;
        - an `active` fulfillment's teardown that fails and later succeeds never
          carries `create_compensation`.
- [ ] 8.9 Application integration, through the typed clients under the mock profile:
      - **Bare metal.** A grant runs but yields no evidence, and the lease is
        terminated:
        - the lease becomes `releasing`;
        - one reclaim job is dispatched;
        - the aggregate reaches `torn_down` carrying `create_compensation`;
        - capacity returns once, and never before `torn_down`;
        - a repeated termination starts no second teardown.
      - **Create in flight, then failed.** The lease is terminated while the create
        is `dispatching`, and the create then fails compensably. The releasing pass
        begins the compensation, and capacity returns at `torn_down`.
      - **Ineligible rows.** For each, the lease is `release_failed` and capacity is
        held.
      - **Refused compensation.** For a compensable row whose create job is missing:
        - the lease is `release_failed` with `compensation_refused`, under the
          handle it entered `releasing` with;
        - the aggregate stays `failed`;
        - capacity is held.
      - **A failing compensation** leaves the lease `release_failed`, with capacity
        held and the aggregate carrying `create_compensation`.
      - **Delivered teardown.** An `active` fulfillment whose teardown fails once and
        then succeeds is not reported compensated.
      - **VM.** A create that fails after dispatch on a relay-backed pool tears
        down, and its relay port returns with the capacity, not before. Its create
        output comes from a rule armed in the test, since the default mock reports
        no relay.
- [ ] 8.10 Verification:
      - `make -C provisioning/compute test` (unit and library integration);
      - `make -C provisioning/compute/service test` (application integration);
      - `make check-packaging`.

      End-to-end: no pipeline scenario fails a create deliberately, and none is
      added. The application integration cases are the lowest level that proves the
      lifecycle. The live bare-metal lane's supported teardown is the system
      evidence.

## 9. A VM storefront reads a compensating fulfillment as a failed delivery

Delivers D4's VM storefront reader ("Readers"), for the `physical-provisioning` delta
requirement "An undelivered lease is released by what its fulfillment proves". Files:
- `domains/vms/storefront/src/market_storefront/services/fulfillment_resume_runtime.py`
- `domains/vms/storefront/tests/unit/test_fulfillment_resume_runtime.py`
- `domains/vms/storefront/tests/unit/test_failure_policy.py`, for the failure actions
  in `domains/vms/storefront/src/market_storefront/failure_actions.py`

- [ ] 9.1 The fulfillment resume treats a `create_compensation` reason, in any state,
      as a failed delivery, as it treats `failed`.
- [ ] 9.2 Unit tests:
      - an aggregate in `teardown_dispatch_pending`, `tearing_down`,
        `teardown_failed`, or `torn_down` carrying `create_compensation` is a failed
        delivery;
      - a delivered aggregate's `torn_down`, carrying another reason, is not;
      - the failure actions' capacity release is still refused by the guarded site
        release until the aggregate is `torn_down`.
- [ ] 9.3 Verification:
      - `make -C domains/vms/storefront test` (unit and application integration);
      - `make check-packaging`.

      End-to-end: none. No pipeline scenario fails a create deliberately.

## 10. A bare-metal reclaim of an account that was never created succeeds

Delivers D4's domain safety for bare metal, for the delta requirement "A bare-metal
reclaim tolerates an account its grant never created". Files:
- `domains/bare_metal/provisioning/iac/ansible/roles/bare-metal-access/tasks/main.yml`
- `domains/bare_metal/provisioning/adapter/tests/test_bare_metal_codec.py` (the
  role-variable test class)

- [ ] 10.1 Before key removal or locking, the reclaim checks whether the tenant
      account exists. When it does not:
      - it skips key removal and locking;
      - it reports `account_present: false` in its fact;
      - it creates nothing.

      An existing account is handled as today, under each policy.
- [ ] 10.2 Tests:
      - role-structure unit tests that the existence check precedes every task
        reading the account, and that the reclaim fact carries `account_present`;
      - `ansible-playbook --syntax-check` on the access playbook;
      - the codec's reclaim interpretation accepts the new field.

      Owed outside this section: running the role against a host that lacks the
      account is the live lane's evidence. No repository suite runs a playbook
      against a host.
- [ ] 10.3 Verification:
      - `make -C domains/bare_metal/provisioning/adapter test` (unit);
      - `make check-packaging`.

      End-to-end: the bare-metal mock lane runs no playbook. The live bare-metal
      lane is the system evidence.

## 11. A compute shape need not state a GPU

Delivers D7's schema and VM vocabulary, for the delta requirement "The compute family
shares one capability schema". Files:
- `domains/compute/src/arkhai_compute/capability_schema.py`
- `domains/compute/tests/test_capability_schema.py`
- `domains/vms/domain/src/arkhai_vms/schema.py`, `capability_shapes.py`, and their
  tests
- `domains/vms/listings/src/arkhai_vms_listings/`: models, resources, pricing, and
  `listing_shapes.py`

- [ ] 11.1 Make `gpu.count` and `gpu.model` not required. The VM shape rule refuses a
      `gpu` family that names only one of them. Bare metal's own rules are
      unchanged, and its tests prove it still refuses a shape without `gpu`.
- [ ] 11.2 Make the listing models and accessors tolerate a missing GPU:
      - `ComputeResource`'s GPU fields become optional;
      - compute and token resources are told apart by the token resource's fields,
        and `resource_is_compute` uses the same test;
      - `VmListing` requires both GPU fields or neither;
      - `ResolvedShape`'s GPU accessors tolerate absence.
- [ ] 11.3 Unit tests:
      - flattening, unflattening, and the digest of a shape without `gpu`;
      - a half-stated `gpu` refused;
      - a CPU listing parsed as compute;
      - a token listing still parsed as tokens;
      - the bare-metal refusal kept.
- [ ] 11.4 Verification:
      - `make -C domains/compute test` (unit);
      - `make -C domains/vms/domain test` (unit);
      - `make -C domains/vms/storefront test-unit`, where the listings package's
        tests run;
      - `make check-packaging`.

      End-to-end: `e2e_listing_shapes` re-runs its GPU shapes over the changed
      schema.

## 12. The VM storefront publishes, prices, and claims a stated CPU-only shape

Delivers D7's storefront half ("CPU-only VM shapes"), for the delta requirements
"Every VM listing is a listing shape" and "A listing's published shape comes from its
source declaration". Files:
- `domains/vms/listings/src/arkhai_vms_listings/reconciler.py`
- `domains/vms/settlement/src/arkhai_vms_settlement/compute_lease.py`
- `domains/vms/storefront/src/market_storefront/controllers/admin_controller.py` (the
  reservation response's `gpu_count`)
- `domains/vms/storefront/src/market_storefront/models/capacity_admin_models.py`
- `core/storefront-client/src/storefront_client/models.py`
  (`ReserveCapacityResponse.gpu_count`)
- `domains/vms/storefront/tests/integration/test_reconciler_derivation.py` and
  `test_admin_api.py`
- `kit/site/tests/integration/test_ledger.py` (test only)

The administrator controller is also in `resolve-compute-family-findings`'s plan
(`_INTERRUPTIBLE_HELD_STATES`). This section edits only the reservation response.

- [ ] 12.1 Reconciler member usage keeps each member that has a resource type and
      declared capacity, for stated shapes:
      - GPU totals are optional, and are reported only for default generation, which
        is unchanged;
      - listing reopening and GPU-model ordering tolerate a shape without a model;
      - the compute lease encoding omits absent GPU fields.
- [ ] 12.2 The VM administrator reservation response's `gpu_count` becomes optional,
      in the server model and the storefront client's model:
      - it is read from the reservation's `dimensions` when they are present, and is
        absent when they name no `gpu_count`;
      - it is read from `allocated_gpu_count` only when the reservation has no
        `dimensions`;
      - nothing coerces it to one.
- [ ] 12.3 Update `test_reconciler_derivation.py`'s case for a member without GPUs:
      it yields nothing under default generation, and serves a stated CPU shape.
- [ ] 12.4 Library integration in `kit/site`: a claim whose `dimensions` name vCPU,
      memory, and disk and no `gpu_count` is admitted holding exactly those, with
      `units` 0 and its `dimensions` authoritative. Its release returns exactly
      those. Add the case only if `test_ledger.py` does not already prove it, and
      record which in this section's notes.
- [ ] 12.5 Application integration, through the storefront's typed client against a
      site projection:
      - a pool hint stating `{cpu: {count: 2}, memory: {gib: 2}, storage: {gib: 20}}`,
        over a member declaring vCPU, RAM, and disk, publishes one listing with no
        GPU fields;
      - negotiating it builds a capacity claim requesting exactly those quantities;
      - per-family rates price it from the flat tiers, and a storefront configuring
        per-GPU-model terms and rates applies none of them to it;
      - reserving the CPU-only listing as administrator, through the storefront
        client's `admin_reserve_capacity`, returns a response with no `gpu_count`.
- [ ] 12.6 Verification:
      - `make -C domains/vms/storefront test` (unit and application integration);
      - `make -C core/storefront-client test` (unit);
      - `make -C kit/site test` (library integration);
      - `make check-packaging`.

      End-to-end:
      - `e2e_listing_shapes` re-runs for its GPU shapes.
      - No pipeline lane provisions a CPU-only VM. The live VM lane is the system
        evidence (`design.md`, "CPU-only VM shapes").

## 13. An aarch64 guest, and a teardown that removes only its own guest

Delivers D7's guest recipe and D9, for the delta requirements "A VM guest matches its
host's architecture" and "A VM teardown removes only what its guest created". Files:
- `domains/vms/provisioning/iac/ansible/roles/vm-management/tasks/`: `vm-create.yml`,
  `vm-remove.yml` with the cleanup script it generates, and `vm-undefine.yml`
- new role-structure tests in `domains/vms/provisioning/adapter/tests/unit/`
- `domains/vms/provisioning/iac/README.md`

- [ ] 13.1 Select the cloud image, machine, and firmware from the target host's
      architecture:
      - each architecture's image is pinned to a dated release with its published
        checksum, and verified before use;
      - `aarch64` uses `--arch aarch64 --machine virt --boot uefi`;
      - an architecture with no pinned image fails before any host effect.

      The `x86_64` path keeps its behaviour, except that its image is now pinned and
      verified.
- [ ] 13.2 Every firewall and NAT rule a create adds for a guest carries a comment
      naming the guest:
      - the cleanup script removes rules by that exact comment;
      - unmarked rules are removed by the guest's `/32` address, never a prefix;
      - the subnet-wide masquerade rule is left alone.
- [ ] 13.3 `vm_remove` with no cleanup script:
      - removes what it finds by the guest's name: the domain with its storage and
        firmware variables, the images, the relay proxy block, the DHCP
        reservation, and the marked rules;
      - reports the guest absent only when it finds none of them;
      - fails, naming the artifact, when it finds one it cannot attribute.
- [ ] 13.4 The VM IaC README lists the host prerequisites (`design.md`, "CPU-only VM
      shapes"). It warns that `playbooks/host-kit/vm-setup.yaml` must not run on a
      host whose management access must be preserved.
- [ ] 13.5 Tests:
      - **Role-structure unit tests:**
        - architecture selection;
        - checksum verification before definition;
        - the comment on every added rule;
        - no prefix match in cleanup;
        - the attribution checks of the missing-script branch.
      - `ansible-playbook --syntax-check` on the VM operations playbook.

      Owed outside this section: a real guest boot and teardown on `aarch64` are the
      live VM lane's evidence.
- [ ] 13.6 Verification:
      - `make -C domains/vms/provisioning/adapter test` (unit);
      - `make -C provisioning/compute/service test`;
      - `make check-packaging`.

      End-to-end: the VM mock lanes run no playbook, so recipe changes do not reach
      them. The live VM lane is the system evidence.

## 14. Closeout

The eleven parts of `openspec/README.md#plan-closeout-requirements`, in order.
Closeout changes documentation only. A part that would need a code edit returns the
change to implementation.

- [ ] 14.1 **Comment hygiene.** Run `make check-comment-hygiene`. Any finding, or a
      comment Sections 2–13 added that still describes history, returns the change
      to implementation.
- [ ] 14.2 **Import placement.** Confirm that every import Sections 2–13 added is at
      module level, or carries a verified reason to stay local.
- [ ] 14.3 **Documentation compliance.** Re-check D1–D10 against `openspec/README.md`'s
      placement rules and `design.md`'s promotion record.
- [ ] 14.4 **Narrative compression.** Compress these task notes to final behaviour,
      material evidence, deferred work, and destinations.
- [ ] 14.5 **Roadmap currency**, in `docs/development/ROADMAP.md`:
      - Under "Goal 1 — Consolidate physical-resource authority in the provisioning
        service", the gap row "The real runner reports no structured
        terminal-failure evidence…" notes that successful results are read in
        either callback form. It stays open for failure classification.
      - Under "Goal 2 — Negotiate full compute capability, not GPU count alone", the
        current state notes that VM shapes stated without GPUs are sold.
      - Under "Payment qualification boundaries", record the gaps this change leaves
        open:
        - D6's exhausted teardown job;
        - D10's operational precondition, that a refresh or reopen under the same
          identity keeps a listing's pause;
        - D10's limits: successor listings are created unpaused, no permanent
          requirement states per-listing pause semantics, no test closes a paused
          listing by reconciliation and reopens it, and bare metal has no test of a
          paused listing refusing an opening;
        - `gpu-optional-compute-shapes`'s remaining scope.
      - Name the update in `design.md`'s promotion record.
- [ ] 14.6 **Campaign index currency.** Update this change's row in
      `openspec/changes/README.md` to `in closeout`, with notes stating what is true
      at closeout, and keep the dependency graph line to
      `gpu-optional-compute-shapes`. That row's `Depends on` stays until archive
      cleanup. Run `make check-change-index`, and name the update in the promotion
      record.
- [ ] 14.7 **Packaging.** Run `make check-packaging` and
      `make check-architecture-change CHANGE=repair-compute-purchase-recovery`. Run
      `make check-agent-skills` only if the change touched `.agents/`, `.claude/`, or
      `.codex/`; it is not planned to.
- [ ] 14.8 **End-to-end pipeline.** Record the pipeline run and its result:
      - the bare-metal lane's `e2e_bare_metal_mock_deal` and
        `e2e_bare_metal_payment_deal`;
      - the VM lane's `e2e_deal`, `e2e_deal_buyer_cli`, `e2e_listing_shapes`,
        `e2e_buy`, and `e2e_non_erc20_settlement`, which read the shipped-form
        default.

      Record the live lanes' qualification separately, as live evidence or as named
      blockers, never as pipeline evidence. The live lanes are the real bare-metal
      and CPU-only ARM64 VM test purchases, each run under D10's operational
      conditions.
- [ ] 14.9 **Promotion**, per `design.md`'s promotion record:
      - `docs/development/ARCHITECTURE.md` "Release": the table's `failed` row splits
        into compensable and not.
      - `openspec/specs/physical-provisioning/architecture.md`:
        - "Durable jobs, transient workers": fact reading and linkage, and a
          bare-metal reclaim's diagnostic result, whose teardown the reclaim
          job's status decides;
        - "The host registry owns the connection": the tenant-facing port;
        - "Proof-driven release": compensation, and the corrected `teardown_failed`
          requeue sentence, which says the requeue re-observes the same failed job
          and does not re-run it (D6).
      - `openspec/specs/fulfillment/architecture.md` "Durable persistence and
        recovery": the compensating teardown and its marker.
      - `openspec/specs/storefront-publication/architecture.md` "Listing shapes and
        the storefront's authority" and "Shape pricing": stated shapes without GPUs,
        and flat-tier pricing.
      - `docs/development/TESTING.md` "4. System Integration Tests (End-to-End)":
        mock output prints the shipped form for the job, and the VM scenarios use
        the default.
      - `docs/development/DEPLOYMENT_AND_CONFIG.md`:
        - "Definition documents", the host-inventory paragraph: `public_port=`;
        - "Storefront listing shapes and pool overrides": the shape-constraints
          bullet, corrected for VM shapes stated without the `gpu` family.
      - `domains/vms/provisioning/iac/README.md` "Prerequisites": the aarch64 host
        prerequisites and the `vm-setup.yaml` warning.
      - `docs/seller-quickstart.md` "6. Live KVM provisioning": the tenant-facing
        route and aarch64 hosts.
      - `docs/development/VALIDATION_RUNBOOK.md`, a new generic section on running two
        lanes against one machine in sequence (D10):
        - the freeze and the per-listing pause;
        - read-backs in the site's states, `reserved`, `provisioning`, `leased`,
          `releasing`, `release_failed`, and `unmanaged`, with `provisioning_failed`
          read as terminal;
        - each member's full `available` mapping compared with its `capacity`
          mapping;
        - every accepted deal drained, with no refund taken as proof;
        - the precondition that a refresh or reopen under the same identity keeps
          the pause.
      - `openspec/specs/README.md`: no new capability or companion, so no edit.
        Confirm it.
      - Complete the promotion record.
- [ ] 14.10 **Documentation citations.** Run
      `make check-doc-citations CHANGE=repair-compute-purchase-recovery`, then
      `openspec validate repair-compute-purchase-recovery --strict`.
- [ ] 14.11 **Archival.** Run `openspec archive repair-compute-purchase-recovery -y`,
      which merges the deltas into `openspec/specs/`. The deltas were not promoted by
      hand, so `--skip-specs` is not used.
