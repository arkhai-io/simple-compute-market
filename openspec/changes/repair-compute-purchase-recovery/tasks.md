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

**Test cadence (owner's decision, after Section 4), per frozen round.** For the rest
of this change:
- Focused suites and packaging gate every intermediate commit, whether a section or a
  merge of `dev`. No intermediate commit owes the full suite, a review, or validation.
- Once a round's last section is committed, its candidate is frozen. The full
  `make test`, one independent implementation review, and one validation run once on
  that frozen candidate. Round 1 ran them after Sections 5 and 6, covering the merge.
  Round 2, Sections 7 to 14, is one preflight round: its candidate freezes after
  Section 14, and both live lanes run on that one validated candidate
  (`design.md`, "Implementation cadence").
- A passing result is reused while its candidate is unchanged.
- The live lanes, each on a validated candidate, and the owner's approval before
  merging to `dev` are unchanged.

**End-to-end evidence.** Validation runs the Helm checks and the pipeline on each
frozen round candidate. Each section names the scenarios (pytest markers in
`e2e-tests/`) that exercise it, or says that none does. No section owes evidence from
a CI workflow that only a push produces.

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

      **Correction after the scope revision of 2026-10-29.** The owner withdrew D7
      (`design.md`, "Scope revision", D7) before any of its slice was implemented.
      The split this task confirmed is undone: `gpu-optional-compute-shapes` owns
      its whole scope again, its proposal no longer records the slice as delivered
      here, and its index row no longer names this change in `Depends on`. The
      dependency graph lines to it are removed. This task stays checked as the
      record of what was confirmed then.

      **Correction after merging `dev` at `1f157a17d`, after Section 14.**
      `gpu-optional-compute-shapes` has since landed on `dev` and is archived. Its
      archived proposal and index row come from `dev` and name this change nowhere;
      the record this branch had added to its active proposal was dropped with the
      archive (14.7).

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

**Correction after merging `dev`: `public_port` belongs to `ssh` version 2.** The
tasks above added `public_port` to version 1 of the self-versioned `ssh`
connection. `RELEASING.md`'s versioning policy forbids that change in place, so D3's
compatibility is settled again (`design.md`, D3, "Compatibility, as settled after
merging `dev`"). These tasks correct it, after 3.1–3.4 and before Section 5. Files:
- `provisioning/compute/src/compute_provisioning/hosts/connection.py` (the registry
  keyed by kind and version) and its unit tests;
- `provisioning/compute/ansible/src/compute_provisioning_ansible/connection.py` (one
  codec per version, a strict read per version, and the factory's version choice) and
  `__init__` exports;
- the service's composition in `container.py` and its test fixtures;
- the tests and fixtures that state a port: the Ansible kit's, the bare-metal adapter's
  `tests/execution.py`, and the service's `test_hosts_api.py`.

- [x] 3.5 The host authority's `ConnectionCodecs` keys codecs by kind and version.
      `build` dispatches to the codec for the submission's own kind and version, and
      carries a previous connection's protected values forward whatever its version.
      A duplicate kind-and-version registration is refused, and so is a version no
      codec of the kind serves, naming the versions served. The `ConnectionCodec`
      protocol is unchanged. Unit tests cover dispatch, both refusals, and the
      single-version registration every existing caller makes.

      Done (unit), in `hosts/connection.py`, with `versions(kind)` naming what a
      kind is served at. `codec` now takes the version. Its only production caller
      is `build`. Seven cases in `provisioning/compute/tests/unit/test_connection_codecs.py`
      cover dispatch, a lone version, an unserved version, an unknown kind, a
      duplicate pair, and a previous connection at another version or of another
      kind.

      Correction: `codec` takes the version optionally again, while the kind is
      served at one version, with three more cases (3.8's corrections).
- [x] 3.6 `SshConnectionCodec` serves one version, given at construction: version 1
      without `public_port` (`extra="forbid"`, so a stated field is refused even as
      null), or version 2 with it. `parse` checks the envelope's kind and version
      before its fields, and refuses any other. `ssh_connection()`, and the INI
      import through it, submit version 2 when a port is stated and version 1
      otherwise. The service registers the codec at both versions. Unit tests cover:
      - each version's fields, including version 1's refusal of a port and its record
        stored as before version 2 existed;
      - version 2's port bounds and an explicit version 2 without a port;
      - an unsupported version refused by `parse` and `build`;
      - the factory's and the INI import's version choice;
      - a protected key carried from a version-1 record into a version-2 update.

      Done (unit):
      - **The models.** `SshConnectionV1` has version 1's fields in their original
        order, so a version-1 record is stored exactly as before. `SshConnection`
        is version 2's model and the view executors read at either version.
      - **The codec.** `SshConnectionCodec(key, version=...)` defaults to version
        1, as every earlier caller registered it. `ssh_connection_codecs(key)`
        gives one codec per served version, and the service's composition
        registers them.
      - **`parse`.** It refuses an unserved kind or version before reading any
        field.
      - **Exports.** `SSH_CONNECTION_VERSION` is replaced by
        `SSH_CONNECTION_VERSIONS` and `SSH_PUBLIC_PORT_VERSION`. Nothing outside
        the kit read it. Corrected: it stays exported, at 1, beside them (3.8's
        corrections).
      - **Tests.** `test_ssh_connection.py` covers each case listed above.
        `test_inventory.py`'s round trip now builds through the registry and shows
        that an INI entry stating a port is submitted at version 2 and every other
        entry at version 1. `test_runner.py`'s routed host is at version 2.
- [x] 3.7 Fixtures that state a port move to version 2, and nothing else changes for
      callers that state none. Application integration through the typed host
      client covers:
      - a version-1 registration stored unchanged;
      - a version-2 route stored and rendered;
      - a version-1 connection stating a port refused;
      - an unsupported version refused.

      Done (application integration), in `test_hosts_api.py`:
      - `TestTenantFacingRoute`'s routed host is read back and stored at version 2,
        and its plain host at version 1;
      - `TestConnectionVersions` covers a registration stating no version (stored at
        version 1 with its original mapping), a version-1 connection stating a port
        or a null (400 naming `public_port`, nothing stored), and version 3 (400
        naming versions 1 and 2, nothing stored).

      The service's fixtures register `ssh_connection_codecs`. The bare-metal
      adapter's `host_with` states version 2 when it adds a port. Callers that
      state no port changed nothing: the e2e helpers, the validation runbook's
      requests, and the issue-discovery tool's configuration all submit version 1.
- [x] 3.8 Verification:
      - the family kit's, the Ansible kit's, and the bare-metal adapter's suites (unit
        and library integration);
      - the service's unit and integration suites under `ACTIVE_PROFILES=mock`;
      - `make lock`, `make check-packaging`, and `make check-change`.

      **Packaging.** `arkhai-compute-provisioning` takes its one bump for this change
      against `dev`, from 0.21.0 to 0.22.0. Only the provisioning service composes the
      registry with two versions of a kind, so its floor on the family kit rises. The
      Ansible kit, the service, and the bare-metal adapter are already bumped once for
      this change, so none is bumped again.

      Promotion: the D3 row of `design.md`'s promotion record.

      Done, on the final source:
      - `make -C provisioning/compute test`: 250 passed (unit and library
        integration);
      - `make -C provisioning/compute/ansible test`: 133 passed (unit);
      - `make -C domains/bare_metal/provisioning/adapter test`: 77 passed (unit);
      - `make -C domains/vms/provisioning/adapter test`: 256 passed (unit);
      - `make -C provisioning/compute/service test`: 607 unit and 461 application
        integration passed;
      - `make lock`: only `arkhai-compute-provisioning`'s version and the
        service's floor changed, in five locks;
      - `make check-packaging`: passed.

      The 0.22.0 family kit, 0.5.0 Ansible kit, 0.20.0 service, and 0.12.0
      bare-metal adapter wheels equal their source. Under the owner's cadence, the
      full `make test` is Round 1's, after Sections 5 and 6.

      End-to-end: no scenario states a tenant-facing port, so every pipeline host
      stays at version 1. Owed by validation: none.

      **Corrections after the parent's review of this task.**
      - **Suite levels.** The counts above name mixed levels, which a folder name
        does not settle:
        - the family kit's 250 include library integration against real SQLite,
          such as `tests/integration/test_host_authority.py`;
        - the VM adapter's 256 include its `tests/integration` suite;
        - the service's 461 combine application integration through the typed
          clients with direct-storage migration tests, such as
          `test_retired_reservation_states_migration.py`, and startup-lifecycle
          checks. They are not all application integration.

        The same holds for the service counts Sections 3 and 4 recorded earlier
        (669 and 542, 669 and 544).
      - **Two additive API corrections, made after the service suite passed.**
        - `SSH_CONNECTION_VERSION` stays exported, at 1. It is the version a
          connection stating no port is submitted at, and the default of
          `SshConnectionCodec`, at class and instance; a stated version overrides
          it.
        - `ConnectionCodecs.codec(kind)` keeps its one-argument form while the kind
          is served at one version. A kind served at several needs the version
          stated, and its refusal names the versions; `build` still passes the
          version explicitly.

        They changed only `hosts/connection.py` and the Ansible kit's
        `connection.py` and `__init__.py`, with their unit tests. Their evidence:
        - `make -C provisioning/compute test`: 253 passed (unit and library
          integration);
        - `make -C provisioning/compute/ansible test`: 134 passed (unit);
        - the service's `TestConnectionVersions`, `TestTenantFacingRoute`, and
          `test_test_router_mounting.py`, after its environment was refreshed: 9
          passed (application integration through the typed client, and the
          fixtures' mounting).

        The service's full 607 and 461 ran on the source before these
        corrections. No path that service composition takes changed: the service
        registers both versions explicitly, and `build` states the version.

**Correction after the Round 1 implementation review: `ssh` is served at version 2
only.** The review's F1 (`reviews/03-implementation-external.md`) found the version-2
to version-1 rollback untested. The owner noted that the repository has no production
deployment and chose to retire version 1 rather than test a downgrade, before Sections
7 onward (`design.md`, D3, "Compatibility: `ssh` is served at version 2 only";
`interventions.jsonl`). Tasks 3.5–3.8 above stand as the record of what was built and
verified then. These tasks supersede what they established about version 1 and the
registry keyed by kind and version. The review's other findings are not dispositioned
here. Files:
- `provisioning/compute/ansible/src/compute_provisioning_ansible/connection.py` and
  `__init__.py`: one model and one codec, at version 2;
- `provisioning/compute/src/compute_provisioning/hosts/connection.py`, restored to
  `dev`'s registry keyed by kind, and the removal of
  `provisioning/compute/tests/unit/test_connection_codecs.py`;
- the service's `container.py`, `pyproject.toml`, and lock, and its test fixtures;
- the tests and fixtures that build `ssh` envelopes or submissions: the Ansible kit's,
  both adapters', the service's, and three `e2e-tests` helpers;
- the host requests in `docs/development/VALIDATION_RUNBOOK.md` and
  `tools/issue-discovery/config/phases/local.yaml`.

- [x] 3.9 Amend the design, proposal, delta, and plan: D3's compatibility, the
      `physical-provisioning` delta's "Host registry records the connection port" and
      "Host connections are typed by their implementation's codec", the proposal's
      D3 bullet and Impact, the D3 promotion row, and the ledger entry for F1.

      Done. D3's two earlier compatibility passages are replaced by one: version 2
      only, the generic submission default left at 1 so an unversioned `ssh` request
      is refused, a stored version-1 host refused at execution until it is updated
      or imported again, how each seam moves it forward and when in a rollout, and
      no rollback to version 1. The delta drops version 1's acceptance and gains
      scenarios for an unversioned or version-1 submission, a stored version-1 host
      refused before any playbook, and a stored host moved forward by an update,
      keeping its key, or by an import. "Compatibility, migration, and rollback" and
      the context note follow. The ledger records F1's redirection.
- [x] 3.10 One `ssh` model and codec at version 2:
      - `SshConnection` carries `public_port`; `SshConnectionCodec.version` is 2, with
        no version argument;
      - `ssh_connection()` and the INI import submit version 2 always, an absent or
        null port stored with no key;
      - `parse` refuses any other kind or version before any field, telling the
        operator to re-register the host;
      - a protected key a submission does not resubmit is carried from the previous
        row whatever its version, as opaque ciphertext;
      - `SshConnectionV1`, `SSH_CONNECTION_VERSIONS`, `SSH_PUBLIC_PORT_VERSION`, and
        `ssh_connection_codecs` are removed, and `SSH_CONNECTION_VERSION` is 2;
      - the family registry returns to `dev`'s, keyed by kind, whose `build` refuses
        another version naming the one served; the service registers one codec.

      Done. Before deleting an export every caller was searched: only tests, the
      service's composition, and the bare-metal adapter's test fixture used the
      removed names. `ConnectionSubmission` (`compute_provisioning_contracts`)
      still defaults to version 1, so the three `e2e-tests` helpers that registered a
      host without a version now state version 2. The VM helper in
      `vms/conftest.py` skips its scenario when registration fails, so without
      this it would have skipped rather than failed. The validation runbook's
      registration and update requests, and the issue-discovery tool's local phase,
      state `"version":2`. The runbook's update request is also the re-registration
      step for a host stored at version 1.

      The service's migration that first wrote connection envelopes from older host
      columns wrote them at version 1, and it is not edited: a host it migrated is
      refused at execution until it is submitted again, like any stored version-1
      host.
- [x] 3.11 Tests:
      - **Unit (Ansible kit):**
        - the codec at version 2;
        - a connection with no port, a null port, a port beside or without
          `public_host`, and malformed ports;
        - every operator submission at version 2;
        - stored connections at version 1, version 3, and another kind refused by
          `parse` and `validate`;
        - a version-1 row with a protected key built forward through the registry,
          keeping the key;
        - a version-1 submission refused naming version 2;
        - a host stored at version 1 never reaching an inventory;
        - the INI round trip, every entry at version 2.
      - **Application integration (service, typed clients, mock profile):**
        - an unversioned registration, and explicit versions 1 and 3, refused with
          400 naming version 2 and nothing stored;
        - a registration and an INI import without a port, stored at version 2 with
          no `public_port` key, and a job's inventory carrying the connection's own
          address and port;
        - a routed registration rendering the buyer route, as before;
        - an embedded-key host updated at version 2 naming no key, keeping its
          ciphertext;
        - a seeded version-1 row: a job against it fails before any inventory is
          written or playbook started, with the re-register message; an update at
          version 2 naming no key stores version 2, keeps the seeded ciphertext byte
          for byte and its public mapping, and then a job succeeds with the embedded
          key materialized; an INI re-import stores it at version 2 with the key path
          its entry names.

      The version-1 rows are written directly as setup, since nothing registers
      version 1 any more; every assertion goes through the typed clients or reads the
      stored row. Keys are development placeholders. No downgrade test is added.

      Done. No red was manufactured. The behaviour under test is new, and the
      first targeted run failed in one case, which was the test's fault, not the
      service's: it awaited a failed job's result, and the typed client raises
      `ComputeProvisioningJobError` on a failed job. The test now expects that
      error and its message.
- [x] 3.12 Verification, after `make dist-clean` and `make dist`, so that no stale
      0.22.0 family wheel stays in the wheelhouse to be locked:
      - `make lock` for the five projects that lock the family kit: every lock now
        records it at 0.21.0, as on `dev`, and the service's floor on it is back to
        `dev`'s `>=0.20.0`;
      - `make -C provisioning/compute test`: 243 passed (unit and library
        integration); the family kit's source, tests, and version equal `dev`'s;
      - `make -C provisioning/compute/ansible test`: 133 passed (unit);
      - `make -C domains/bare_metal/provisioning/adapter test`: 77 passed (unit);
      - `make -C domains/vms/provisioning/adapter test`: 262 passed (unit and library
        integration);
      - the service's `test-unit`: 607 passed (unit);
      - twenty service integration modules: those that register, update, or import
        hosts or run jobs on them, the capacity modules, and the router mounting
        module, with the mock profile. 319 passed and 1 failed, the case 3.11
        describes; after the fix, `test_hosts_api.py` passed 52. These are mixed
        levels: application integration through the typed clients, with
        direct-storage setup and reads;
      - `make -C e2e-tests test-unit`: 172 passed (unit);
      - `make check-packaging` (architecture included), `make check-comment-hygiene`,
        `make check-change` (strict OpenSpec validation and citations included), and
        `make check-tasks`: passed;
      - the family kit's 0.21.0, the Ansible kit's 0.5.0, the service's 0.20.0, and
        both adapters' wheels equal their source; the locks changed only the family
        kit's version and the service's floor on it.

      **Packaging.**
      - `arkhai-compute-provisioning` returns to 0.21.0: its source equals `dev`'s,
        so it changes nothing to bump.
      - `arkhai-compute-provisioning-ansible` stays at 0.5.0, bumped once for this
        change; retiring version 1 is the incompatible change that minor bump
        allows before 1.0.0.
      - The service stays at 0.20.0, its Ansible floor at `>=0.5.0`.
      - The adapters' versions are unchanged: only their tests changed here.

      **End-to-end.** Every pipeline host is registered by the three helpers, now at
      version 2, or imported from an inventory, which submits version 2. The VM and
      bare-metal lanes therefore exercise version-2 registration and execution. No
      scenario seeds a version-1 row. The earlier pipeline and Helm passes ran
      against the candidate that served both versions, so they are not evidence for
      this correction. Owed by validation: the pipeline and Helm on the corrected
      candidate.

      **Retained development and test hosts.** A host stored before this change is
      at version 1 and runs nothing until it is moved forward. In the rollout that
      deploys this service, once it is running and before any work is dispatched to
      the host, submit the host's connection again at version 2.
      - **Update.** `PUT /api/v1/hosts/{host_id}` replaces the whole public mapping,
        so it restates every stored public field, `key_path` included where the host
        has one, and the tenant route, at version 2, with no `private_key` secret.
        Omitting an existing `key_path` would leave the connection naming no key,
        and the update is refused. A host with a protected key and no `key_path`
        keeps that key as stored ciphertext.
      - **Import.** For a host whose key is a file, an inventory import naming the
        same file is the alternative.

      Then read it back at version 2, with its key reference or protected scheme,
      pool, enabled state, and route unchanged; any listing that must not trade stays
      paused throughout. Nothing rewrites a row on its own, and no database row is
      edited by hand. This is done in the reviewed rollout, not by this section.

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

**Correction after merging `dev`, before this section started.**
`resolve-compute-family-findings` landed first and is archived. This branch merged
`dev` after Section 4 and before this section, and these corrections come from that
merge:
- **The VM codec tests.** They moved, unchanged, to
  `domains/vms/provisioning/adapter/tests/unit/test_vm_codec.py`. Add 5.5's codec
  cases there. `make -C domains/vms/provisioning/adapter test` runs them, and the
  provisioning service's suite no longer does.
- **The scenario rules.** Each of the five scenario modules now builds its create
  rule as a typed `MockRuleCreate`, from `compute_provisioning_contracts`, through the
  family's mock-rule client. 5.4 still applies: drop the `result_stdout` argument and
  keep `rule_id`, `match`, and `pause_before_result`.
- **The fixed output.** The fixed create output these rules print still names
  `vmuser` and a guest that is not the job's. A search at the merge
  (`rg -n "vmuser|e2e-test-vm|e2e-shapes-vm|e2e-buy-vm" e2e-tests/`) found those values
  only inside that output, and no assertion on them. 5.4 re-runs the search at
  section start.
- **The service's `vm_mock_output` users.** The provisioning service's integration
  conftest, `test_test_controller.py`, and `test_system_api.py` use it. 5.6's
  `make -C provisioning/compute/service test` therefore still covers the mock profile,
  though not the codec tests.
- **The service's integration fixtures.** They mounted the test routers on the shared
  app whenever `app.routes` did not list the routers' paths. FastAPI lists an
  included router as one entry, not by its paths, so every fixture setup included
  the routers again and wrapped the app's lifespan once more.
  `test_retired_settings_startup.py` then exhausted the stack entering the lifespan.
  The fixtures now mount through `mount_unless_served`, in the service's integration
  conftest, which asks the app's own routing whether each route is served.
  `tests/integration/test_test_router_mounting.py` holds that a second mount changes
  nothing.

- [x] 5.1 Replace `extract_vm_fact`'s private `msg:` fallback with Section 2's
      reader. The codec supplies the expected action from its own mapping, beside
      `VM_RESULT_FACTS`: the job's `vm_action`, which is `create` for a create and
      `vm_remove` for a remove, as each VM role prints it. The shared reader holds no
      VM knowledge. Behaviour on JSON-form output is unchanged.

      Done, in `codec.py`:
      - `extract_vm_fact` reads through `read_fact`, with the expected action from
        `VM_FACT_ACTIONS`, beside `VM_RESULT_FACTS`: each VM action's fact names
        the action as its role prints it, so `create` and `vm_remove` among them.
      - The forward-scanning `msg:` fallback, and the regex reads of a port and an
        account over the whole output (`extract_ssh_port`, `extract_tenant_user`),
        are removed. No production code used them outside the codec.
      - The monitor and check roles print no `action`, so only their JSON `var:`
        form is read. The removed fallback could not read their `msg:` form
        either, so nothing they report is lost; it is a limit of those roles,
        left as it is.
- [x] 5.2 A create's fact yields evidence only when:
      - its `action` is `create`;
      - its `vm_name` is the job's `vm_target`;
      - its `status` is `success`.

      The tenant account and forwarded port are read from that fact
      (`tenant_user`, `external_ssh_port`) or its `frp` block, no longer by
      searching the whole output. The fact's `host` is not compared. Otherwise the
      result carries no evidence, and a detail naming the mismatch.

      Done:
      - **Linkage.** `create_fact_mismatch` compares the selected fact's `action`,
        `vm_name` (against `vm_target`), and `status`. `create_evidence` yields
        nothing on a mismatch, and `create_result` adds it to the detail as
        `mismatch`. A result with no fact names that instead.
      - **Fact-only fields.** The tenant account is the fact's `tenant_user`, and
        the forwarded port its `external_ssh_port` when that is a port. A relayed
        create prints a sentence there instead.
      - **Address.** The buyer-facing address stays the registry's (`public_host`,
        else `ssh_host`). The guest's port is the forwarded or relayed one, never
        the host's `public_port`.
      - **A defect found on the way.** `build_result_payload` replaced the
        forwarded port with the `frp` block's `remote_port` whenever that block
        was present. The buyer-key fact prints the block on the direct path too,
        disabled and with `remote_port: 'N/A'`, so a real buyer-key create on the
        direct path reported port `N/A` and yielded no evidence. Only an enabled
        relay's port now replaces the forwarded one. The section's red (below)
        shows it.
- [x] 5.3 `vm_mock_output` renders the shipped form for the job, from the job's
      stored parameters, as bare metal's does:
      - **A create.** The provided-key create fact, with:
        - `vm_name` set to the job's `vm_target`;
        - `tenant_user` derived from that name as the role derives it, by removing
          every non-alphanumeric character and lower-casing;
        - `status` `success` and a `timestamp` of the run;
        - a forwarded `external_ssh_port`, and no relay.
      - **A remove.** `vm_remove_data` naming the job's guest.

      The fixed `mock-vm` create, whose status is `running`, is removed.

      Done, in `services/mock_output.py`:
      - **A create.** The fact names the job's `vm_target` and its
        `tenant_account`, reports `success`, a timestamp, the forwarded port
        `2222`, and no relay.
      - **The key variant.** A job naming the buyer's key prints the role's
        provided-key fact, with its disabled `frp` block. A job naming none
        prints the generated-key fact, with the role's `relay` block. The mock
        credentials and their redaction are unchanged.
      - **A remove.** It prints `vm_remove_data` naming the job's guest.
      - **Other actions.** Each prints a minimal success fact under its own name,
        rather than the create output every action used to receive.
      - **The form.** `shipped_output` prints the YAML `var:` block, display only,
        and the `msg: |-` JSON copy.
- [x] 5.4 Drop `result_stdout` from the create rule in each of the five scenario
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

      Done. Each of the five rules is a typed `MockRuleCreate` and keeps its
      `rule_id`, `match`, and `pause_before_result`. `_CREATE_RESULT_STDOUT` and
      its comment are removed from `compute_deal_driver.py`, as are the four
      inline outputs and their comments. The search at section start found
      `vmuser` and the three fixed guest names only inside those outputs, and no
      assertion on them; after the edit it finds nothing.
- [x] 5.5 Unit tests:
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

      Done (unit):
      - **`tests/unit/test_vm_codec.py`**, now the VM adapter's:
        - the shipped form read from its `msg:` block;
        - the last document for the expected action taken;
        - a remove run never adopting a create document;
        - a summary block followed by a later document, adopting nothing;
        - a port and account printed outside the fact, not read;
        - a relayed create reporting no forwarded port;
        - a fact naming another guest, status, or action, and a result with no
          fact, each yielding no evidence with its `mismatch`;
        - a fact `host` other than the registry's, still yielding evidence at the
          registry's address;
        - a disabled relay block keeping the forwarded port.
      - **Fixtures.** Shipped-form fixtures come from a renderer kept in the test
        module, apart from the adapter's own, so a mistake in that renderer
        cannot hide one in the codec.
      - **Removed.** The regex-reader tests and the forward-fallback case went
        with the functions they tested.
      - **`tests/unit/test_vm_mock_output.py`** (new): the tenant account's
        derivation; the create in the shipped form, for the job's guest, in both
        key variants; its evidence through the real codec, credentials split out
        and absent from the result; the remove fact.

      **Red.** A private script ran the same cases through the codec and mock on
      `HEAD`, overlaid on the adapter's environment, and through the new ones:
      - Every case went red on `HEAD`'s code, each failing on behaviour, not on an
        import:
        - a remove run adopting a create document;
        - evidence from another guest's fact, and from a `running` one;
        - a port read from outside the fact;
        - the mock naming another guest;
        - the disabled relay block's `N/A` port.
      - All went green on the new code.
- [x] 5.6 Verification:
      - `make -C domains/vms/provisioning/adapter test` (unit);
      - `make -C provisioning/compute/service test` (unit and application
        integration, including the VM codec tests and the service's mock-profile
        cases that use `vm_mock_output`);

        Correction after merging `dev`: the VM codec tests now run in the
        adapter's suite above, not the service's. The service's suite still
        runs the mock-profile cases that use `vm_mock_output`.
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

      Done, under the owner's focused cadence (the plan's header):
      - **VM adapter:** `make -C domains/vms/provisioning/adapter test`, 262 passed
        (unit, and library integration in its `tests/integration`).
      - **Provisioning service, targeted.** One run of the integration modules that
        run VM jobs or consume `vm_mock_output`, plus the service's VM operations
        unit tests. 316 passed: application integration through the typed clients,
        with some direct-storage cases. The modules:
        - `test_bare_metal_mock_profile`, `test_capacity_api`,
          `test_capacity_definitions_api`, `test_compute_contract_api`;
        - `test_fulfillment_api`, `test_fulfillment_convergence*`;
        - `test_host_pool_moves_api`, `test_host_requirement_api`,
          `test_hosts_api`;
        - `test_leases_api`, `test_lease_release_api`;
        - `test_pool_seed_api`, `test_pools_api`;
        - `test_provisioning_client_endpoint_coverage`, `test_system_api`,
          `test_test_controller`, `test_test_router_mounting`, `test_vms_api`.

        The service's whole suite, as its `make` target runs it, is not re-run
        here: Round 1's root `make test`, after Section 6, covers it.
      - **e2e:** `make -C e2e-tests test-unit`, 172 passed. The five scenario modules
        import.
      - **Packaging:** `make lock` changed only the adapter's version, its floor on
        the Ansible kit, and the service's two floors on the adapter.
        `make check-packaging` passed.

      **Service fixtures.** The conftest's fixed `FAKE_CREATE_STDOUT` reported
      status `running` and named one guest, `agent-vm-01`. Under the linkage, a
      create naming another guest yields no evidence. Two tests failed on it, and
      each failure is the linkage working:
      - `test_vms_api.py`'s create result;
      - `test_fulfillment_api.py`'s live credentials, whose fulfillment's guest
        derives from its reservation.

      The fixture is now `fake_create_stdout(vm_name)`, reporting `success` as the
      role does. `FAKE_CREATE_STDOUT` keeps `agent-vm-01`, and the fulfillment
      test renders the output for `fulfillment_guest_name(capacity_reservation_id)`.

      **Packaging.**
      - `arkhai-vms-provisioning-adapter` goes from 0.15.0, `dev`'s, to 0.16.0, and
        its floor on the Ansible kit rises to `>=0.5.0`, for `read_fact`.
      - The provisioning service composes the adapter's codec and mock, so its
        `adapters` extra and dev group floors rise to `>=0.16.0`. The service is
        not bumped again.

      End-to-end:
      - The five VM-lane scenarios named above, `e2e_deal`, `e2e_deal_buyer_cli`,
        `e2e_listing_shapes`, `e2e_buy`, and `e2e_non_erc20_settlement`, now read
        each create through the per-job default and the `msg:` path.
      - Owed by validation: the pipeline's VM lane on this commit. No workflow
        that only a push triggers is owed.

## 6. Recover what `buy` recorded, and qualify the payments upgrade

Delivers D5 and the payments qualification in "Context". Files:
`domains/bare_metal/buyer/tests/test_cli_completion.py`, or a new test module beside
it.

- [x] 6.1 Test: `buy_bare_metal` writes a real run log under one temporary XDG state
      directory, with its module factories replaced:
      - `fresh_identity`, `registry_client`, and `payment_approval` for the write;
      - `recovery_identity` for the read.

      `_recovered_deal`, the path `access`, `result`, and `teardown` share, reads the
      log back under the same directory. It recovers the same publisher principals,
      publisher, and registry binding. The test fails if the producer's form changes
      without the consumer's.

      Done, as `test_a_deal_bought_is_recovered_from_the_run_log_buy_wrote` in a new
      `domains/bare_metal/buyer/tests/test_run_log_recovery.py`.
      - **What is replaced.** Only the four factories, on `cli`. The configuration
        is a file read by the real loader. The registry factory returns the
        registry client's own `ListingSummary`. The payment factory returns the
        payments kit's real `PaymentApproval` over its in-memory
        `FakePaymentsClient`, so the mandate check, approval, and receipt
        verification run for real.
      - **The seller.** `negotiate_with_seller` and the settlement and fulfillment
        transports are the command's own collaborators, not factories, and reach
        the seller over HTTP. So the seller is a fake served on loopback HTTP. It
        verifies each request's version 2 proof against the buyer's principal,
        accepts at round zero with an Agreement whose mandate the payments kit's
        seller stage derives, and signs each response as the listing's
        publisher. No imported name is replaced.
      - **The write.** `buy` runs through negotiation, approval, and settlement, and
        writes its run log under the temporary state directory.
      - **The read.** With `fresh_identity` now refusing, `_recovered_deal`
        resolves the recorded run through `recovery_identity`. It reads back:
        - the publisher principals `buy` recorded, equal to the listing's;
        - the publisher;
        - the registry URL and authority, which match the configuration;
        - the seller URL, listing, and negotiation.

        It refreshes the publisher from the registry once and records no
        refreshed trust. `market bare-metal access --run-id` then reads the
        fake seller's access answer through the same recovery.
      - **Level.** Unit, under `TESTING.md`'s command-module convention: the real
        commands, a temporary filesystem, and fakes at the registry, payments, and
        seller boundaries. It is not a live purchase, a real storefront, or
        delivery.
      - **No red.** It passed on its first run. The producer correction is on the
        branch's base, so this qualifies it and changes no behaviour (D5). A
        negative control was run once and not kept. It had `buy` record
        `publisher_principals` in the retired list form, and the test then failed
        at recovery with "malformed publisher_principals", the historical refusal.
      - **Fixtures.** Deterministic development keys, accounts, and a documentation
        address. Every one is marked as never for a public network.
- [x] 6.2 Qualify the payments upgrade with no code change:
      - run `make -C kit/arkhai-payments test`;
      - rebuild the bare-metal buyer environment through `make dist` and its
        `reinit`;
      - record in this section's notes that the kit verifies `livemode`, refuses a
        mismatched mode, and refuses unknown receipt fields.

      Done, with no code change.
      - **The rebuild.** `make dist` passed. `make -C domains/bare_metal/buyer test`
        runs `reinit` first, which reinstalled the lock's internal packages from
        the wheelhouse and left `uv.lock` unchanged. Afterwards the installed
        `arkhai-kit-arkhai-payments` 0.3.0 and `arkhai-core-buyer` 0.6.0 equal
        their source file for file, and so do their wheels. One `core_buyer`
        file had differed before the rebuild, in an environment built before
        `dev` was merged. The bare-metal buyer installs its own project editable.
      - **The kit's suite,** `make -C kit/arkhai-payments test`: 92 passed (unit).
        - **Signed `livemode`.** The published receipt vector carries
          `livemode`, and the fixture reproduces it byte for byte
          (`test_receipt_fixture.py`). `test_tampering_with_any_signed_field_breaks_the_signature`
          shows that the signature covers the receipt's fields.
        - **Mismatched mode.**
          - `test_a_receipt_from_the_other_mode_is_refused`;
          - the buyer's `test_an_approval_receipt_verifies_only_in_the_configured_mode`
            and `test_a_polled_receipt_is_verified_apart_from_the_approval_receipt`;
          - the seller's `test_a_receipt_verifies_only_in_the_configured_mode`.
        - **Unknown fields.** The generated `Receipt`, `SignedReceipt`, and
          `TransactionSnapshot` models forbid extra fields. No suite test isolates
          an unknown receipt field: `test_responses_outside_the_contract_are_protocol_errors`
          gives a response whose one field is unknown, but that response also
          lacks every required field.
      - **The captured receipt.** It was replayed once through the rebuilt buyer
        environment, locally and not kept, printing only outcomes. It parses, and
        its signature, transaction, deal, and test mode verify. A live-mode
        expectation, a flipped `livemode`, a tampered proof, another mandate, and
        an unknown extra field are each refused. The historical run log's retired
        list form is still refused, as D5 intends.
- [x] 6.3 Verification:
      - `make -C domains/bare_metal/buyer test` (unit);
      - `make -C kit/arkhai-payments test` (unit).

      No package changes, so there is no packaging step. End-to-end:
      `e2e_bare_metal_payment_deal` re-drives a recorded run.

      Done:
      - `make -C domains/bare_metal/buyer test`: 17 passed, 1 of them new (unit).
      - `make -C kit/arkhai-payments test`: 92 passed (unit).
      - Only a test module and these notes changed, so no version, pin, or lock
        moves. `make check-packaging` still ran before the section's checkpoint,
        as below.

      **End-to-end, corrected.**
      - `e2e_bare_metal_payment_deal` runs `market bare-metal buy` and reads its
        run log back with `read_run`. It re-drives settlement with the typed
        client's `settle_agreement`, and reads delivery through the fulfillment
        transport. It never runs `access`, `result`, or `teardown --run-id`, so it
        does not reach `_recovered_deal`. With no payments target configured,
        which is the repository's default, it reports a blocked skip.
      - `e2e_bare_metal_unbacked_introduction` does reach `_recovered_deal`, through
        `market bare-metal settlement contact introduce --run-id`. That is a run
        `request-introduction` wrote, which records the publisher as `buy` does.
      - `e2e_bare_metal_deal`, the real-host scenario no lane selects, calls
        `result` and `access` with `--from` and `--json`. The commands take
        `--run-id` and no `--json`, and refuse those options. This is left as it is:
        no lane runs it, and fixing it is outside this section. The live
        bare-metal lane uses `--run-id`.

        Correction: the Round 1 review's F3 was accepted, and Section 11 corrects
        the scenario before the live bare-metal lane runs (`design.md`, D14).
      - Owed by validation: none. No workflow that only a push triggers is owed.

      **Coverage classification correction.** The new case exercises the buyer
      command's orchestration and real run-log persistence across producer and
      consumer, so it is CLI component integration under the hierarchy's
      orchestration rule. Its seller and payments service remain fakes; it does
      not validate a real storefront's server contract or a live purchase. The
      buyer suite's 17 passes therefore include this integration case, rather
      than being 17 isolated unit cases.

      **Handoff.**
      - This section ran in a session of its own: the session that implemented
        Section 5 had grown too large to also hold this section's full reads.
      - Under the owner's cadence, Round 1's one full `make test` and one
        independent implementation review follow this section's commit.
      - `test_cli_completion.py` replaces imported names
        (`negotiate_with_seller`, `BUYER_STAGES`, the settlement transport, and the
        configuration loader), not only the module's factories, as
        `TESTING.md`'s command-module convention says. It was left as it is; the
        new module replaces only the four factories.

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

- [x] 7.1 Add the transition `failed` → `teardown_dispatch_pending`, and the constant
      `CREATE_COMPENSATION = "create_compensation"`.

      Done (unit), in `transitions.py`, with the constant beside the edge it
      accompanies and exported from the package. `db.py`'s state docstring now
      says `failed` is terminal but for that edge. `test_transitions.py` checks
      that `failed` reaches only `teardown_dispatch_pending`, and that `torn_down`
      and `abandoned` reach no state.
- [x] 7.2 Add `FulfillmentOrchestrator.begin_compensating_teardown(fulfillment_id,
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

      Done (unit and library integration), as the table states:
      - **Types.** `CompensationCandidate` is in `fulfillment.py`. It hands
        `authorize` a deep copy of the provider metadata, read-only at its top
        level, so nothing the callback does reaches the record.
        `CompensationRefusedError` is in `provider.py`. Both are exported from the
        package.
      - **One transaction.** The operation's first statement is a new
        transaction method, `get_by_fulfillment_id_for_write`. It reserves
        SQLite's writer slot and then reads the row, so `authorize`, preparation,
        and the write all judge one state.
      - **The write.** A new transaction method, `begin_compensating_teardown`,
        shares the ordinary teardown's write. It refuses a row that is not
        `failed`, and writes the prepared operation and `failure_reason` only, so
        `failure_message` is kept.
      - **Preparation is shared.** Both teardown entrypoints use one helper. It
        reuses a teardown operation already on the row, and otherwise asks the
        provider. A native `failed` row carries no prepared teardown, so for
        compensation the provider is asked.
      - **Unchanged.** `begin_fulfillment_teardown` takes no writer slot and still
        refuses `failed`.
- [x] 7.3 Tests:
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

      Done:
      - **Unit, `test_fulfillment.py`.** The orchestrator runs over the module's
        fake unit of work and a mocked provider. Each row of the table is covered:
        - not found;
        - the four begun-teardown states, adopted with nothing written;
        - `authorize` refusing;
        - `ProviderConfigInvalidError`, refused;
        - another preparation error, propagated;
        - the authorized write, which keeps the message;
        - the five other states, each a plain conflict, never a refusal.

        `authorize` receives one candidate with the record's fields, and the
        candidate's top level cannot be written. A callback that changes nested
        metadata leaves the record's metadata unchanged, whether it then refuses
        (nothing written) or authorizes (the provider prepares from the record's
        own metadata). Both cases fail against a shallow copy.
      - **Unit, `test_fulfillment_persistence.py`.** Over a mocked repository, the
        transaction's compensating write passes `failure_reason` and the prepared
        operation and no message. It refuses a row that is not `failed`.
      - **Library integration, new `tests/integration/test_compensating_teardown.py`.**
        Real file-backed SQLite, with independent sessions:
        - **Nothing written.** A refusal by `authorize`, a refusal by
          `ProviderConfigInvalidError`, and a propagated error each leave the row
          as convergence left it. A later compensation can still begin.
        - **A concurrent ordinary teardown.** The compensation is held after its
          write and before its commit. The ordinary request reads the committed
          `failed` row and refuses, writing nothing. After the commit, the same
          request adopts the compensation's view. One teardown was prepared, and
          the marker and message are kept.
        - **Two compensations.** The second runs on a connection that does not
          wait for the writer slot. It fails at the slot, before `authorize` or
          preparation runs. Once the first commits, a repeat adopts it.
          Removing the writer reservation fails this case.
        - **Diagnostics.** The teardown's progress is written through the
          repository's transitions, as convergence writes them. The counts move:
          - `failed` 1;
          - `teardown_dispatch_pending` 1;
          - `tearing_down` 1;
          - `teardown_failed` 1;
          - `tearing_down` 1;
          - nothing, at `torn_down`.

          The row ends `torn_down` carrying `create_compensation`. A repeated
          compensation adopts it.

      **Differences from the plan.**
      - **`torn_down` has no count.** `recovery_diagnostics` reports only the four
        recovery states and the two failure counts. A `torn_down` row is not
        counted anywhere, so "finally under `torn_down`" is asserted as the row
        leaving every count, with its state read from the record. No count was
        added. The delta's "ends counted as `torn_down`" says more than the
        diagnostics report.
      - **Correction: the design and the delta now say what the diagnostics
        report.** D4's "Readers" and the delta's convergence-worker paragraph said
        the row ends "under" or "counted as" `torn_down`. The existing projection
        has no `torn_down` entry, so both now say the row reaches a durable
        `torn_down` and leaves every recovery-state and failure count, never
        counted as failed. That is the contract tested above. No diagnostics field
        was added.
      - **`test_settlement_repository.py` is unchanged.** It sits in `unit/` and
        uses a real database. `TESTING.md` moves such a file to `integration/`
        when it is next touched, and this section needed no repository change.
        The real-database cases are in the new integration module instead.
      - **`test_import_boundaries.py`'s standard-library list gains `copy` and
        `types`.** `fulfillment.py` uses `copy.deepcopy` and `MappingProxyType`.
- [x] 7.4 Verification:
      - `make -C kit/fulfillment test` (unit and library integration);
      - `make check-packaging`.

      End-to-end: none. No pipeline scenario fails a create deliberately.

      Done:
      - `make -C kit/fulfillment test`: 200 passed (unit and library
        integration).
      - **Packaging.** `arkhai-kit-fulfillment` is 0.6.0. No dependant imports the
        new operation yet, so their `>=0.5.0` floors stay. `make lock` changed
        eight locks, each only in that version. `make check-packaging` passed,
        including `make check-architecture`.
      - **End-to-end.** None, as planned. Owed by validation: none.

      **Handoff.**
      - **Floors.** Section 8 is the first caller. It raises
        `compute_provisioning`'s floor on the kit to 0.6.0.
      - **The ordinary teardown takes no writer slot.** A concurrent ordinary
        request therefore judges the last committed state: it refuses `failed`
        while a compensation is uncommitted, and adopts it afterwards. Two
        ordinary requests on one `active` row are not serialized the same way.
        That is unchanged here.
      - **Reasons are compared exactly.** The kit writes `create_compensation`
        and never reads it. Convergence's teardown-failure write that keeps it is
        Section 8's (8.6).

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

**Correction after merging `dev`.** `resolve-compute-family-findings` landed first,
and this branch merged it before Section 5. In the files this section edits it changed:
- `TERMINAL_FAILURE_STATES`, which no longer holds `provisioning_failed`;
- `_TERMINAL_RESERVATION_STATES`, likewise;
- convergence's diagnostics line.

`_begin_recorded_teardown`, `_mark_release_failed`, the releasing pass, and
convergence's teardown-failure write are as this section's tasks describe them.

- [x] 8.1 Add `compensable(state, failure_reason, provider_metadata)` to
      `compute_provisioning.release`. It is true when the state is `failed`, the
      reason is `provider_reported_failure`, and the metadata parses as
      `JobFulfillmentMetadata` with `operation` `create`.

      Done (unit), as stated. A value that is not a mapping is not compensable.
      `PROVIDER_REPORTED_FAILURE` now lives beside the predicate, and
      convergence writes it from there, so the reason the predicate reads is
      the one convergence writes.
- [x] 8.2 `submit_release` calls `compensable` with the record's fields. It answers
      `TEARDOWN` for a compensable `failed` aggregate, and `UNRELEASABLE`
      (`fulfillment_failed`) for any other `failed` one.

      Done (library integration, `test_release.py`'s decision table).
- [x] 8.3 `FulfillmentServiceTeardownPort.begin_teardown` reads the current state:
      - for `failed`, it calls `begin_compensating_teardown` with
        `authorize=lambda candidate: compensable(candidate.state,
        candidate.failure_reason, candidate.provider_metadata)`;
      - for any other state, it calls `begin_fulfillment_teardown`.

      It translates `CompensationRefusedError` into `TeardownRefused`
      (`compensation_refused`), and passes every other error through.

      Done (library integration). `TeardownRefused` carries `reason` and
      `message`, and lives in `compute_provisioning.release`. The service's
      `DeferredFulfillmentTeardownPort` is what the composition wires, not
      `FulfillmentServiceTeardownPort`. It now delegates both of its calls to a
      `FulfillmentServiceTeardownPort` over its bound service, so the rule has
      one implementation.
- [x] 8.4 `FulfillmentReleaseStatusPort` reads the record through the repository and
      calls `compensable` with its fields. It answers by D4's state table, with
      `READY_FOR_TEARDOWN` for a compensable `failed` aggregate. The composition
      gives it the repository and the session factory the executor holds.

      Done (library integration). Its constructor now takes
      `settlement_repository` and `session_factory` as keywords, in place of the
      teardown port, which it no longer uses. Every test composition that built
      it was updated (8.7).
- [x] 8.5 When `begin_teardown` raises `TeardownRefused`, the lease lifecycle records
      `release_failed` with the refusal's reason and message, under the release
      handle, through the site's conditional write. `_mark_release_failed` gains an
      explicit expected-handle argument:
      - On the release path, `_begin_recorded_teardown` passes the decision's
        `fulfillment_id`, which `begin_release` has just recorded. Its reservation
        was read before that write, so it is not used without the handle.
      - In the releasing pass, the reservation read in that cycle supplies its
        recorded `release_job_id`, as today.

      Every other error stays transient, as today.

      Done (unit). `_mark_release_failed` takes `expected_handle` as a required
      keyword. The callers that act on a reservation as they read it pass
      `_handle_read(reservation)`, which is the old derivation; the release
      path's refusal passes the decision's `fulfillment_id`.
      `_begin_recorded_teardown` now returns the lease's resulting state, so a
      termination refused this way answers `release_failed`. In the releasing
      pass, an error other than a refusal still propagates to the cycle's
      handler, which logs it and counts the lease as skipped.
- [x] 8.6 Convergence's teardown-failure write keeps a `create_compensation` reason
      and replaces only `failure_message`. For every other aggregate it writes
      `provider_reported_failure`, as today.

      Done (library integration), in `_apply_teardown_failure`. The reason is
      read inside the owned write transaction, not from the claimed row.
- [x] 8.7 Update the tests that pin the old behaviour. The design found the set
      below; re-list it at section start:
      - `provisioning/compute/tests/integration/test_release.py`
      - `provisioning/compute/service/tests/unit/services/test_ledger_lease_lifecycle.py`
      - `provisioning/compute/service/tests/integration/test_lease_release_api.py`
      - `provisioning/compute/service/tests/integration/test_compute_contract_api.py`

      Re-listed at section start:
      - **`test_release.py`.** The status port's constructor changed. The
        decision table gains a compensable `failed` row, which answers
        `TEARDOWN`.
      - **`test_lease_release_api.py`.** Its failed-grant case set `failed` with
        no reason, a row convergence never writes. It is replaced by the
        ineligible cases in 8.9. The status port's constructor changed.
      - **`test_ledger_lease_lifecycle.py`, the service's integration
        `conftest.py`, and `test_legacy_backfill_teardown.py`.** Only the status
        port's constructor changed. The first's `failed` row has no reason, so
        it still pins the ineligible path.
      - **`test_compute_contract_api.py` is unchanged.** Its ordinary teardown of
        a `failed` aggregate still answers 409, as the design keeps it.
- [x] 8.8 Unit and library integration tests:
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

      Done:
      - **Unit, new `provisioning/compute/tests/unit/test_compensable.py`.**
        `compensable` over:
        - the eligible row;
        - the states other than `failed`;
        - quarantined, `invalid_provisioned_resource_metadata`,
          `create_compensation`, and no reason;
        - metadata that is none, empty, not a mapping, missing its host, create
          job, or target, a teardown's, another provider's, or carrying an
          unknown field.
      - **Library integration, `test_release.py`.**
        - The status port answers every state in D4's table, and a handle that
          names no fulfillment.
        - The teardown port is driven against the real orchestrator and a real
          SQLite database, with only the provider faked:
          - `active` begins the ordinary teardown;
          - a begun teardown is adopted;
          - a compensable `failed` row is compensated once over two calls;
          - quarantined, no metadata, and `ProviderConfigInvalidError` are
            refused, writing nothing;
          - a connection error propagates and is not a refusal.
        - The state changes between the port's read and the kit's transaction:
          - another release compensates first, and the port adopts it;
          - the create fails after the port read `dispatching`. The ordinary
            teardown refuses with a conflict, not a refusal, and the status then
            reads ready.
      - **Unit, `provisioning/compute/tests/unit/test_lease_lifecycle.py`.**
        - A refusal on the release path is recorded under the decision's
          handle. The reservation was read `leased`, so it had none.
        - A refusal under a handle another release has since replaced is
          refused by the site, and that release is left as it is. Passing the
          read reservation's handle instead fails this case.
        - The releasing pass records a refusal.
        - A transient failure there leaves the lease `releasing`.
      - **Library integration, `test_fulfillment_convergence.py`.**
        - A compensating teardown that fails keeps `create_compensation`, and its
          message becomes the teardown's detail. After the requeue and a later
          success, it is still marked.
        - An `active` teardown that fails and then succeeds never carries the
          marker.
        - Writing `provider_reported_failure` unconditionally fails the first
          case.
- [x] 8.9 Application integration, through the typed clients under the mock profile:
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

      Done, through the typed clients. Convergence is stepped with its pause and
      advance controls, and the lease watchdog with `check_leases`.
      - **Bare metal** (`test_lease_release_api.py`):
        - **No evidence.** A mock rule prints a grant naming another tenant, so
          the grant carries no delivery evidence, and convergence fails it as
          `provider_reported_failure`. Terminating the lease then:
          - makes the lease `releasing`, under the fulfillment;
          - begins the compensation, which keeps the create's message;
          - dispatches one reclaim job, and a repeated termination adds none;
          - holds capacity after the reclaim succeeds and before convergence
            records `torn_down`;
          - releases the lease once, and a later cycle releases nothing.
        - **Create in flight.** A grant held at a gate, then failed, is
          compensated by the releasing pass.
        - **Ineligible rows.** Four of them: quarantined,
          `invalid_provisioned_resource_metadata`, no metadata, and another
          provider's metadata. Each leaves the lease `release_failed`
          (`fulfillment_failed`), runs no teardown job, and holds capacity.
        - **Refused compensation.** With the create job's row deleted, the lease
          is `release_failed` (`compensation_refused`) under the fulfillment it
          entered `releasing` with. The aggregate stays `failed`, nothing is
          prepared, and capacity is held.
        - **A failing compensation.** A reclaim rule's failure leaves the
          aggregate `teardown_failed` with `create_compensation`, and the lease
          `release_failed` with capacity held.
        - **Delivered teardown.** A delivered grant's reclaim fails, and
          convergence records `provider_reported_failure`. A failed teardown job
          is not re-run (D6), so its later success is set as convergence would
          leave it. The operator's retry-release then releases the lease, and
          the aggregate never carries the marker.
      - **VM** (`test_fulfillment_api.py`, the relay-backed class):
        - The module runs VM jobs through its `fake_ansible` runner, not the
          mock rule set, so the test states the create and removal outputs on
          that runner.
        - The create prints another guest, so it carries no evidence.
          Convergence fails it, and the termination compensates it.
        - The removal runs, and the aggregate reaches `torn_down` with the
          marker. The relay port stays leased until the lease's release returns
          it with the capacity.
- [x] 8.10 Verification:
      - `make -C provisioning/compute test` (unit and library integration);
      - `make -C provisioning/compute/service test` (application integration);
      - `make check-packaging`.

      End-to-end: no pipeline scenario fails a create deliberately, and none is
      added. The application integration cases are the lowest level that proves the
      lifecycle. The live bare-metal lane's supported teardown is the system
      evidence.

      Done:
      - `make -C provisioning/compute test`: 280 passed (unit and library
        integration).
      - `make -C provisioning/compute/service test`: 607 unit and 476
        application integration passed.
      - **Packaging.**
        - `arkhai-compute-provisioning` is 0.22.0, with its floor on
          `arkhai-kit-fulfillment` raised to 0.6.0.
        - The service is already 0.20.0 in this change, so it is not bumped
          again. Its floors rise to `arkhai-kit-fulfillment>=0.6.0` and
          `arkhai-compute-provisioning>=0.22.0`.
        - The Ansible kit and the two adapters keep their floors, since none
          uses the new API.
        - `make dist` and `make lock` changed five locks: compute, Ansible, the
          service, and both adapters. Each changed only in that version and those
          floors.
        - `make check-packaging` passed, including `make check-architecture`.
      - **End-to-end.** None. Owed by validation: none.
      - **Coordination.** `resolve-compute-family-findings` landed first, as the
        correction above records. This section changes neither
        `TERMINAL_FAILURE_STATES` nor `_TERMINAL_RESERVATION_STATES`.

      **Handoff.**
      - **Retry-release reuses the release path's handling.** An operator's
        retry-release of a `release_failed` lease runs `_request_release`. A
        compensable aggregate begins its compensation there, and a refusal
        returns the lease to `release_failed` under the new handle.
      - **A failed create is no longer reported `fulfillment_failed`.** The
        bare-metal mock profile's failed grants are compensable now. A test
        that terminates such a lease and expects `fulfillment_failed` must make
        the row ineligible.
      - **Section 10 is next on this path.** Bare metal's reclaim of an account
        its grant never created is what makes the compensation safe on a real
        host. Here, the mock's reclaim succeeds.

## 9. A VM storefront reads a compensating fulfillment as a failed delivery

Delivers D4's VM storefront reader ("Readers"), for the `physical-provisioning` delta
requirement "An undelivered lease is released by what its fulfillment proves". Files:
- `domains/vms/storefront/src/market_storefront/services/fulfillment_resume_runtime.py`
- `domains/vms/storefront/tests/unit/test_fulfillment_resume_runtime.py`
- `domains/vms/storefront/tests/unit/test_failure_policy.py`, for the failure actions
  in `domains/vms/storefront/src/market_storefront/failure_actions.py`

- [x] 9.1 The fulfillment resume treats a `create_compensation` reason, in any state,
      as a failed delivery, as it treats `failed`.

      Done (unit), in `_load_active_physical_result`. A status whose state is
      `failed`, or whose `failure_reason` is the kit's `CREATE_COMPENSATION`, is a
      failed delivery: the delivery is recorded `failed` in phase `physical_failed`
      with the status's message, and the pass runs the accepted entry's failure
      policy with the reason `provisioning_failed`, exactly as for `failed`. The
      constant is imported from `market_fulfillment`, which the module already
      imports. The unit fakes of the status gained `failure_reason=None`, since
      the real `FulfillmentStatusResponse` always carries the field.

      **Left as it is: the foreground poll.** `fulfillment_service.py`'s
      `_poll_fulfillment_until_terminal` stops only at `active` or `failed`, and its
      docstring says the teardown states cannot appear there. D4 names only the
      resume reader. A compensation begins only on a lease's release, so the poll
      meets a teardown state only if a release lands between two of its polls after
      the create failed. It then times out after `provisioning.timeout`, a bounded
      wait, and the resume loop reads the delivery as failed. This is recorded for
      review, not changed here.
- [x] 9.2 Unit tests:
      - an aggregate in `teardown_dispatch_pending`, `tearing_down`,
        `teardown_failed`, or `torn_down` carrying `create_compensation` is a failed
        delivery;
      - a delivered aggregate's `torn_down`, carrying another reason, is not;
      - the failure actions' capacity release is still refused by the guarded site
        release until the aggregate is `torn_down`.

      Done (unit):
      - **`test_fulfillment_resume_runtime.py`.** One resume pass over a delivery
        whose fulfillment is known, reading a real `FulfillmentStatusResponse`:
        - in each of the four teardown states with `create_compensation`, the
          delivery is recorded `failed` and the failure policy runs once with the
          reservation and the status's message; no result is read and nothing is
          begun;
        - `torn_down` with no reason or `provider_reported_failure`,
          `teardown_failed` with `provider_reported_failure`, and `tearing_down`
          with none are not failed deliveries: the pass waits, and no policy runs.
      - **Red.** Against `HEAD`'s reader the four compensating cases failed and the
        other sixteen in the two modules passed. Treating any non-null reason as a
        failure fails the two `provider_reported_failure` cases, so the marker, not
        a reason, decides.
      - **`test_failure_policy.py`.** The failure actions' release over the fake
        site's transport. While the site's guard refuses, as provisioning's does
        for a compensating aggregate until `torn_down` (the fake models it as a
        release answering no reservation), the action reports nothing released,
        the reservation stays `reserved`, its capacity stays held, and no listing
        reopens. Once the guard permits, the same action releases it. This passed
        before and after the change: D4 says the failure actions need no change,
        and this pins it. Provisioning's own guard is Section 8's evidence.
      - **Seams.** The new case replaces the module's
        `capacity_binding_for_listing` and its configured-actions source, as the
        module's existing release case does. That patches module names, which
        `TESTING.md` discourages; it was kept to match the module's seam rather
        than restructure the policy. The `SQLiteClient` it constructs is not read
        on this path.
- [x] 9.3 Verification:
      - `make -C domains/vms/storefront test` (unit and application integration);
      - `make check-packaging`.

      End-to-end: none. No pipeline scenario fails a create deliberately.

      Done:
      - `make -C domains/vms/storefront test`: exit 0, after `reinit`. Unit 1158
        passed and 1 skipped; integration 476 passed. Both folders mix levels:
        `tests/unit` holds cases over real SQLite, and `tests/integration` holds
        application cases through the typed client beside direct-storage ones.
      - **Packaging.** `arkhai-vms-storefront` goes from 0.23.1, `dev`'s, to
        0.24.0, its one bump in this change, under this plan's minor-bump rule.
        Its floor on `arkhai-kit-fulfillment` rises to `>=0.6.0`, for
        `CREATE_COMPENSATION`. `make dist` and `make lock` changed two locks, the
        storefront's and `e2e-tests`', each only in that version and floor. No
        exact pin of the storefront exists.
      - `make check-packaging`: passed, the architecture rules included.
        `make check-change`, `make check-tasks`, and `make check-comment-hygiene`:
        passed.
      - **The wheel.** The 0.24.0 wheel's 85 package files equal their source.
      - **End-to-end, confirmed.** No VM-lane scenario fails a create, so none
        reaches this reader's new branch. Owed by validation: none.

      **Handoff.**
      - The section's fresh-context compliance check was not run: the owner's
        cadence for this phase runs no subagent or reviewer, and the round's one
        independent review covers it.
      - Section 10 is next: the bare-metal reclaim of an account never created.

## 10. A bare-metal reclaim of an account that was never created succeeds

Delivers D4's domain safety for bare metal, for the delta requirement "A bare-metal
reclaim tolerates an account its grant never created". Files:
- `domains/bare_metal/provisioning/iac/ansible/roles/bare-metal-access/tasks/main.yml`
- `domains/bare_metal/provisioning/adapter/tests/test_bare_metal_codec.py` (the
  role-variable test class)

- [x] 10.1 Before key removal or locking, the reclaim checks whether the tenant
      account exists. When it does not:
      - it skips key removal and locking;
      - it reports `account_present: false` in its fact;
      - it creates nothing.

      An existing account is handled as today, under each policy.

      Done, in the role's `main.yml`:
      - **The lookup.** A reclaim first runs `getent passwd <account>` on the
        target, as an argv command with no shell and no `become`. It changes
        nothing (`changed_when: false`), and fails the reclaim on any exit but 0
        (found) and 2 (no such name). A `set_fact` records
        `bare_metal_account_present` from it.
      - **The gate.** All four tasks that touch the account are skipped when it is
        absent: key revocation, the key-only `authorized_keys` removal, the lock,
        and the delete. The lock's `user: state: present` is the one that would
        have created the account. Each task's other conditions, and so each
        policy's handling of a present account, are unchanged.
      - **The fact.** The reclaim fact gains `account_present`, beside
        `account_locked` and `account_deleted`.
      - **Beyond the plan's files: the mock.** D2 has the mock print what the role
        prints. The adapter's default reclaim output now prints `account_present`
        as `"true"`, since a default reclaim stands for a delivered grant's. A case
        needing an absent account arms a rule. The adapter is already 0.12.0 in
        this change, so it is not bumped again.

        Correction (14.10): the role prints `account_present` as a boolean, and
        the mock now does too.
- [x] 10.2 Tests:
      - role-structure unit tests that the existence check precedes every task
        reading the account, and that the reclaim fact carries `account_present`;
      - `ansible-playbook --syntax-check` on the access playbook;
      - the codec's reclaim interpretation accepts the new field.

      Owed outside this section: running the role against a host that lacks the
      account is the live lane's evidence. No repository suite runs a playbook
      against a host.

      Done:
      - **Role structure (unit), `TestReclaimOfAnAbsentAccount`** in
        `test_bare_metal_codec.py`, beside the role-variable class. It splits the
        role into its top-level tasks and checks:
        - the lookup runs `getent passwd` on the account, changes nothing, takes no
          `become`, runs on the target, and fails on any exit but 0 and 2;
        - the four reclaim tasks that use `authorized_key`, `file`, or `user` all
          follow the lookup and are gated on its result;
        - the lock, which states `present`, is gated;
        - the presence is recorded after the lookup and before any of those
          tasks;
        - the reclaim fact carries `account_present`.

        Red: against `HEAD`'s role the five fail and the module's other 42 pass.
        Green: 47.
      - **The codec (unit).** A reclaim fact with `account_present`,
        `account_locked`, and `account_deleted` all `false`, as the role prints
        its booleans, is the result unchanged, in the shipped and JSON forms and
        under each policy. The codec did not change, so this passed before too.
      - **The mock (unit).** The default reclaim reports `account_present`.
      - **`--syntax-check`.** `ansible-playbook --syntax-check` on
        `playbooks/node-access.yaml` passed on ansible-core 2.19.14 under the
        packaged `ansible.cfg`, run once from an isolated tool environment outside
        the repository, and on the workstation's ansible 2.10.8. Neither is a
        repository suite: no target in the repository runs this playbook's syntax
        check, and the adapter's environment has no Ansible.
      - **A local run, outside the repository and not kept.** The new role was run
        on ansible-core 2.19.14 under the packaged configuration, against the
        local machine over a local connection, for a synthetic account confirmed
        absent before and after. Under each of the three policies it exited 0,
        printed `account_present`, `account_locked`, and `account_deleted` as
        `false`, and created no account. The adapter's codec read each printed
        fact as linked, with no mismatch. `HEAD`'s role, run the same way under
        the default policy with `become` disabled, failed at the key task with
        "Failed to lookup user", the historical failure. A present account was
        not exercised locally, since that would change this machine. This is
        corroboration, not a host-lane result.
- [x] 10.3 Verification:
      - `make -C domains/bare_metal/provisioning/adapter test` (unit);
      - `make check-packaging`.

      End-to-end: the bare-metal mock lane runs no playbook. The live bare-metal
      lane is the system evidence.

      Done:
      - `make -C domains/bare_metal/provisioning/adapter test`: 88 passed (unit).
      - **The changed mock's consumers.** After `make dist` and the service's
        `reinit`, `test_bare_metal_mock_profile.py` and
        `test_lease_release_api.py` passed 23 (application integration through
        the typed clients under the mock profile, with direct-storage setup in
        the second). The service's whole suite was not re-run: only the mock's
        reclaim fact gained a field, which nothing reads.
      - **Packaging.** No version changed: the adapter is already bumped once in
        this change, and the role ships in no Python package. `make lock` changed
        nothing. `make check-packaging`, `make check-change`, `make check-tasks`,
        and `make check-comment-hygiene`: passed.
      - **End-to-end, confirmed.** `e2e_bare_metal_mock_deal` and
        `e2e_bare_metal_payment_deal` read the mock's default reclaim, which now
        prints `account_present`; nothing asserts on it. No lane runs the role.
        Owed by validation: none.

      **Handoff.**
      - The section's fresh-context compliance check was not run, as in Section 9.
      - Round 2's implementation sections are complete. The live bare-metal lane
        still owes a real reclaim of an account a failed grant never created, and
        one of a present account under the configured policy.

        Correction after the scope revision: Round 2 also includes Sections 11 to
        14, so its candidate freezes after Section 14, not after this section.

## 11. The real-host bare-metal scenario drives the buyer commands as they ship

**Replanned against the scope revision of 2026-10-29** (`design.md`, "Scope revision").
Sections 11 to 14 below replace the plan's earlier Sections 11 to 13, none of whose tasks
had been started:
- the earlier Section 11, "A compute shape need not state a GPU", and Section 12, "The
  VM storefront publishes, prices, and claims a stated CPU-only shape", are withdrawn
  with D7, their slice `gpu-optional-compute-shapes`'s again;
- the earlier Section 13, "An aarch64 guest, and a teardown that removes only its own
  guest", is split: its `aarch64` recipe is withdrawn, its x86-64 image pin becomes
  Section 12 (D11), and its teardown repairs Section 13 (D9), unchanged in substance.

Sections 11 to 14 join Sections 7 to 10 in Round 2, one preflight round whose candidate
freezes after Section 14. The closeout, formerly Section 14, is Section 15.

Delivers D14, the Round 1 review's F3 (`reviews/03-implementation-external.md`), as
test code only, before the live bare-metal lane runs. Files:
- `e2e-tests/tests/e2e/roles/scenarios/bare_metal/test_bare_metal_deal.py`
- a helper the scenario calls for its commands, teardown wait, and SSH, in
  `e2e-tests/tests/e2e/roles/helpers/`, so the unit suite can test them without
  collecting the scenario
- `e2e-tests/tests/e2e/roles/buyer_cli.py` (`BuyerCli._resolve_run_id_from_args`)
- a new unit module in `e2e-tests/tests/unit/`
- `e2e-tests/tests/e2e/roles/README.md`, whose paragraph on the scenario's inputs gains
  the pinned known-hosts file

- [x] 11.1 The scenario runs `market bare-metal result`, `access`, and `teardown`, each
      with `--run-id <id>`, the id `buy` printed, and reads each command's JSON
      output, which needs no flag. No `--from`, no `--json`, and no `teardown request`
      or `teardown status` remain. Each argument list is built by one helper function
      per command, so the unit tests read exactly what the scenario runs. The run-id
      resolver recognizes `--run-id <id>`, `--run-id=<id>`, and `--from=<id>`, beside
      the forms it reads today.

      Done, as test code:
      - **The helper.** `e2e-tests/tests/e2e/roles/helpers/bare_metal_access.py`
        holds `recovery_command(command, run_id)`, which builds `("bare-metal",
        <command>, "--run-id", <id>)` for `result`, `access`, and `teardown` alone,
        and the teardown wait and SSH helpers below. The scenario reads each
        command's JSON through its existing `_json_result`.
      - **The run.** The scenario takes the run from `buy`'s own run log
        (`MarketRun.run_id`) and asserts that `buy` printed the same `run_id`.
      - **The resolver.** `run_id_from_args` in `buyer_cli.py`, which
        `BuyerCli._resolve_run_id_from_args` now calls, reads `--from`, `--run`,
        `--run-id`, and `-r` followed by a value, and `--from=`, `--run=`, and
        `--run-id=` with one. An option with no value binds nothing.
      - **Found on the way: the purchase's events.** The scenario expected `buy`'s
        log to hold `discover`, `negotiation_completed`, and `settlement_submitted`
        or `settlement_started`, which `buy` never writes; those come from other
        commands. A real `buy`, run through the bare-metal buyer's run-log test,
        records `run_started`, `agreement_accepted`, `payment_approved`, and
        `run_ended`, ending `agreed`. The scenario now checks that sequence and
        status through `assert_purchase_recorded`, and the buyer's test pins the
        same sequence on the producer's side (11.4).
      - **The skip message** for `BARE_METAL.BUY_ARGS` names what `buy` takes: the
        listing, `--option-id`, `--ssh-public-key`, and `--duration-seconds`. It
        named output flags `buy` has never had.
- [x] 11.2 Teardown repeats `teardown --run-id` and reads its `state`:
      - `released` ends the wait in success;
      - `teardown_failed` fails at once, naming the state and its `failure_reason`;
      - any other state continues, at `POLL_INTERVAL_SECONDS`, until
        `TEARDOWN_TIMEOUT_SECONDS`, after which it fails naming the last state.

      The command's own errors fail the scenario as they do today. The
      `TERMINAL_TEARDOWN_STATUS` setting is removed. The wait is one function taking
      the command runner and a clock, so its unit test needs no sleep.

      Done: `wait_for_release(teardown, *, timeout_seconds, poll_interval_seconds,
      clock, sleep)`. Its first call is the request and the rest observe it, since
      the command is one idempotent route (`fulfillment_service.teardown`, which
      ends the lease once and otherwise answers `status`). The scenario passes it
      `recover("teardown")` and the two existing settings; no
      `TERMINAL_TEARDOWN_STATUS` remains, and nothing in `settings.toml` named it.
- [x] 11.3 Every access attempt is a fresh SSH process:
      - `-F none`, `ControlMaster=no`, and `ControlPath=none`;
      - `BatchMode=yes`, `IdentitiesOnly=yes`, `IdentityAgent=none`,
        `PreferredAuthentications=publickey`, `PasswordAuthentication=no`, and
        `KbdInteractiveAuthentication=no`, with the role's key;
      - `StrictHostKeyChecking=yes` against a known-hosts file named by a new role
        input, `ARKHAI_E2E_BARE_METAL_KNOWN_HOSTS_FILE`, checked before any market
        effect; the scenario skips without it, as it does without the key.

      One classifier reads each attempt: success is exit 0 with the expected output;
      revoked is exit 255 with "Permission denied" for the public key; anything else
      is an error, and the scenario fails rather than counting it as revocation.

      Done: `ssh_command` and `classify_ssh`, with every option above and also
      `ConnectTimeout=10`, `GlobalKnownHostsFile=/dev/null`, so no system-wide
      known host is trusted, and `UpdateHostKeys=no`, so an attempt never rewrites
      the pin. The local OpenSSH 8.9 accepted every option in a dry `ssh -G`,
      which connects to nothing. `StrictHostKeyChecking=accept-new` is gone. The
      new `bare_metal_known_hosts` fixture skips without the input; the scenario
      no longer writes a known-hosts file of its own. The first attempt must be
      accepted, and the one after teardown refused.
- [x] 11.4 Unit tests, in `e2e-tests/tests/unit/`:
      - each command's argument list parses under the installed bare-metal buyer's
        own Typer command, resolved to its subcommand and parsed without running it,
        and the earlier `--from`, `--json`, and `teardown request` forms are refused
        by the same parser;
      - the run-id resolver, for `--run-id <id>`, `--run-id=<id>`, `--from <id>`,
        `--from=<id>`, and no run;
      - the teardown wait over scripted answers: `terminating`, then a teardown
        state, then `released`; `teardown_failed`; and a timeout;
      - the SSH argument list carries every option above, and the classifier on an
        exit 0 with and without the marker, an exit 255 refusal, and a refused
        connection, a timeout, a host-key mismatch, and an unreachable host, none of
        which is revocation.

      Their level is unit: the scenario's own helpers and the installed command's
      parser, with no stack, network, or purchase.

      Done, in a new `tests/unit/test_bare_metal_deal_commands.py`, 35 cases:
      - **The parser.** The installed `market.buyer_domains` entry point
        `bare-metal` is loaded, registered on a fresh Typer root as the `market`
        command registers it, and each argument list is parsed down to its leaf
        command with `make_context`, running nothing. Each recovery command parses
        with its `run_id`. The scenario's earlier forms — `--from` with `--json`,
        `teardown request`, `teardown status`, and `--json` alone — are each
        refused by the same parser, so a regression fails here.
      - **The resolver**, seven cases, and the run binding: a `MarketRun` built
        over a temporary run directory takes `buy`'s one new log, and a recovery
        bound by `--run-id` keeps that run though another log appears beside it.
      - **The teardown wait**, over scripted answers and a fake clock:
        `terminating` through `released` in four calls, three two-second waits;
        `teardown_failed` failing on its second call, naming the reason; and a
        bound of six seconds failing with the last state.
      - **SSH.** The argument list carries every option and no `accept-new`, and an
        access view without its route is refused. Exit 0 with the probe output is
        accepted, without it is an error. Exit 255 with "Permission denied
        (publickey)" is refused; a refused connection, a timeout, no route, an
        unknown or changed host key, and an unresolved name are each an error.
      - **The purchase's events.** `BUY_EVENTS` and `assert_purchase_recorded`
        accept the sequence a real `buy` writes, and refuse one with no approval,
        one ending `exited`, another command's events, and one out of order.
      - **The producer's side (test only, beyond the plan's file list).** The
        bare-metal buyer's `test_run_log_recovery.py` now asserts the events its
        real `buy` recorded are exactly that sequence, ending `agreed`. Its
        command, persistence, and fakes are unchanged (Section 6).

      **Red.** `HEAD`'s resolver body, run on the new cases, returned no run for
      `--run-id <id>`, `--run-id=<id>`, and `--from=<id>`; `--from <id>` still
      resolved. The refused-form cases are the scenario's own earlier argument
      lists, which the installed parser rejects. The old event expectations are
      the "another command's events" case. The new helper did not exist before,
      so its own cases have no behavioural red.

      Fixtures are a documentation address, a synthetic tenant, a zeroed run id,
      and placeholder key paths, marked as fixture values only.
- [x] 11.5 Verification:
      - `make -C e2e-tests test-unit` (unit);
      - `make check-packaging`.

      End-to-end: none. `e2e_bare_metal_deal` is in no lane and is not run here. It
      runs only in an authorized live run on Round 2's validated candidate, as the
      live bare-metal lane's scripted path (`design.md`, "Live qualification"). No
      package version changes: `e2e-tests` is a tooling project. Owed by
      validation: none.

      Done:
      - `make -C e2e-tests test-unit`: exit 0, 208 passed (unit), 35 of them new.
      - `make -C domains/bare_metal/buyer test`: exit 0, 17 passed, the run-log
        case among them (CLI component integration, as Section 6 classified it).
      - The scenario module compiles and collects one test; it was not run.
      - `make check-packaging`: exit 0, the architecture rules included.
        `make check-change`, `make check-tasks`, and `make check-comment-hygiene`:
        passed.
      - **No production file changed**, so no version, floor, or lock moved.

      **Handoff.**
      - The section's fresh-context compliance check was not run: this phase runs
        no subagent or reviewer, and the round's one independent review covers it.
      - **Not proven here:** that a real storefront answers each lifecycle state
        as the wait expects, that a real host refuses a revoked key with that
        message, and the run against a real host. Those are the live bare-metal
        lane's, on Round 2's validated candidate.
      - Sections 12 to 14, the VM recipe, are next, in a fresh session. Round 2
        freezes after Section 14.

      Correction (14.11): the scenario paragraph of `e2e-tests/tests/e2e/roles/README.md`
      that 11's file list names was rewritten, and the paragraph after it still
      described the old teardown and revocation; the two are folded into one.

## 12. An x86-64 guest is created from a pinned, verified image

Delivers D11, for the delta requirement "A VM guest is created from a pinned, verified
image". Files:
- `domains/vms/provisioning/iac/ansible/roles/vm-management/tasks/vm-create.yml` (the
  scratch image tasks)
- the role's `vars/main.yml`, new, for the pin
- a new role test module in `domains/vms/provisioning/iac/tests/`

- [x] 12.1 The scratch image is one dated release of the Ubuntu Noble x86-64 cloud
      image:
      - the pin, the release's dated URL and the SHA-256 its published checksum list
        gives for the image, is in the role's `vars/main.yml`. Record in this
        section's notes which release was pinned and that its signed checksum list
        was verified when the digest was taken;
      - the image is stored under a name carrying the release;
      - its SHA-256 is verified before it backs any disk, after a download and when
        the file is already on the host, and a mismatch fails the create before any
        disk or domain is defined;
      - before any host effect, the create reads the target's machine architecture
        and fails, naming it, on any other than `x86_64`.

      Golden images are unchanged.

      Done:
      - **The pin.** Release `20261017`:
        `https://cloud-images.ubuntu.com/noble/20261017/noble-server-cloudimg-amd64.img`,
        SHA-256 `04e8f2461a16a44e78a370284471f29616cdd9baf1893df25807b71f985b6c94`,
        621284352 bytes. When the digest was taken, that release's `SHA256SUMS`
        was checked against its `SHA256SUMS.gpg` with `gpgv` and the Ubuntu cloud
        image keyring (`ubuntu-cloudimage-keyring.gpg`). The result was a good
        signature from the UEC Image Automatic Signing Key, and the list gives
        that digest for the image.
      - **`vars/main.yml`** (new) states the release once. The URL and the stored
        path, `/var/lib/libvirt/images/noble-server-cloudimg-amd64-20261017.img`,
        are templated from it, beside the digest and the one pinned architecture,
        `x86_64`. Its comment says how an operator moves the pin. Role variables
        outrank inventory and play variables; only extra variables, which a pool's
        operator-owned `extra_vars` are, override them.
      - **The image tasks** in `vm-create.yml`:
        - `stat` the pinned path, without a checksum;
        - only when the path is absent, `get_url` the pinned URL to it, with
          `checksum: sha256:<pin>` and `libvirt-qemu:kvm` `0644`. Two facts were
          read in ansible-core 2.19.14's `get_url`: it checks a download's
          digest before moving it into place, so a bad download never reaches
          the path, and it re-downloads over an existing file whose digest
          differs, which is why it runs only on absence;
        - a shell step, "Verify the pinned scratch image before it backs any
          disk", directly before `qemu-img create`, on both paths. It runs
          `sha256sum` on the path and fails, naming both digests, on a mismatch
          or a missing file. It leaves the file as it is;
        - `qemu-img create -b` names the pinned path.

        The `/tmp` download, the `mv`, and the separate ownership task are gone.
        No task names the unversioned `noble-server-cloudimg-amd64.img` or a
        `current` URL. A file under the old name is therefore never used, and is
        not removed either.
      - **The architecture check is in `prerequisites.yml`**, outside the plan's
        file list. The prerequisites run before the create's own tasks, and their
        "Ensure libvirtd is running" starts and enables a service. Only there can
        the check precede every host effect. The check is a shell step with
        `changed_when: false`, for a scratch create alone. It reads `uname -m`
        and fails, naming the architecture (`unknown` when unreadable), on any
        other than the pinned one.
      - Golden creates are unchanged. Nothing else about the guest changed.
- [x] 12.2 Tests:
      - **Role structure (unit):** the URL is dated and never `current`; the
        checksum is stated; verification precedes the `qemu-img create` that uses
        the image as a backing file, on both the download and the existing-file
        paths; the architecture check precedes the create's first task that changes
        the host.
      - **Behaviour (unit, through `shell_harness`):** wherever the verification or
        the architecture check is a shell step, it is run with its commands faked: a
        matching and a mismatching digest, and `x86_64` and another architecture.
      - `make -C domains/vms/provisioning/iac validate-playbooks`, the playbooks'
        `--syntax-check`, with the Ansible version recorded.

      Owed outside this section: a real download and a real guest boot are the live
      VM lane's evidence.

      Done, in a new `domains/vms/provisioning/iac/tests/test_scratch_image_pin.py`,
      17 cases (unit):
      - **Role structure, read as YAML.**
        - The pin is an eight-digit release, its URL dated and never `current`,
          its digest 64 hex characters, and its stored name carries the release.
        - `vm-create.yml`'s directives name neither `current` nor the
          unversioned file.
        - The download goes to the pinned path with the pinned checksum, never
          `force`, and only when the `stat` found nothing.
        - The verification has the disk's own condition, does not depend on the
          file's presence, and is the task immediately before `qemu-img create`.
          That task's `-b` is the pinned path.
        - No `qemu-img`, `virt-install`, or `virsh define` precedes the
          verification.
        - In `prerequisites.yml`, every task before the architecture check is a
          local, read-only one. The check precedes the first task that changes
          the host, and it is conditioned on a scratch create.
      - **Behaviour, through `shell_harness`.**
        - The architecture check's real shell, with `uname` faked: `x86_64`
          passes; `aarch64` fails naming it; an empty answer fails naming
          `unknown`.
        - The verification's real shell, with the real `sha256sum` on a
          temporary file of synthetic bytes: a matching digest passes; a
          mismatch fails naming both digests and leaves the file byte for byte;
          a missing file fails.
      - **Red.** Against `HEAD`'s role, all 17 failed. The red is weak for most
        of them, since they had nothing to read. These are the meaningful ones:
        - a `current` URL and the unversioned name were found;
        - no verification preceded the disk.
      - **Mutations, each on a temporary copy, each caught by exactly one case:**
        - conditioning the verification on a fresh download alone fails the
          both-paths ordering case;
        - removing the digest comparison fails the mismatch case.
      - **Real Ansible.**
        - `make -C domains/vms/provisioning/iac validate-playbooks` passed on
          the system's ansible 2.10.8, and on ansible-core 2.19.14 from an
          isolated environment outside the repository. That is the version the
          service image's `ansible-core>=2.17,<2.20` resolves. The playbook
          reaches the role's task files only through `include_tasks`, which a
          syntax check does not parse.
        - So a throwaway playbook outside the repository `import_tasks`
          `prerequisites.yml`, `vm-create.yml`, `vm-remove.yml`,
          `vm-undefine.yml`, and both retry files, with the role's
          `vars/main.yml`. Its `--syntax-check` passed on both versions.
          Correction (14.8): that check is now in the repository, run by
          `validate-playbooks`. On Section 14's candidate it failed on three
          tasks Sections 13 and 14 edited, whose comments carried apostrophes;
          what the throwaway parsed is not known.
        - Corroboration, not a repository suite: the architecture check and the
          verification ran as tasks under ansible-core 2.19.14 against
          `localhost`, with the role's variables and a synthetic file, the
          overrides given as extra variables:
          - a matching digest: `ok=2`;
          - a mismatch: failed, naming the file's digest;
          - a faked `aarch64`: failed, naming it.
- [x] 12.3 Verification:
      - `make -C domains/vms/provisioning/iac test` (unit);
      - `make -C domains/vms/provisioning/adapter test` (unit and library
        integration; its tests read `vm-create.yml`);
      - `make check-packaging`.

      End-to-end: the VM mock lanes run no playbook, so the recipe does not reach
      them. The live VM lane is the system evidence. The role ships in no Python
      package, so no version changes. Owed by validation: none.

      Done:
      - `make -C domains/vms/provisioning/iac test`: exit 0, 82 passed (unit): the
        65 before this section and 17 new.
      - `make -C domains/vms/provisioning/adapter test`: exit 0, 262 passed (unit,
        and library integration in its `tests/integration`), after its `reinit`.
      - `make check-packaging`: exit 0, the architecture rules included.
      - **Delivery.** The role ships through the provisioning service image's
        `COPY` of `domains/vms/provisioning/iac`, whose `.dockerignore` admits
        the whole tree, `vars/` included.
        Correction (14.12): that ignore file replaces the root one, so it also
        admitted the checkout's environments and caches under the tree; it now
        leaves them out. It is not in any wheel, so no version,
        floor, or lock moved. A wheel's contents say nothing about the role an
        image carries. Validation of a built image reads the role there.
      - **End-to-end, confirmed.** No mock lane runs a playbook. Owed by
        validation: none.

      **Handoff.**
      - A host already holding the release at the pinned path is verified and
        not downloaded again. A file there with another digest fails every
        scratch create until an operator removes it.
      - The live VM lane still owes a real download, or a staged copy's
        verification, and a guest booted from the pinned image.

## 13. A VM teardown removes only its own guest

Delivers D9, for the delta requirement "A VM teardown removes only what its guest
created". It must land before any real guest is created on a lane's host. Files:
- `domains/vms/provisioning/iac/ansible/roles/vm-management/tasks/vm-create.yml` (the
  rules a create adds, and the cleanup script it writes)
- `vm-remove.yml` and, where it removes the same artifacts, `vm-undefine.yml`
- the role's tests in `domains/vms/provisioning/iac/tests/`, including
  `test_cleanup_script_relay_teardown.py`'s harness of the cleanup script

- [x] 13.1 Every firewall and NAT rule a create adds for a guest carries a comment
      naming the guest:
      - the cleanup script removes rules by that exact comment;
      - unmarked rules are removed by the guest's `/32` address, never a prefix;
      - the subnet-wide masquerade rule is left alone.

      Done:
      - **The marker.** It is `vm_guest_rule_marker`, `arkhai-vm:<guest>`, in
        the role's `vars/main.yml`, and it is the only definition. A guest name
        is lowercase letters, digits, and hyphens, so the marker never needs
        quoting. `iptables -S` still quotes it because of the `:`, and the
        reader strips the quotes.
      - **The create** (the direct-forwarding path; a relay-backed create adds
        no rule) gives `-m comment --comment` with the marker to:
        - its DNAT rule;
        - its per-guest masquerade;
        - both FORWARD rules;
        - the fallback INPUT rule.

        Its `ufw allow` carries the marker as the rule's comment. The
        subnet-wide masquerade stays unmarked. firewalld's `--add-port` takes
        no comment.
      - **One implementation**, `roles/vm-management/files/guest_teardown.sh`
        (new). Every teardown path includes it with `lookup('file', ...)`:
        - the cleanup script the create writes;
        - `vm_remove`'s branch for a missing script (13.2);
        - three `vm_undefine` tasks: the forwarded port, the rules, and the
          firewall.

        It holds no Jinja delimiter, so including it into templated text
        changes nothing.
      - **What is a guest's.** The library reads `iptables -S` for nat
        PREROUTING and POSTROUTING and filter FORWARD and INPUT, and deletes a
        rule by its exact specification, `-A` turned into `-D`. A rule is the
        guest's when either:
        - it carries the guest's marker; or
        - it carries no comment at all and has one of the shapes a create
          writes, naming exactly the guest's address. The shapes are: DNAT to
          `<address>:22`; masquerade of `-d <address>/32 --dport 22`; FORWARD
          `ACCEPT` of `-d <address>/32 --dport 22` or of
          `-s <address>/32 --sport 22`. On INPUT, a tcp `ACCEPT` of exactly the
          guest's forwarded port.

        A rule carrying any other comment is not the guest's. The subnet
        masquerade names no `/32` address, so it never matches. The forwarded
        port is the `--dport` of the guest's own DNAT rule.
      - **The cleanup script** now:
        - also takes the guest's address from its reservation by exact name;
        - takes its port from the guest's own forwarding rule;
        - removes the rules through the library;
        - removes UFW rules by the marker, or, for one with no comment, by the
          exact `<port>/tcp`, IPv4 or IPv6;
        - removes firewalld's rule by the exact port.

        Each of these replaces a substring `grep`. Rules are removed directly,
        not inside `$(...)`, where bash clears `set -e`, so a deletion the host
        refuses fails the script.
      - **Found on the way: the proxy block's prefix match.** The cleanup
        script's `sed` range `/# BEGIN ... FOR VM $VM_NAME/,/# END .../d` also
        matched every guest whose name begins with this one's. It would delete
        that guest's block, and a relay registration with it. The library
        removes a block only by its exact BEGIN and END lines. It refuses a
        BEGIN without an END, which would otherwise take every later block. It
        rewrites the file in place, through an owner-only temporary copy,
        since the file holds the client's credential. It reloads the client,
        never restarts it. Reload failure stays `partial`, as before.
        `vm_undefine` already removed the block exactly, through
        `blockinfile`.
      - **`vm_undefine`** finds the forwarded port, removes the rules, and
        removes UFW and firewalld rules through the library. Its UFW
        verification lists what the library would still match, not a
        substring of the port.
- [x] 13.2 `vm_remove` with no cleanup script:
      - removes what it finds by the guest's name: the domain with its storage and
        firmware variables, the images, the relay proxy block, the DHCP
        reservation, and the marked rules;
      - reports the guest absent only when it finds none of them;
      - fails, naming the artifact, when it finds one it cannot attribute.

      Done, in `vm-remove.yml`. The `fail` on a missing script is gone. The
      force-destroy and the script run only when the script exists. Otherwise
      the new shell task "Remove what the guest left without a cleanup script"
      runs:
      - **Reading first.** It fails at once if the `default` network cannot be
        read. It takes the guest's domain by exact name, and its address from
        the domain, else from the reservation named exactly for it.
      - **What it cannot attribute.** With the guest's address unknown, it
        lists every unmarked rule of a create's shapes. A rule whose address is
        reserved for another name belongs to that guest and is set aside. Any
        other such rule could be this guest's or an unknown one's. The task
        fails naming each one, before anything is removed. With the address
        known, a rule for another address is not this guest's, so nothing is
        in doubt. Marked rules are attributed by the marker alone.
      - **What it removes**, each counted:
        - the domain, after a destroy if it is running, by `virsh undefine
          --remove-all-storage --nvram`;
        - `<guest>.qcow2`, `<guest>-init.iso`, and `<guest>_VARS.fd` by exact
          path;
        - the proxy block, exactly, with a reload;
        - each DHCP reservation whose name is exactly the guest's;
        - the guest's rules, UFW rules, and firewalld port, as 13.1 says;
        - the guest's SSH key files and `/tmp/cloudinit_<guest>_*`
          directories, which the create also leaves.

        Rules are saved only when one was removed.
      - **The report.** It prints `GUEST_PRESENT=true` when it removed
        anything, and `GUEST_PRESENT=false` with "Nothing of guest ... is on
        this host" when it removed nothing. `vm_remove_data` gains two fields:
        - `cleanup_record`: whether the script existed;
        - `guest_present`: true on the script path, and otherwise as the
          branch reported.

        Both print as text, as the bare-metal reclaim prints
        `account_present`.
        Correction (14.10): the role prints all three as booleans, from a
        single `| bool` expression; the mocks now print them so too. The fact's status and output come from whichever
        path ran. Each path registers its own result, since a skipped task's
        `register` would overwrite the other's.
      - **Beyond the plan's files: the mock.** D2 says the mock prints what
        the role prints. So the VM adapter's default remove now prints
        `cleanup_record` and `guest_present` as `"true"`, a delivered guest's
        remove. The adapter is already 0.16.0 in this change, and nothing reads
        either field, so it is not bumped.
- [x] 13.3 Tests:
      - **Behaviour (unit, through `shell_harness`):** the cleanup script's rule
        removal, with two guests whose addresses share a prefix, removing only the
        first guest's rules and never the masquerade rule; and the missing-script
        branch, where it is shell, finding each artifact, finding none, and finding
        one it cannot attribute.
      - **Role structure (unit):** the comment on every rule the create adds; no
        prefix match in cleanup; the missing-script branch's attribution checks
        where they are tasks rather than shell.
      - `make -C domains/vms/provisioning/iac validate-playbooks`.

      Owed outside this section: a real partial create's teardown is the live VM
      lane's evidence.

      Done (unit). New `tests/host_fakes.py` and `tests/test_guest_teardown.py`,
      21 cases, plus one case in the relay harness:
      - **The fakes.** `host_fakes.FakeHost` keeps the host's state in files:
        - `iptables -S` prints rules in `-S` form, quoting a comment as iptables
          1.8 does, and `-D` deletes the first equal rule or fails as iptables
          does;
        - `virsh` keeps domains, with state, address, MAC, and storage that
          `undefine --remove-all-storage` deletes, and the `default` network's
          reservations in `net-dumpxml` form;
        - `ufw` keeps numbered rules with comments;
        - `curl`, `systemctl`, and `firewall-cmd` are faked too, so no real one
          is reached.

        Every call is logged.
      - **The two guests.** `guest-1` at `192.0.2.1`, port 4000, and
        `guest-12` at `192.0.2.12`, port 40001. They share a prefix in name,
        address, and port. Guest A's rules are partly marked and partly not.
        Guest B's rules are too, and beside them sit the subnet masquerade, the
        management SSH `INPUT` rule, and a rule naming A's exact address under
        another comment. Paths under `/etc`, `/var`, and `/usr/local`, and
        `/tmp/cloudinit_`, are rewritten into a temporary tree, as the relay
        harness rewrites `/etc/frp`.
      - **Behaviour, each the real shell through `shell_harness`:**
        - **The cleanup script**, whole, as the create renders it for A. It
          removes exactly A's five rules, its domain, its storage, its ISO, its
          lease, its proxy block, and its UFW rules, marked and v6-unmarked.
          Every one of B's effects and of the host's own stays, the subnet
          masquerade and the 40001 UFW rules among them. A host refusing a
          `-D` fails the script before it reports the rules removed or
          undefines the domain.
        - **`vm_remove` without a script**, eight cases:
          - a partial create (domain, disk, ISO, NVRAM, keys, cloud-init
            directory, reservation, proxy, rules) is all removed, and B's
            same-named cloud-init directory stays;
          - a domain and its disk alone (the delta's scenario) are removed, and
            it succeeds;
          - nothing of the guest: `GUEST_PRESENT=false`, and no destructive
            call is made;
          - marked rules alone, with no address known, are removed by the
            marker;
          - an unmarked DNAT to an unreserved address, with the address
            unknown: the task fails naming that rule, and the domain, disk,
            proxy, and rule all stay, with no `-D` issued;
          - with the address unknown, B's unmarked rules, reserved to B, cause
            no doubt and stay;
          - a reservation alone supplies the address for A's unmarked rules;
          - an unreadable network fails before any `-D`.
        - **`vm_undefine`**: its port task reads 4000, and its rule task
          removes exactly A's five rules.
        - **The relay harness** gains a neighbour, `agent-vm-012`, whose block
          stays when `agent-vm-01`'s is removed. Its existing six cases now
          include the library; the harness has seven cases.
      - **Role structure:**
        - the four per-guest rules carry the marker and the subnet masquerade
          carries none;
        - the UFW and INPUT openings carry it;
        - the marker is defined once, in `vars/main.yml`;
        - every teardown task includes the library;
        - no teardown path keeps one of the substring greps or the unanchored
          `sed` range;
        - the library holds no Jinja delimiter;
        - `vm_remove` has no `fail` task, runs each path on its own condition,
          and reports `cleanup_record` and `guest_present`.
      - **Updated:** `test_vm_management_contracts.py`'s undefine case pinned
        the old line-number greps. It now pins the library's inclusion and
        calls.
      - **The VM adapter's mock** (unit): a new case asserts that the default
        remove prints `cleanup_record` and `guest_present` as `"true"`.
      - **Red.** Against `HEAD`'s task files, with only the new `files/` and
        `vars/` added so the modules import, 20 of the new cases failed. Most
        failed for want of the new tasks. Two reds are meaningful:
        - the relay neighbour case failed, because `HEAD`'s `sed` range
          deleted `agent-vm-012`'s block;
        - a corroboration against real iptables 1.8.7 (nf_tables), run in an
          unprivileged user and network namespace outside the repository.
          `HEAD`'s cleanup block, run for `192.0.2.1`, also deleted
          `192.0.2.12`'s masquerade and both its FORWARD rules. The library,
          on the same seeded rules, deleted exactly `192.0.2.1`'s five and left
          `192.0.2.12`'s, the subnet masquerade, and the management SSH rule.
      - **Mutations, each on a temporary copy:**
        - an address compared as a prefix fails 5 cases;
        - the marker compared as a prefix fails 8;
        - removing the unattributable refusal fails its case.
      - **Real Ansible.**
        - `validate-playbooks` and the throwaway `import_tasks` syntax check
          (12.2) passed on 2.10.8, 2.17.14, and 2.19.14.
          Correction (14.8): on the role files as committed, the in-repository
          check fails under 2.17.14 and 2.19.14, at a task this section edited.
        - Corroboration, outside the repository: `vm-remove.yml` ran through
          `include_role` under ansible-core 2.17.14 and 2.19.14, against
          `localhost`, with `host_fakes` on `PATH`. This exercised the library's
          `lookup('file')` from the role's `files/`, the templating, and the
          conditionals:
          - a guest with nothing on the host printed `cleanup_record: false`
            and `guest_present: false`;
          - an unattributable DNAT failed, naming it, with "nothing was
            removed".
        - The system's ansible 2.10.8 cannot run this role at all: any filter
          fails against the installed Jinja2 3.x, with `environmentfilter`
          missing. So its run is not evidence either way.
- [x] 13.4 Verification:
      - `make -C domains/vms/provisioning/iac test` (unit);
      - `make -C domains/vms/provisioning/adapter test`;
      - `make check-packaging`.

      End-to-end: the VM mock lanes run no playbook. The live VM lane is the system
      evidence. No version changes. Owed by validation: none.

      Done:
      - `make -C domains/vms/provisioning/iac test`: exit 0, 104 passed (unit):
        82 before this section, 21 in the new module, and the relay harness's
        new case.
      - `make -C domains/vms/provisioning/adapter test`: exit 0, 263 passed (unit,
        and library integration in its `tests/integration`), one new.
      - **The mock's consumers in the service.** After `make dist` and the
        service's `reinit`, five integration modules passed 95, exit 0, under
        the mock profile: `test_system_api`, `test_fulfillment_api`,
        `test_test_controller`, `test_vms_api`, and `test_lease_release_api`.
        These are application integration through the typed clients, with
        direct-storage setup in some. The service's whole suite was not re-run:
        the mock's remove fact only gained two fields, which nothing reads.
      - `make check-packaging`: exit 0, the architecture rules included. The
        rebuilt 0.16.0 adapter wheel's 32 package files equal their source.
      - **Versions.** None moved. The adapter is already 0.16.0 in this change.
        The role ships in the provisioning service image's `COPY` of the IaC
        tree, `files/` included, and in no wheel.
      - **End-to-end, confirmed.** No mock lane runs a playbook. The VM lane's
        default remove output gains two fields that no scenario reads. Owed by
        validation: none.

      **Handoff.**
      - D9 is in place before any real guest. On the relay path a create adds
        no rule. So the live lane's teardown exercises the proxy block, the
        reservation, the domain, and its storage, not rules.
      - Guests created before this section have cleanup scripts holding the
        old substring matches. Those scripts run as written. Only a host's
        fresh guests, and a teardown with no script, use the library.
      - Not changed:
        - the subnet masquerade the create appends on every direct-path
          create, which accumulates duplicates;
        - a failed reload of the relay client, which stays non-fatal (`partial`)
          on both paths;
        - the cleanup script's unconditional `iptables-save`.

        Each predates this change and is outside D9.

## 14. A GPU guest's boot-GPU detection and opt-in, readiness wait, and autostart

Delivers D12 and D13, for the delta requirements "A host's boot GPU is passed through
only by an operator's opt-in" and "A GPU guest's readiness wait and autostart are set
by its pool's operator". Files:
- `domains/vms/provisioning/iac/ansible/roles/vm-management/tasks/vm-create.yml`: the
  boot-GPU detection, the single-GPU selector, every other task that excludes or
  refuses the boot GPU, the setup wait, and the autostart task
- the role's tests in `domains/vms/provisioning/iac/tests/`, beside
  `test_gpu_attachment_discovery.py`
- `domains/vms/provisioning/adapter/tests/unit/`, for where the settings come from

- [x] 14.1 Boot-GPU detection reads each candidate's own sysfs `boot_vga` flag, in place
      of the `lspci -D -vmm` parse that expects a device's `Slot:` after its `Class:`
      and so finds none on a real host. Every task that excludes or refuses the boot
      GPU uses that one test. List those tasks in this section's notes.

      Done:
      - **One test**, `roles/vm-management/files/gpu_eligibility.sh` (new),
        included with `lookup('file', ...)`:
        - `gpu_is_boot_gpu` reads `/sys/bus/pci/devices/<address>/boot_vga`;
        - `gpu_driver` reads the device's `driver` link;
        - `gpus_attached_to_guests` reads every defined guest's hostdev
          *source* addresses;
        - `gpu_ineligibility` and `eligible_gpus` combine them.

        No `lspci -D -vmm` parse, `HOST_GPU`, or `boot_vga` read remains in
        `vm-create.yml` or `gpu-virt-install-retry.yml`.
      - **The tasks that use it**, each with the opt-in:
        - "Get all GPUs currently attached to VMs", the listing that names each
          inventory GPU and why it is not eligible;
        - "Find least-used available GPU", the single-GPU selector;
        - "Get total available GPUs for retry calculation", which now counts
          eligible GPUs;
        - "Get alternative GPU (excluding attempted ones)", twice, in the scratch
          and golden retry rescues;
        - "Get next alternative GPU (excluding attempted ones)" in
          `gpu-virt-install-retry.yml`;
        - "Auto-select available GPUs by count", the multi-GPU selection.
      - **Wider than the plan's single selector, deliberately.** Before this
        section, the three retry alternatives and the multi-GPU selection
        excluded no boot GPU at all. So a first attempt failing on another GPU
        could fall back to the host's console GPU. They now draw only eligible
        GPUs. That also stops a retry taking a GPU another defined guest holds,
        which the first choice already refused. The delta's D12 requirement now
        names all three ways a create chooses, with a retry scenario, and D12 in
        `design.md` says why.
      - **Not changed:**
        - `gpu-virt-install-multi-retry.yml`, which nothing includes but itself;
        - a storefront-supplied `vm_gpu_devices` list. `gpu-virt-install-multi.yml`
          reads each entry's `.pci`, and the requirements model types the list as
          strings, so such a list fails at templating before any `virt-install`;
          it selects no device.
      - **Found on the way.** Every attachment scan read the five lines after a
        hostdev, so a device's address *inside* its guest also counted as a
        host device. The library reads only `<source>` addresses, normalized
        from libvirt's `0x` hex.
- [x] 14.2 The opt-in, `vm_passthrough_boot_gpu`, false when absent. Without it the boot
      GPU is never selected, whatever the inventory lists. With it, the boot GPU is
      eligible only when, at selection, the capability inventory lists it available,
      the device's sysfs driver link names `vfio-pci`, and no defined guest has it
      attached. Another driver, or none, makes it ineligible, and a create left with
      no eligible GPU fails before defining a domain. Nothing in the role binds or
      unbinds a device. The selection among eligible GPUs is unchanged.

      Done:
      - **The opt-in.** `defaults/main.yml` (new) defaults it to false. A pool's
        `extra_vars` reach the playbook as extra variables and override that.
        Every selector renders it as `true` or `false` for the library.
      - **Eligibility.** A candidate is a GPU the inventory lists. It is
        ineligible when a defined guest has it attached. When it is the boot
        GPU, it is also ineligible without the opt-in, or when its driver link
        is anything but `vfio-pci`, absent included. Each exclusion is named on
        stderr.
      - **Failure.** An empty eligible set prints `NO_AVAILABLE_GPU`, and the
        existing "Fail if no available GPU found" stops the create before any
        domain is defined. Its message shows the listing's reasons.
      - **Fail closed.** Defined guests that cannot be read fail the selection.
        The first choice and the alternatives exit non-zero; the retry count
        reads zero.
      - **Unchanged.** The least-used choice among eligible GPUs, the
        multi-GPU selection's holding back of its first eligible GPU, and a
        supplied `vm_gpu_device`'s replacement by the selector's choice.
      - **No binding.** No file of the role binds or unbinds a device: no
        `/bind`, `/unbind`, `driver_override`, `new_id`, `nodedev-detach`,
        `nodedev-reattach`, or `modprobe`.
- [x] 14.3 The readiness wait reads `vm_setup_wait_attempts` and
      `vm_setup_wait_interval_seconds`, defaulting to 10 and 30. A value that is not
      a positive integer fails the create, naming it, before any host effect, and a
      wait that runs out fails the create naming the bound, as today.

      Done:
      - **Defaults.** 10 and 30, in `defaults/main.yml`.
      - **The type check.** It is in `prerequisites.yml`, before the
        architecture check and every task that touches the host. Two `assert`
        tasks run on the controller for every create:
        - `vm_setup_wait_attempts` and `vm_setup_wait_interval_seconds` must
          each be `is integer` and `> 0`;
        - `vm_passthrough_boot_gpu` and `vm_autostart` must each be
          `is boolean`.

        Each failure names its setting. The checks are strict: a quoted `"40"`
        is text, and `true` is not a count. A pool's `extra_vars` reach the
        playbook as JSON, so their types survive.
      - **The wait** loops at most the pool's number of attempts, sleeping the
        pool's interval between them. On running out it fails, printing "VM
        setup was not confirmed within <n> attempts, <s> seconds apart
        (vm_setup_wait_attempts, vm_setup_wait_interval_seconds)" to stderr.
- [x] 14.4 The autostart task runs only when `vm_autostart`, true when absent, is true.

      Done: the task's condition gains `vm_autostart | bool`. The type check in
      14.3 has already refused a value that is not a boolean. Teardown is
      unchanged.
- [x] 14.5 Tests:
      - **Detection and selection (unit, through `shell_harness`):** the selector run
        with `lspci`, `virsh`, and the device's sysfs files faked. The fake `lspci -D
        -vmm` prints each record in that format's real field order, `Slot:` before
        `Class:`, with synthetic devices, documentation-style addresses, and no real
        model or identifier. Cases:
        - a host whose only GPU is its boot GPU, listed available by the inventory:
          excluded without the opt-in — the regression, which the current parse
          fails;
        - with the opt-in, bound to `vfio-pci` and unattached: selected;
        - with the opt-in, the inventory listing it but its driver another, or none:
          excluded, and the create's no-GPU failure follows — the stale-inventory
          regression;
        - with the opt-in, attached to a defined guest: excluded;
        - a host with a second, non-boot GPU: the other GPU is selected without the
          opt-in.

        If a sysfs file cannot be faked through the harness, make the path the
        task reads a variable the test can point at a temporary tree, and record
        why; prove nothing by structure alone that behaviour can prove.
      - **Role structure (unit):** every boot-GPU exclusion uses the per-device flag
        and reads the opt-in; no task binds or unbinds a device; the wait reads its
        two settings, validates them before the create's first host effect, and
        keeps its failure; the autostart task's condition.
      - **The settings' source (unit, VM adapter):** none of the four settings is a
        job parameter or a fulfillment requirement field, and each reaches the
        playbook from the pool's `extra_vars` through the fulfillment plan.
      - `make -C domains/vms/provisioning/iac validate-playbooks`.

      Owed outside this section: a real passthrough of a boot GPU, its readiness on
      the lane's host, and the GPU's return to the host's driver baseline are the
      live VM lane's evidence, after the operator's host procedure is reviewed.

      Done (unit), in a new `domains/vms/provisioning/iac/tests/test_gpu_eligibility.py`
      (22 cases, 2 of them with subtests) and a new
      `domains/vms/provisioning/adapter/tests/unit/test_gpu_guest_settings.py`
      (7 cases):
      - **The fake.** `host_fakes.FakeGpuHost` builds a sysfs PCI tree under a
        temporary directory, with each device's `boot_vga` and `driver` link.
        Its `lspci -D -vmm` prints `Slot:` before `Class:`. Its `virsh`
        reports defined guests, each hostdev with a source address and a
        separate guest-side address.
      - **Faking sysfs.** The library names `/sys/bus/pci/devices` once, as
        `PCI_DEVICES`, and the test rewrites that literal to the temporary
        tree. This is the same path rewriting the teardown tests do, so no
        production variable exists for testing. The GPUs are synthetic devices
        at arbitrary addresses.
      - **Behaviour, the real shell through `shell_harness`:**
        - **The single selector:**
          - the boot GPU alone, no opt-in: `NO_AVAILABLE_GPU`, named as the
            boot GPU without an opt-in;
          - opt-in and `vfio-pci`: selected;
          - opt-in with `nvidia`, or no driver: `NO_AVAILABLE_GPU`, naming the
            driver;
          - opt-in but attached to a defined guest: excluded;
          - with a second GPU and no opt-in: the second is selected;
          - a guest-side address equal to a candidate's: the candidate is not
            taken as attached;
          - defined guests that cannot be read: the task fails.
        - **The three alternatives:** each refuses to fall back to the boot GPU
          without the opt-in, and takes the bound boot GPU with it.
        - **The retry count:** 1 without the opt-in and 2 with it, over a boot
          GPU, a free GPU, and an attached GPU.
        - **Multi-GPU:** three asked of four listed, the boot GPU listed
          second: exactly the two eligible GPUs not held back are selected.
        - **The readiness wait,** with `ssh` and `sleep` faked:
          - the defaults: 10 attempts, 9 sleeps of 30, then a failure naming
            the bound;
          - 40/15: 40 attempts, 39 sleeps of 15, then a failure naming both
            settings;
          - a guest ready on the third attempt: two sleeps of 15, success.
      - **Role structure:**
        - the defaults are exactly false/10/30/true;
        - both type checks loop their settings with these exact conditions,
          run on the controller for a create, and precede the first task
          delegated to the host;
        - the wait reads its two settings and no fixed `sleep 30`;
        - the autostart condition reads `vm_autostart | bool`;
        - every task choosing a GPU includes the library and reads the opt-in;
        - the boot GPU is read only from its flag;
        - no role file binds or unbinds a device;
        - the library carries no Jinja delimiter.
      - **The settings' source (unit, VM adapter):**
        - no `VmFulfillmentRequirements` field names any of the four settings,
          and a request naming one is refused, naming it, for each;
        - no `VmJobParams` field and no job variable names one;
        - a pool's `extra_vars` holding all four reach the prepared job's
          `provider_extra_vars`, and the rendered extra-vars document, with
          their types: `true`, `40`, `15`, `false`.
      - **`test_gpu_attachment_discovery.py`'s** full-task syntax case now
        renders the include and the opt-in before `bash -n`.
      - **Red.** Against `HEAD`'s task files, with only the new `files/` and
        `defaults/` added, 13 of the selection and wait cases failed. The
        decisive ones:
        - `HEAD`'s selector chose the boot GPU `0000:0a:00.0` without any
          opt-in, since its parse found no boot GPU in real field order;
        - it preferred the boot GPU over a second GPU;
        - all three of its alternatives fell back to the boot GPU;
        - its attachment scan took a guest-side address for a host device;
        - its wait ignored the pool's bound.

        The multi-GPU case passed on `HEAD` only by its hold-back's luck, so it
        was rearranged to list the boot GPU second.
      - **Mutations, each on a temporary copy:**
        - removing the opt-in check fails 5 cases;
        - removing the driver check fails both stale-inventory subtests;
        - removing the attachment check fails 2 cases.
      - **Real Ansible, corroboration outside the repository**, on ansible-core
        2.17.14 and 2.19.14:
        - The two type checks ran with the role's defaults and pool-style extra
          variables:
          - the defaults and a 40/15/false/true pool passed;
          - `0`, `-1`, `"abc"`, `"40"`, and `true` as a count each failed,
            naming the setting;
          - `"no"` and `1` as a switch each failed, naming it;
          - the opt-in rendered `false` and `true`;
          - the autostart condition held only for the default.
        - The real selector task ran through `include_role` from a temporary
          copy of the role, whose library pointed at a fixture tree.
          `lookup('file')`, the `{% if %}` block, and the default against the
          extra variable gave `NO_AVAILABLE_GPU` without the opt-in and the
          boot GPU with it.
        - `validate-playbooks` and the `import_tasks` syntax check passed on
          2.10.8, 2.17.14, and 2.19.14.
          Correction (14.8): on the role files as committed, the in-repository
          check fails under 2.17.14 and 2.19.14, first at "Auto-select available
          GPUs by count", whose comment this section added.
- [x] 14.6 Verification:
      - `make -C domains/vms/provisioning/iac test` (unit);
      - `make -C domains/vms/provisioning/adapter test` (unit and library
        integration);
      - `make check-packaging`.

      End-to-end: the VM mock lanes run no playbook, and a mock scenario's result
      is never evidence for the recipe. The live VM lane is the system evidence. A
      section changing only the role and tests changes no version. Owed by
      validation: none.

      This section freezes Round 2's candidate: the round's one full `make test`,
      one independent implementation review, and one validation follow it, before
      any live purchase.

      Done:
      - `make -C domains/vms/provisioning/iac test`: exit 0, 126 passed and 2
        subtests passed (unit): 104 before this section and 22 new.
      - `make -C domains/vms/provisioning/adapter test`: exit 0, 270 passed (unit,
        and library integration in its `tests/integration`): 263 before, 7 new.
      - `make check-packaging`: exit 0, the architecture rules included.
      - **Versions.** None moved. The adapter changed only in tests. The role,
        its new `defaults/` and `files/` included, ships in the provisioning
        service image's `COPY` of the IaC tree, not in a wheel. A wheel's
        contents say nothing about the role an image carries.
      - **End-to-end, confirmed.** No mock lane runs a playbook. Owed by
        validation: none.

      **Handoff.** Round 2's sections are complete; its candidate is frozen at
      this section's commit.
      - **Owed on the frozen candidate:** one root `make test`, one independent
        implementation review covering Sections 7 to 14, and local, Helm, and
        pipeline validation. Then the round's triage.
      - **Owed by the live VM lane:**
        - the pinned image's download, or a staged copy's verification;
        - a guest booted from it;
        - with `vm_passthrough_boot_gpu`, a boot GPU the operator bound to
          `vfio-pci` passed through;
        - its readiness within the pool's bound;
        - `vm_autostart` false honoured;
        - a teardown removing only the guest's artifacts;
        - the GPU back on its host driver.

        A lane whose only GPU is its boot GPU sets the opt-in and
        `vm_autostart: false` in the pool's `extra_vars`, and a readiness wait
        measured on its host.
      - **The fresh-context compliance checks of Sections 12 to 14 were not
        run.** This phase runs no subagent or reviewer, and the round's one
        independent review covers them.

**Merge of `dev` after Section 14.** Round 2's frozen candidate passed its full local
run and its pipeline and was reviewed, and its Helm part had not run, when `dev`
advanced by three commits: `gpu-optional-compute-shapes`, a change-workflow command
following a change's clone, and a CI change running each of `make test`'s targets as
its own job. This branch merged `dev` at `1f157a17d` before any live run (`design.md`,
"Coordination with `gpu-optional-compute-shapes`"). The merge and the corrections
after it make Round 2's new candidate, which owes the round's full `make test`, the
review's amendment, and validation again.

- [x] 14.7 Merge `dev` at `1f157a17d`, resolve each conflict so both sides hold, and
      reconcile what merged without one.

      Done:
      - **Conflicts**, each resolved so both sides hold:
        - `docs/development/VALIDATION_RUNBOOK.md` and
          `tools/issue-discovery/config/phases/local.yaml`: the mock host request
          states `ssh` version 2, as this branch has it, and no `gpu_count`, which
          `dev` retired.
        - `provisioning/compute/ansible/src/compute_provisioning_ansible/inventory.py`:
          the parser reads `public_port=` with `ansible_port=`'s rule, a malformed
          value rejecting its entry, and reads no `gpus=` or `gpu_model=`, as `dev`
          has it; the docstring lists both changes.
        - `provisioning/compute/service/pyproject.toml`: this branch's floors and
          `dev`'s exact `arkhai-core-storefront-client==0.29.0` pin; its `uv.lock` is
          `dev`'s, regenerated by `make lock`.
        - `openspec/changes/README.md`: `gpu-optional-compute-shapes`'s row is
          `dev`'s, archived; this change's row is this branch's.
        - `gpu-optional-compute-shapes`'s active `proposal.md`: deleted, as `dev`
          archived the change. Its archived copy is `dev`'s and is not
          recreated or edited; the note this branch had added to the active proposal
          went with it (1.2's correction).
      - **Reconciled without a conflict.** Every file both sides changed was read.
        One merged cleanly and broke D1: `dev`'s new stage
        `test_09d_arm_a_create_rule_for_the_machine` in
        `e2e-tests/tests/e2e/roles/scenarios/vms/test_listing_shapes.py` armed a
        create rule with a fixed `result_stdout` naming `e2e-shapes-cpu-vm`, which is
        not the job's guest, with no `status`, in the JSON `var:` form. Under D1 that
        create yields no evidence, so `market buy` in `test_09e` would not reach
        `ready`. The rule keeps its id, match, and gate and drops the output, as 5.4
        did for the scenario's other rule; nothing reads the dropped values. The e2e
        helpers' host registrations merged with both `version=2` and no GPU fields.
        A scan of every `ConnectionSubmission` naming `ssh` finds no production or
        scenario caller without a version; the two that state none are tests of the
        refusal and of an unregistered kind.
      - **Specifications.** Every requirement the `physical-provisioning` and
        `fulfillment` deltas modify is byte for byte the same on the old base and on
        `dev`, and no added requirement's name is taken on `dev`. `dev`'s own edits
        ("Host inventory is connection identity", "Host writes declare no
        capacity", and the added "A host record describes no hardware") are in
        requirements the deltas do not touch, so the deltas needed no edit.
      - **Versions**, measured against `dev` (`RELEASING.md`, "Versioning policy"):
        both branches had taken the same next minor of four packages, so this
        change's bump of each is the next above `dev`'s:
        - `arkhai-compute-provisioning-ansible` 0.6.0, and both adapters' and the
          service's floors on it `>=0.6.0`, for `read_fact` and `public_port`;
        - `arkhai-compute-provisioning` 0.23.0, and the service's floor on it
          `>=0.23.0`, for compensation;
        - `arkhai-compute-provisioning-service` 0.21.0;
        - `arkhai-vms-storefront` 0.25.0.

        `arkhai-kit-fulfillment` 0.6.0 and the bare-metal and VM adapters, 0.12.0
        and 0.16.0, were already above `dev`'s and are unchanged. These numbers
        supersede the versions Sections 2, 3, 8, and 9 recorded.
      - **Change documents.** `design.md` gains "Coordination with
        `gpu-optional-compute-shapes`" and a note on the new candidate under
        "Implementation cadence", and its non-goal on host GPU fields, D3's host
        update, D7, the open questions, and D7's promotion row say that the change
        landed and is archived. The proposal and this change's index row say the
        same, and the row now says Sections 2–14 are implemented. Closeout task 15.5
        is reworded to match; no closeout task changes otherwise.

      Evidence, after `make dist-clean` and `make lock`:
      - `make lock`: only the versions and floors above moved;
      - `make check-packaging`: passed, the architecture rules included;
      - `make -C provisioning/compute/ansible test`: 134 passed (unit);
      - `make -C provisioning/compute test`: 281 passed (unit and library
        integration);
      - `make -C kit/fulfillment test`: 200 passed (unit and library integration);
      - `make -C domains/bare_metal/provisioning/adapter test`: 88 passed (unit);
      - `make -C domains/vms/provisioning/adapter test`: 272 passed (unit, and
        library integration in its `tests/integration`);
      - `make -C provisioning/compute/service test`: 607 unit and 480 integration
        passed, exit 0. The integration folder mixes application integration
        through the typed clients with direct-storage migration and setup cases,
        `dev`'s host GPU column drop among them;
      - `make -C e2e-tests test-unit`: 208 passed (unit); the scenario modules
        import, the edited stage among them. No scenario was run;
      - `make -C domains/vms/storefront test`: unit 1198 passed and 1 skipped. Its
        integration phase was stopped at 42% by the session's command time limit,
        with no failure reported, and was run again on its own: 501 passed, exit
        0. Both folders mix levels, as Section 9 recorded.

      End-to-end: the VM lane's `e2e_listing_shapes` now reads every create through
      the per-job default, `dev`'s stage without GPUs included. Owed by validation:
      the pipeline and Helm on the new candidate.

**Corrections after the Round 2 implementation review.** An independent review of
Section 14's candidate, `928d4c0c8` over `99e55949`, raised F1 to F4, none blocking.
It disclosed that it read `ARCHITECTURE.md`, `DEPLOYMENT_AND_CONFIG.md`, and
`ROADMAP.md` only in part; its continuation completes those reads before it amends
its judgement for the new candidate. Under the owner's delegated judgement the
supervising session accepted all four, and added S1, found while checking the
image's packaging. These are partial dispositions: no round outcome is recorded
until the new candidate's validation and the amended review join.
Each is fixed below, on top of the merge (14.7). They span Sections 10 to 14 and the
service's image, and are recorded here, after the round's last section, with a
pointer from each note they correct.

- [x] 14.8 F1: a checked-in playbook, never run, statically imports the
      `vm-management` role's `prerequisites.yml`, `vm-create.yml`, `vm-remove.yml`,
      `vm-undefine.yml`, `gpu-virt-install-retry.yml`, and
      `gpu-virt-install-multi-retry.yml`, and `make validate-playbooks` syntax-checks
      it, so the repository's own check parses the task files the role reaches only
      through `include_tasks`.

      Done:
      - **The playbook.**
        `domains/vms/provisioning/iac/ansible/playbooks/single-tenant/vm-management-task-files.yaml`
        imports each file through `import_role` with `tasks_from`, so each is
        parsed as part of the role, with its defaults, vars, and files. Its first
        task is a `fail`, so a run reaches none of the imports. Its header says it
        is parse-only and what a syntax check does not show. A task listing, which
        runs nothing, shows the refusal first and the role's tasks resolved under
        the role.
      - **`validate-playbooks`** gains its `--syntax-check`.
      - **It found three tasks that do not load.** On the role files of Section
        14's candidate, the new check failed under ansible-core 2.17.14 and
        2.19.14: Ansible splits a free-form `shell: |` string as module arguments,
        and an apostrophe in a bash comment reads as an unbalanced quote, so the
        whole task file fails as it loads. Sections 13 and 14 had added such
        comments to three tasks:
        - `vm-create.yml`, "Auto-select available GPUs by count" ("the pool's
          opt-in");
        - `vm-create.yml`, "Set up iptables port forwarding for SSH" ("no other
          guest's", "no guest's marker");
        - `vm-undefine.yml`, "Get external port before cleanup (for firewall rule
          removal)" ("this guest's own").

        `vm-create.yml` and `vm-undefine.yml` are loaded by `include_tasks` when a
        create or an undefine runs, so every real VM create would have failed
        before any task ran; no mock lane runs a playbook, and the shell harness
        runs the scripts with bash, which accepts them. At `99e55949`, before Round
        2, all three parsed. The four comments are reworded with no apostrophe and
        no executable line changes. The playbook's header states the constraint.
        A parse of every free-form `shell`/`command` string in the role, with
        Ansible's own splitter, now finds one failure, `vm-check.yml`'s "Get total
        GPU count", which already failed at `99e55949`, is outside this change's
        files and the playbook's imports, and is left as it is.
        Correction (14.14): it is fixed and imported too, since the operator's
        host-capacity read runs it.
      - **A structural guard** (unit), beside the audit playbook's, in
        `tests/test_ansible_structure.py`: the playbook refuses first, imports each
        of the six files through `import_role` and nothing dynamically, each named
        file exists, and `validate-playbooks` checks it. Replacing one
        `import_role` with `include_role`, in a scratch copy, fails it.

      Evidence:
      - `make -C domains/vms/provisioning/iac validate-playbooks`, run with
        isolated ansible-core 2.17.14 and 2.19.14 environments outside the
        repository first on `PATH`, the bounds of the service image's
        `ansible-core>=2.17,<2.20`: before the rewording, exit 2 at the first
        failing task; after it, exit 0, every playbook parsed. The workstation's
        ansible 2.10.8, below the supported range, also passes. No CI job runs
        this target.
      - `make -C domains/vms/provisioning/iac test`: 127 passed and 2 subtests
        passed (unit), the shell-harness behaviour tests unchanged.

      A syntax check renders no Jinja and runs nothing. That the role's templates
      render, and that it works on a host, remains the live VM lane's evidence.
- [x] 14.9 F2: D10's sixth condition lists the site's held states without the retired
      `provisioning`, and names the site's `HELD_RESERVATION_STATES`
      (`kit/site/src/market_site/db.py`) as the authority for the list, which holds
      `reserved`, `leased`, `releasing`, `release_failed`, and `unmanaged`.

      Done, in `design.md` only. The edit was made in this session before the
      merge concluded, so it is in the merge commit with 14.7's documents. Closeout
      task 15.9 already promotes those five states and names neither retired one.
- [x] 14.10 F3: the three diagnostic fields this change added to the mocks print as
      JSON booleans, as the roles print them: `account_present` in bare metal's
      default reclaim, and `cleanup_record` and `guest_present` in VM's default
      remove. The roles set each from a single `| bool` expression, which Ansible
      templates as a boolean, so their `to_nice_json` copy prints `true` or
      `false`. The older text fields beside them, `account_locked` and
      `account_deleted`, are unchanged: nothing reads them.

      Done:
      - `bare_metal_provisioning_adapter/services/mock_output.py`:
        `account_present=True`; its `var:` display prints a boolean bare.
      - `vm_provisioning_adapter/services/mock_output.py`: `cleanup_record=True`
        and `guest_present=True`, which its display already printed bare.
      - The two producer tests assert `True` where they asserted `"true"`; against
        the earlier mocks they fail.
      - Neither adapter is bumped again: both are already above `dev` in this
        change.

      Evidence:
      - `make -C domains/bare_metal/provisioning/adapter test`: 88 passed (unit);
      - `make -C domains/vms/provisioning/adapter test`: 272 passed (unit, and
        library integration in its `tests/integration`);
      - after `make check-packaging` rebuilt the wheelhouse and the service's
        `reinit`, the service's mock-profile consumers of these outputs,
        `test_bare_metal_mock_profile`, `test_lease_release_api`, `test_system_api`,
        `test_fulfillment_api`, `test_test_controller`, and `test_vms_api`: 103
        passed (application integration through the typed clients, with
        direct-storage setup in some). Nothing reads the three fields.
- [x] 14.11 F4: `e2e-tests/tests/e2e/roles/README.md` describes
      `e2e_bare_metal_deal` in one paragraph: teardown to `released`, revocation
      only by the pinned host's public-key refusal, and a missing prerequisite
      named and left unavailable. The paragraph after it, which still said the
      scenario waits for a configured terminal status and counts any failed attempt
      as revocation, is folded into it.
- [x] 14.12 S1: the provisioning service's `Dockerfile.dockerignore` replaces the
      root `.dockerignore` for that image, and admits both IaC trees whole, so the
      root's exclusions never applied there. A checkout's `.venv`,
      `__pycache__`, and `.pytest_cache` under the VM IaC tree were in the build
      context. Late exclusions now leave out, by the repository's own ignore rules
      for those trees, environments and caches, Ansible logs and retry files, and
      the VM IaC tree's operator keys, credentials, local inventories, and variable
      files, re-admitting the tracked `ansible/keys/.gitignore` and the two
      inventory examples.

      Done. Nothing secret was found in the context; the files that were admitted
      are environments and caches. No test mirrors the patterns. Evidence, short of
      an image:
      - an emulation of Docker's ignore matching over the old and new rules: of 150
        tracked files and wheels the image takes, none changes inclusion, every role
        asset this round added among them; of 688 untracked files then under the
        IaC trees, the old rules admitted all and the new admit none;
      - `make check-packaging`, which reads the image's ignore file: passed.

      Owed by validation: the candidate image's own contents, its IaC files equal
      to the tracked ones and no local runtime artifact present.
- [x] 14.13 Verification of 14.8 to 14.12:
      - the suites named in each task above;
      - `make check-packaging`: passed, the architecture rules included; every
        changed distribution's wheel equals its source;
      - `make check-change CHANGE=repair-compute-purchase-recovery`, with comment
        hygiene: passed.

      End-to-end: the VM lane's remove and the bare-metal lane's reclaim read the
      changed mock fields, which no scenario asserts on. No scenario runs a
      playbook. Owed by validation: the round's full `make test`, the pipeline,
      Helm, and the image inspection in 14.12, on the new candidate.
- [x] 14.14 S2: `vm-check.yml`'s "Get total GPU count", the task file a host
      capacity read runs (`GET /api/v1/hosts/{host}/capacity` submits a
      `check` job), loads, and the parse-only playbook imports it.

      The supervising session accepted, under the owner's delegated judgement, the
      defect 14.8 found and left: the task's free-form `shell: |` carried "card's"
      in a bash comment, so Ansible's argument splitter refused the whole task
      file as it loaded, and every capacity read on a real host would fail before
      any task ran. It predates this change, as of `99e55949`, and is fixed here
      because a live VM host's preflight reads its capacity through that route.

      Done:
      - the comment is reworded with no apostrophe; no executable line, count
        rule, or API changes;
      - `vm-management-task-files.yaml` imports `vm-check` through `import_role`
        after the other six, behind the same refusal, and its header names a
        capacity check among the runs it covers;
      - the structural guard of 14.8 lists `vm-check` among the imported files.

      Evidence:
      - `make -C domains/vms/provisioning/iac validate-playbooks` with ansible-core
        2.17.14 and 2.19.14 first on `PATH`: on a scratch copy of the tree with the
        new playbook and `84ac2c117`'s `vm-check.yml`, exit 2 on each, at "Get total
        GPU count" ("failed at splitting arguments"); on the repository, exit 0 on
        each, every playbook parsed;
      - Ansible's own splitter over every free-form `shell` and `command` string of
        every role in both IaC trees: no failure remains;
      - `make -C domains/vms/provisioning/iac test`: 127 passed and 2 subtests
        passed (unit), the script's behaviour test in `test_passthrough_audit.py`
        among them;
      - `make check-packaging` and `make check-change`: passed. The role ships in
        no wheel, so no version, floor, or lock moved.

      Owed by validation: as 14.13, on the candidate this commit makes. Whether
      the count is right on a host stays the live VM lane's evidence.

## 15. Closeout

The eleven parts of `openspec/README.md#plan-closeout-requirements`, in order.
Closeout changes documentation only. A part that would need a code edit returns the
change to implementation.

- [ ] 15.1 **Comment hygiene.** Run `make check-comment-hygiene`. Any finding, or a
      comment Sections 2–14 added that still describes history, returns the change
      to implementation.
- [ ] 15.2 **Import placement.** Confirm that every import Sections 2–14 added is at
      module level, or carries a verified reason to stay local.
- [ ] 15.3 **Documentation compliance.** Re-check D1–D14 against `openspec/README.md`'s
      placement rules and `design.md`'s promotion record.
- [ ] 15.4 **Narrative compression.** Compress these task notes to final behaviour,
      material evidence, deferred work, and destinations.
- [ ] 15.5 **Roadmap currency**, in `docs/development/ROADMAP.md`:
      - Under "Goal 1 — Consolidate physical-resource authority in the provisioning
        service", the gap row "The real runner reports no structured
        terminal-failure evidence…" notes that successful results are read in
        either callback form. It stays open for failure classification.
      - Under "Payment qualification boundaries", record the gaps this change leaves
        open:
        - D6's exhausted teardown job;
        - where two lanes share a machine, D10's operational precondition, that a
          refresh or reopen under the same identity keeps a listing's pause;
        - D10's limits: successor listings are created unpaused, no permanent
          requirement states per-listing pause semantics, no test closes a paused
          listing by reconciliation and reopens it, and bare metal has no test of a
          paused listing refusing an opening;
        - the live lanes' state at closeout, as evidence or as named blockers.
      - "Goal 2 — Negotiate full compute capability, not GPU count alone" is
        unchanged by this change: D7 is withdrawn, and `gpu-optional-compute-shapes`,
        archived, delivered that scope.
      - Name the update in `design.md`'s promotion record.
- [ ] 15.6 **Campaign index currency.** Update this change's row in
      `openspec/changes/README.md` to `in closeout`, with notes stating what is true
      at closeout. Confirm that no dependency line or `Depends on` entry names this
      change, since D7's were removed with its withdrawal. Run
      `make check-change-index`, and name the update in the promotion record.
- [ ] 15.7 **Packaging.** Run `make check-packaging` and
      `make check-architecture-change CHANGE=repair-compute-purchase-recovery`. Run
      `make check-agent-skills` only if the change touched `.agents/`, `.claude/`, or
      `.codex/`; it is not planned to.
- [ ] 15.8 **End-to-end pipeline.** Record the pipeline run and its result:
      - the bare-metal lane's `e2e_bare_metal_mock_deal` and
        `e2e_bare_metal_payment_deal`;
      - the VM lane's `e2e_deal`, `e2e_deal_buyer_cli`, `e2e_listing_shapes`,
        `e2e_buy`, and `e2e_non_erc20_settlement`, which read the shipped-form
        default.

      Record the live lanes' qualification separately, as live evidence or as named
      blockers, never as pipeline evidence (`design.md`, "Live qualification"):
      - the bare-metal lane, a whole GPU machine bought through the buyer commands,
        `e2e_bare_metal_deal` or its commands, a bounded GPU computation by the
        tenant, teardown to `released`, a fresh SSH refusal, and restored capacity;
      - the VM lane, a GPU guest on an x86-64 host from the pinned image, a bounded
        GPU computation inside the guest, the normal release, a fresh SSH refusal,
        the GPU back at the host's driver baseline, and restored capacity.

      The two run on separate hosts, in parallel; D10's conditions apply only to a
      lane sharing a machine.
- [ ] 15.9 **Promotion**, per `design.md`'s promotion record:
      - `docs/development/ARCHITECTURE.md` "Release": the table's `failed` row splits
        into compensable and not.
      - `openspec/specs/physical-provisioning/architecture.md`:
        - "Durable jobs, transient workers": fact reading and linkage, and a
          bare-metal reclaim's diagnostic result, whose teardown the reclaim
          job's status decides;
        - "The host registry owns the connection": the tenant-facing port, and
          `ssh` served at version 2 alone, a stored version-1 host refused until it
          is submitted again;
        - "Proof-driven release": compensation, and the corrected `teardown_failed`
          requeue sentence, which says the requeue re-observes the same failed job
          and does not re-run it (D6).
      - `openspec/specs/fulfillment/architecture.md` "Durable persistence and
        recovery": the compensating teardown and its marker.
      - `docs/development/TESTING.md` "4. System Integration Tests (End-to-End)":
        mock output prints the shipped form for the job, and the VM scenarios use
        the default.
      - `docs/development/TESTING.md`, beside "Chart Render Tests", and
        `domains/vms/provisioning/iac/README.md` "Validation", whose list of syntax
        checks it extends: `make validate-playbooks` parses the `vm-management`
        role's task files, a capacity check's included, through the parse-only
        `vm-management-task-files.yaml`, since a syntax check does not follow
        `include_tasks`; it renders no Jinja and runs nothing (14.8, 14.14).
      - `docs/development/DEPLOYMENT_AND_CONFIG.md` "Definition documents", the
        host-inventory paragraph: `public_port=`; every `ssh` host connection,
        through the API or an inventory, at version 2; and a host stored at version
        1 moved forward by an update or an import.
      - `docs/bare-metal-seller-quickstart.md`:
        - "Define the selected site": the inventory example with `public_port=`, and
          the sentence on `public_host` rewritten to the buyer's endpoint the host
          record states, each field falling back to the connection's;
        - "Release-qualified deal evidence": the scenario's inputs, the pinned
          known-hosts file among them, `--run-id`, teardown to `released`, and
          revocation proven only by an authentication refusal.
      - `docs/seller-quickstart.md` "4. Prepare your KVM hosts": in step 2, that a
        VM guest's port is its forwarded or relay port, never the host's
        `public_port`; in step 3, the x86-64 host prerequisites.
      - `domains/vms/provisioning/iac/README.md`:
        - "Prerequisites": the x86-64 host prerequisites, how an operator moves the
          image pin, and the `vm-setup.yaml` warning;
        - "VM Management Operations (vm-management role)": `vm_passthrough_boot_gpu`,
          `vm_setup_wait_attempts`, `vm_setup_wait_interval_seconds`, and
          `vm_autostart`, beside the passthrough variables.
      - `docs/development/VALIDATION_RUNBOOK.md`, a new generic section on running
        live lanes (D10):
        - lanes on separate machines run in parallel, with source, build, and
          environment changes serialized;
        - lanes sharing a machine run in sequence, under the freeze and the
          per-listing pause;
        - read-backs in the site's held states, `reserved`, `leased`, `releasing`,
          `release_failed`, and `unmanaged` (`HELD_RESERVATION_STATES`), naming
          neither retired state;
        - each member's full `available` mapping compared with its `capacity`
          mapping;
        - every accepted deal drained, with no refund taken as proof;
        - the precondition that a refresh or reopen under the same identity keeps
          the pause.
      - `openspec/specs/README.md`: no new capability or companion, so no edit.
        Confirm it.
      - Complete the promotion record.
- [ ] 15.10 **Documentation citations.** Run
      `make check-doc-citations CHANGE=repair-compute-purchase-recovery`, then
      `openspec validate repair-compute-purchase-recovery --strict`.
- [ ] 15.11 **Archival.** Run `openspec archive repair-compute-purchase-recovery -y`,
      which merges the `physical-provisioning` and `fulfillment` deltas into
      `openspec/specs/`. The deltas were not promoted by hand, so `--skip-specs` is
      not used.
