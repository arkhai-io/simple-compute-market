# Tasks

Planned against the design settled in `design.md` and advanced by
`reviews/14-design.triage.md`; replanned against D16–D23, settled after section 1 returned
the change to design and advanced by `reviews/27-design.triage.md`. Section 1's tasks and
notes are kept as implemented; sections 2–8 were replanned against the reviewed design.
Every task answers to a decision (D1–D23, with D3a), a requirement of the delta
`specs/frp-grant-admission/spec.md`, or a repository obligation cited at the task:
`openspec/README.md#plan-closeout-requirements`, the task rules in `openspec/config.yaml`,
`docs/development/TESTING.md`'s levels, `docs/development/BUILD_AND_PACKAGING.md`, and
`AGENTS.md`.

The change is `admit-relay-proxies-by-grant` (D16, D17); the tool, its distribution,
console script, image, root targets, and capability keep the name `frp-grant-admission`
(D14). A command naming the change uses the change's name; a path or name of the tool or
the capability keeps the tool's.

Test levels follow `docs/development/TESTING.md`. **Unit**: one module in isolation, no
socket and no process. **Integration (in-process)**: the plugin's real HTTP server on an
ephemeral loopback port, sent requests shaped exactly as frps's server-plugin protocol
sends them; the caller is frps, so there is no typed client and frps's protocol is the
contract. **Integration (real frp)**: real `frps` and `frpc` processes against the
plugin, which skip without binaries in the default suite and run in the gate, as the
native Ansible tests do (`TESTING.md`, "Ansible Syntax and Native Checks"). No
`e2e-tests` scenario exercises the plugin: nothing in the deployed stack runs a relay with
it until `prove-relay-provisioning`, whose real lanes do. No section owes one.

Every path below is under `tools/frp-grant-admission/` unless it names another root.
The tool depends on `cryptography`, PyJWT, and the standard library only (D4); nothing in
it names hosts, leases, sites, or SCM. Public-repository discipline (`AGENTS.md`) applies
to the vector, the examples, and every note: the only keys are RFC 8032 §7.1's test keys,
labelled as test values never to be used on any network, and every address is loopback
or a documentation example.

Order: sections 1–4 deliver the plugin proven in-process — configuration, verification
and the vector, the server, and the README specification; sections 5–7 deliver real frp,
CI with the floor run, and shipping; section 8 is the closeout. Section 5 needs sections
1–3; section 6 needs section 5; section 7 needs section 3. No dependency gates
implementation. If a premise about frp that section 5 tests is false — frps failing
closed, frpc retrying a refused proxy, a refusal reason reaching frpc, a reload leaving
unchanged proxies registered — the change returns to design rather than being worked
around (D15, D21).

Permanent documentation outside the tool — the capability's `architecture.md`,
`openspec/specs/README.md`, `ARCHITECTURE.md`, and `TESTING.md` — is written at closeout
(8.9). The tool's README and `tools/README.md` are deliverables of their sections.

Notes were compressed at closeout (8.4) to final behaviour, evidence, deferrals, and
destinations; implementation's choices, declined suggestions, and what it left unproven
are in `design.md`, "Implementation record".

## 1. The project and its configuration

Delivers the tool's project and the configuration loader: TOML, issuers grouping keys,
thumbprint key ids, the loopback listen rule, and every load refusal (D3, D3a, D4, D8's
Python floor, D13, D20; delta "Issuers bind keys to an audience and a port range", and the
listen-address rule of "Configuration reloads only when valid").

Files: `pyproject.toml`, `uv.lock`, `Makefile`, `LICENSE`, `.gitignore`,
`src/frp_grant_admission/__init__.py`, `src/frp_grant_admission/config.py`,
`tests/unit/test_config.py`, `tests/rfc8032.py`, `examples/config.toml`.

- [x] 1.1 Create the project as `docs/development/BUILD_AND_PACKAGING.md` lays one out:
      distribution `frp-grant-admission`, import package `frp_grant_admission` at
      `src/frp_grant_admission`, hatchling with `packages = ["src/frp_grant_admission"]`
      and nothing else, `requires-python = ">=3.11"`, `license = "MIT"`, version `0.1.0`,
      runtime dependencies `cryptography` and `PyJWT` only, `pytest` in the `dev` group,
      and a console script `frp-grant-admission`. Copy the root `LICENSE` beside it. The
      `Makefile` exports `UV_PYTHON` from `../../.python-version` and has `test`; it needs
      no `reinit`, since its lock installs nothing from the wheelhouse. Lock with
      `make lock PROJECTS="tools/frp-grant-admission"`. (D4, D8)
      Note: as planned; `cryptography>=42`, `PyJWT>=2.8.0`, the console script
      `frp_grant_admission.cli:main`, `readme` added in section 4. The lock resolves
      cryptography 50.0.2 and PyJWT 2.15.1. A first lock needs a stub `uv.lock` holding
      `version = 1` and `requires-python`, since `scripts/uv_project.py lock` needs one
      and uv refuses an empty file; moving a locked third-party package means relocking
      from that stub.
- [x] 1.2 **Decision gate on PyJWT's `iat`.** Find the lowest PyJWT release whose
      `jwt.decode` refuses, with zero leeway, an `iat` later than the clock, as D12 step 7
      and the delta's "A grant is not yet valid" require of "`nbf` and `iat` validated as
      PyJWT does"; declare `PyJWT>=` that release and record it in this task's note. If no
      release does, stop: the design must decide whether the plugin checks `iat` itself,
      and the change returns to design (`openspec/README.md#open-questions-and-prescribed-tasks`).
      (D8, D12)
      Note: 2.6.0 is the first release refusing a future `iat` and refusing at exactly
      `exp`; `strict_aud` first appears in 2.8.0; no release takes a clock. Evidence:
      each release locked in turn and its `jwt/api_jwt.py` read. Correction (replanned):
      the gate is settled by the design — D18 makes the time checks the plugin's own and
      D20 keeps `PyJWT>=2.8.0` for `strict_aud` alone. Done: `pyproject.toml` declares
      `PyJWT>=2.8.0`.
- [x] 1.3 `config.py` loads a TOML file with `tomllib` into an immutable configuration:
      `listen` and a list of issuers, each with `name`, `audience`, `ports.start`,
      `ports.end`, and `keys`, each key a `public_key` — single-line standard base64 of
      the DER SubjectPublicKeyInfo of an Ed25519 key. Each key's id is derived at load as
      its RFC 7638 JWK thumbprint (base64url, unpadded, SHA-256 of
      `{"crv":"Ed25519","kty":"OKP","x":"<base64url raw key>"}`), and the configuration
      maps each id to its key and issuer. Types are strict: a quoted port is an error.
      (D3, D3a, D13)
      Note: `load_config(path)` and `parse_config(text)` return a frozen `Config` with a
      read-only thumbprint-to-`Key` map; keys must be canonical (`design.md`,
      "Implementation record").
- [x] 1.4 Loading collects every problem and refuses the file, naming each: a key listed
      twice (by thumbprint, in any issuers); two issuers with the same `name`; two
      issuers whose ranges overlap, naming both; an issuer with no keys; a range outside
      1–65535 or with `end` before `start`; a key that is not Ed25519 SPKI DER base64;
      a missing or mistyped field; and a `listen` that is not an IPv4 address in
      `127.0.0.0/8` or `[::1]` with a port from 1 to 65535 — a hostname such as
      `localhost` included, decided without a resolver. (D3, D13; 14 F2)
      Note: beyond the plan, an unknown field at any level is refused; `listen` is parsed
      with `ipaddress` alone; an unreadable or non-TOML file is one problem naming why.
- [x] 1.5 `examples/config.toml` is D13's example, with RFC 8032's TEST 1 public key and
      a comment saying it is a test value never to be used on any network. (D13;
      `AGENTS.md` public-repository discipline)
      Note: the second issuer carries RFC 8032's TEST 2 key, labelled the same way; the
      issuers are `issuer-a` and `issuer-b` since section 4.
- [x] 1.6 `.gitignore` ignores the tool's frp cache directory (section 5) and its
      environment. (D5)
      Note: the cache directory is `.frp-cache/`.
- [x] 1.7 Unit (`tests/unit/test_config.py`): the example loads; the TEST 1 key's derived
      id is RFC 8037 Appendix A.3's `kPrK_qmxVWaYVA9wwBF6Iuo3vVzz7TxHCTwXBygrS4k`; two keys
      in one issuer both resolve to it; each refusal in 1.4 is reported, and a file with
      several problems reports all of them; `listen` values `0.0.0.0:7300`,
      `192.0.2.1:7300`, `localhost:7300`, and `[::]:7300` are refused, and
      `127.0.0.1:7300`, `127.1.2.3:7300`, and `[::1]:7300` load.
      Note: unit, all pass, each case above and every structural refusal; the RFC 8032
      keys live in `tests/rfc8032.py`.
- [x] 1.8 Verification: `make -C tools/frp-grant-admission test` (unit); `make
      check-packaging` (a new project and lock).
      End-to-end: none (see the preamble).
      Note: unit, 45 passed; `make check-packaging` passes. End-to-end: none.
- [x] 1.9 Re-check section 1 after the rename and the merge of `dev` (D16, D21): the work
      of 1.1–1.8 is unchanged; `make -C tools/frp-grant-admission test` (unit) passes;
      `make check-packaging` passes; `make check-change CHANGE=admit-relay-proxies-by-grant`
      reports no failure but its citations check's, which may name only files the change
      creates — comment hygiene included, now that no code line contains the change's
      name. Then check 1.1–1.9 and commit the section.
      Note: unchanged since `2c4e080b8`; unit, 55 passed after the fresh-context check
      added the overlap fix (1.4) and structural cases; `make check-packaging` passes;
      `make check-change` 5 of 6, citations naming only files the change creates.
      End-to-end: none.

Section 1 first stopped, its work done, because `make check-comment-hygiene` refuses any
code line containing a change's name and the change shared the tool's name. The design
settled it by renaming the change, not the tool (D16, D17); `reviews/27-design.triage.md`
records comment hygiene passing on the renamed change. Section 1 is completed by 1.9.

## 2. Grant verification and the test vector

Delivers the grant check of D12 steps 5–11 — the plugin's own header, time, and
claim-type checks around PyJWT's parsing and signature — its reason codes, and the
published vector with verification, signing, and thumbprint cases (D2, D7, D12, D18, D19,
D22; delta "A proxy is admitted only for its granted port" for the grant's checks, and
"The plugin owns its grant specification").

Files: `src/frp_grant_admission/grant.py`, `src/frp_grant_admission/reasons.py`,
`vector/frp-grant-1.json`, `tests/unit/test_grant.py`, `tests/unit/test_vector.py`,
`tests/vector_builder.py`.

- [x] 2.1 `reasons.py` defines the stable reason codes of D12 — `malformed_request`,
      `operation_not_supported`, `proxy_type_not_allowed`, `group_not_allowed`,
      `port_invalid`, `grant_missing`, `grant_malformed`, `grant_type_unsupported`,
      `key_unknown`, `signature_invalid`, `claim_missing`, `audience_mismatch`,
      `grant_expired`, `grant_not_yet_valid`, `port_mismatch`, `port_outside_range` —
      each with its short text. (D10, D12)
      Note: `Reason` is an enum of `(code, text)`; `reason.reply` is frps's
      `"<code>: <text>"`. Unit, `tests/unit/test_reasons.py`: exactly these sixteen, in
      order — passes. The two mappings the design left open are recorded in D12.
- [x] 2.2 `grant.py` verifies a grant string against a configuration, a remote port, and
      a clock passed in by the caller, in D12's order, refusing at the first failure:
      (a) at most 4 KiB, else `grant_malformed`; (b) the unverified header's `kid` names
      a configured key, else `key_unknown`; (c) the unverified header's `typ` is exactly
      `frp-grant+jwt`, else `grant_type_unsupported`, and it has no `crit`, else
      `grant_malformed` — before PyJWT verifies anything (D22); (d) `jwt.decode_complete`
      with `algorithms=["EdDSA"]`, the key's issuer's audience, and `options={"require":
      ["exp", "aud", "port"], "strict_aud": True, "verify_exp": False, "verify_nbf":
      False, "verify_iat": False, "verify_sub": False, "verify_jti": False}`, PyJWT's
      errors mapped to `signature_invalid`, `claim_missing`, `audience_mismatch`, and
      `grant_malformed`; (e) `exp`, and `nbf` and `iat` when present, are JSON integers
      and not booleans, else `grant_malformed`, and against the passed clock `now ≥ exp`
      is `grant_expired` and an `nbf` or `iat` later than `now` is
      `grant_not_yet_valid`, with no leeway (D18); (f) `sub` and `jti`, when present, are
      strings, else `grant_malformed` (D19); (g) `port` a JSON integer and not a boolean,
      equal to the remote port, else `port_mismatch`, and inside the issuer's range, else
      `port_outside_range`. The result is a verdict, its reason, the issuer's name, and the `kid`, `sub`,
      `jti`, and `exp` it read, with whether they were verified. Unknown claims are
      ignored. The check never reads the system clock, and no time comparison is left to
      PyJWT. (D2, D12, D18, D19, D22)
      Note: `check_grant(grant, config, remote_port, now)` returns a frozen `GrantResult`;
      `verified` is true once the signature, audience, required claims, and claim types
      pass, so a grant refused for its time or port still reports verified claims.
      Error mapping, the header reader, and the surrogate and `RecursionError` paths are
      in `design.md`, "Implementation record". Correction: "never reads the system clock"
      holds for the plugin's own code (PyJWT reads it, with every time check off).
      Correction (section 6): (d) is called on a `jwt.PyJWT()` instance, since PyJWT
      2.8.0 exports no module-level `decode_complete`; same function and options.
- [x] 2.3 `vector/frp-grant-1.json`: the specification's version (`frp-grant 1.0`); the
      TEST 1 key's seed and public key, labelled a test value never to be used on any
      network; a configuration of two issuers with adjacent ranges; verification cases
      (time, proxy type, remote port, token, verdict, reason); signing cases (key,
      header, claims, exact token) — one with every claim, one with only `aud`, `exp`,
      and `port`; and the thumbprint case. Tokens are JCS-serialized (RFC 8785) header
      and claims, unpadded base64url, signed with the TEST 1 key.
      `tests/vector_builder.py` writes the file from its cases, so a case is added by
      editing the builder, and `test_vector.py` fails when the committed file differs
      from what the builder writes. (D7)
      Note: the vector carries RFC 8032's TEST 1 and TEST 2 (issuer `issuer-a`,
      6100–6199) and TEST 3 (`issuer-b`, 6200–6249), each with seed, raw key, SPKI, and
      `kid`; cases replay at 2027-01-01T00:00:00Z unless stated. Regenerate with `uv run
      python -m tests.vector_builder` from the tool's directory; on a difference,
      `test_vector.py` writes the builder's output to its temporary directory and names
      it.
- [x] 2.4 The verification cases cover every grant reason in 2.1 that the grant check can
      return, and these named cases: valid; a second key of the same issuer; wrong port;
      outside the issuer's range; inside the other issuer's range; wrong audience; an
      `aud` list (`strict_aud`); forged signature; unknown `kid`; `typ` `JWT`; `typ`
      absent; `crit` present on a correctly signed grant; `crit` present on a forged grant,
      refused as `grant_malformed`, not `signature_invalid` (D22); `port` as a string;
      `port` as `true`; missing `exp`; `exp` as a string, `exp` as a float, `exp` as
      `true`, and `iat` as a string, each refused as `grant_malformed` (D18); an integer
      `jti` and an object `sub`, each refused as `grant_malformed` (D19); a padded token
      admitted; an unknown claim admitted; and D12's three boundary cases — one second
      before `exp` admitted, exactly `exp` refused as `grant_expired`, and an `iat` one
      second ahead refused as `grant_not_yet_valid` — with an `nbf` one second ahead
      refused as `grant_not_yet_valid` too. (D7, D12, D18, D19, D22; 14 F1)
      Note: 38 verification cases, every named case above and more. Departure: the 4 KiB
      cap is proven in `test_grant.py`, not the vector (`design.md`, "Declined").
- [x] 2.5 Unit (`tests/unit/test_vector.py`): every verification case returns its
      verdict and reason through `grant.py`, at the case's time; every signing case's
      token is reproduced byte for byte by serializing its header and claims as JCS and
      signing with the TEST 1 key; the thumbprint case matches `config.py`'s derivation;
      the committed file equals the builder's output. Unit (`tests/unit/test_grant.py`):
      the result's `verified` is false and its `kid`, `sub`, and `jti` are the token's for
      a forged grant, and absent for a malformed one; a grant whose `exp` is before the
      wall clock is admitted when the passed clock is earlier than its `exp`, and one whose
      `iat` is after the wall clock is admitted when the passed clock is later, proving no
      time check is PyJWT's and the system clock is never read. (D18)
      Note: unit, all pass. `test_vector.py` reproduces each signing case with its own
      JCS from the file's seeds and cross-checks every key entry; `test_grant.py` covers
      the result fields, the 4 KiB cap (4096 bytes admitted, one more refused), and
      clocks in 2001 and 2100 — showing no verdict depends on the wall clock.
- [x] 2.6 Verification: `make -C tools/frp-grant-admission test` (unit).
      End-to-end: none (see the preamble).
      Note: unit, 116 passed; `make test` and `make check-packaging` pass; `make
      check-change` 5 of 6, citations naming only files the change creates. End-to-end:
      none. Round-1 triage fix (41 F1): a third signing case, "non-ASCII and control
      characters" (`sub` `hôte-€-1`, a `jti` with U+1F600 and U+000F), the builder's JCS
      held to RFC 8785 §3.2.2.2's example, and a test that the signing cases keep a BMP
      non-ASCII, a non-BMP, and a control character. Evidence: unit 203 passed, 15
      skipped (real frp); `make test-floor` 189 passed at PyJWT 2.8.0 and
      `cryptography` 42.0.0; `make test` and `make check-packaging` pass.

## 3. The server: requests, decisions, logging, and reload

Delivers the HTTP endpoint frps calls, request handling and answers, decision logging,
SIGHUP reload, and the `serve` and `check` commands (D6, D8, D9, D10, D12 steps 1–4 and
its answers, D18's system clock; delta "A proxy is admitted only for its granted port" for
the request's checks, "The plugin holds no state and calls nothing", "Configuration
reloads only when valid", and "Every decision is explained and logged").

Files: `src/frp_grant_admission/server.py`, `src/frp_grant_admission/decision_log.py`,
`src/frp_grant_admission/cli.py`, `tests/integration/test_server.py`,
`tests/unit/test_request.py`, `tests/unit/test_cli.py`.

- [x] 3.1 `server.py` serves `http.server.ThreadingHTTPServer` on the configured loopback
      address, answering `POST /` only: a body of at most 64 KiB read within a 5-second
      socket timeout, else `malformed_request`; valid JSON with `op` `NewProxy`, else
      `malformed_request` or `operation_not_supported`; `content.proxy_type` exactly
      `tcp`, else `proxy_type_not_allowed`; `content.group` absent or empty, else
      `group_not_allowed`; `content.remote_port` an integer from 1 to 65535, else
      `port_invalid`; the grant from `content.metas.grant` only, else `grant_missing` —
      `content.user.metas` is never read; then section 2's check, given the system clock
      read once per request, the server's clock being injectable for tests. An admission
      answers HTTP 200 `{"reject": false, "unchange": true}`; a refusal answers HTTP 200
      `{"reject": true, "reject_reason": "<code>: <text>"}`. Each request reads the
      configuration reference once, so it finishes under the configuration it started
      with. The server holds no other state and makes no outbound call. (D6, D8, D12, D18)
      Note: the request checks are their own pure module, `request.py` (`decide_request`,
      `decide_body`, returning a `Decision`); `server.py` holds `Plugin` (configuration
      reference, reload, clock floored to whole seconds) and `PluginServer`. Path, method,
      `Content-Length`, and bind behaviour are in `design.md`, "Implementation record".
- [x] 3.2 `decision_log.py` writes one JSON line to stderr per decision, in D10's shape —
      `ts`, `event` (`admit` or `refuse`), `reason` on a refusal, `proxy`, `type`,
      `remote_port`, `issuer` where known, `kid`, `sub`, `jti`, `exp` where present, and
      `verified` — and one line per configuration load or reload, listing each issuer's
      name, range, and key thumbprints, or every problem found. It never writes the grant
      or the request's metadata. (D10)
      Note: the line shapes are stated in the README's "The log". Unit,
      `tests/unit/test_decision_log.py`: an admission's exact line, a forged grant logged
      unverified with no segment of the grant, no client-wide metadata, a quote and a
      newline staying one line, `NaN` and infinite values as text, deep nesting as a
      placeholder, and the three configuration lines — passes.
- [x] 3.3 SIGHUP re-reads the file through section 1's loader: a valid file replaces the
      configuration reference in one assignment; an invalid one leaves the running
      configuration and logs every problem. `listen` is bound once at startup: a reload
      that changes it applies the rest and logs that the new address takes effect at
      restart. (D9; 14 F2)
      Note: `install_reload_on_sighup(plugin)`, installed by `serve` after binding; any
      exception in a reload keeps the running configuration and never ends
      `serve_forever`. Unit, `tests/unit/test_reload_signal.py`: a raising reload,
      signalled twice, is reloaded twice with nothing raised — passes.
- [x] 3.4 `cli.py`: `frp-grant-admission serve --config <path>` refuses to start, exiting
      non-zero with every problem, on a file that does not load; `frp-grant-admission
      check <path>` loads a file without touching a running plugin, prints each issuer
      with its range and its keys' thumbprints, and exits non-zero naming every problem
      when it does not load. (D9)
      Note: `main(argv)` returns the exit status; `serve` writes one `config_refused`
      line and exits 1 on a file that does not load or an address it cannot bind; `check`
      prints `listen`, each issuer, and an indented `key <thumbprint>` per key.
- [x] 3.5 Unit (`tests/unit/test_request.py`): each request refusal of 3.1 from a request
      dict, including a grant only in `content.user.metas`, `remote_port` 0, a non-empty
      `group`, `op` `Login`. Unit (`tests/unit/test_cli.py`): `check` prints thumbprints
      for the example and fails naming each problem of an invalid file; `serve` exits
      non-zero on one.
      Note: unit, all pass: every request refusal and its answer, the request checks
      deciding before a grant is read, `check` and `serve` on the example, a
      four-problem file, and a missing file. The frps request shape is shared from
      `tests/frps_request.py`.
- [x] 3.6 Integration, in-process (`tests/integration/test_server.py`), the server on an
      ephemeral `127.0.0.1` port with a fixed clock, sent bodies shaped as frps's
      `NewProxy` request: a valid grant is answered with an admission, and its log line
      has `verified: true`; a forged grant is refused as `signature_invalid`, and its log
      line has `verified: false` and contains neither the grant nor the reply's token; a
      body over 64 KiB and a body that is not JSON are refused as `malformed_request`; a
      `GET` is not answered as an admission; after the file gains an issuer and the
      process receives SIGHUP, that issuer's grant is admitted without a restart; after
      the file is made invalid and SIGHUP is sent, the earlier configuration still admits
      and every problem is logged; a reload changing `listen` keeps the bound address and
      logs that it waits for a restart. Waits are bounded and observe the log or the
      answer, never a sleep.
      Note: integration (in-process), all pass: 12 cases in `test_server.py` — each case
      above, a missing `Content-Length`, a stalled body, `[::1]`, and another path — and 2
      in `tests/integration/test_start.py` (`start` binding, its startup line, SIGHUP to
      the process, and an address in use). Waits are on a condition with a 5-second
      bound.
- [x] 3.7 Verification: `make -C tools/frp-grant-admission test` (unit and in-process
      integration).
      End-to-end: none (see the preamble).
      Note: unit and in-process integration, 174 passed; `make check-packaging` and `make
      test` pass. End-to-end: none.

## 4. The README specification

Delivers the tool's README as the published grant specification, after sections 1–3
prove the behaviour it states (D2, D3, D3a, D7, D9, D10, D12, D13, D14's README part,
D18, D19, D22; delta "The plugin owns its grant specification").

Files: `README.md`, `pyproject.toml` (`readme`).

- [x] 4.1 `README.md` states, naming no concept of any particular issuing system: what
      the plugin does and does not (D1, D6); the grant — header, claims, required and
      optional, their types (`exp`, `nbf`, `iat` JSON integers; `sub` and `jti` strings),
      where it is carried in frpc's configuration and on the wire (D2, D18, D19); `typ`
      as the major version and the compatibility rule, with the specification's version
      `frp-grant 1.x`, and that `typ` and `crit` are checked before the signature (D2,
      D22); key ids as RFC 7638 thumbprints (D3a); signing as JCS and unpadded base64url,
      required of signers only (D7); expiry checked on the relay's clock with no leeway,
      and the boundary (D12, D18); the configuration format with D13's example, the
      loopback rule, and the frps `[[httpPlugins]]` stanza (`path = "/"`, `ops =
      ["NewProxy"]`) (D13); reload by SIGHUP, `listen` at restart only, and `check` (D9);
      the reason codes and the decision log's fields (D10, D12); the vector's format and
      the conformance a signer owes (D7); and D3's operating rules — drain before
      refusing what was admitted, a signer granting only within its range, ranges within
      frps's `allowPorts`. `pyproject.toml` gains `readme = "README.md"`. (D14)
      Note: the README is version 1.0 within `frp-grant 1.x`, matching the vector, and
      holds every part above; sections 5–7 added the frp version, the pins format, the
      floor run, and installation. The example issuers are `issuer-a` and `issuer-b`.
      It keeps "relay" for the frps server; closeout judged that compliant (`design.md`,
      "Closeout judgements").
- [x] 4.2 Verification: every section, field, type, and reason code the README names
      exists in the code and the vector (read against sections 1–3); `make
      check-comment-hygiene`; `make check-packaging` (`readme` added).
      End-to-end: none.
      Note: read against `grant.py`, `reasons.py`, `config.py`, `decision_log.py`, and
      the vector, with corrections made while reading. Unit and in-process integration,
      174 passed; `make check-comment-hygiene`, `make check-packaging`, and `make test`
      pass. End-to-end: none.

## 5. The real-frp gate

Delivers the pins file, the checksum-verified fetch, and the real-frp tests, run by the
tool's gate (D5; delta "Admission fails closed", "The plugin is proven against pinned
frp", and the real-frp scenarios of "A proxy is admitted only for its granted port", "The
plugin holds no state and calls nothing", and "Every decision is explained and logged").

Files: `frp-pins.toml`, `tests/frp_fetch.py` (the fetch is test tooling and does not
ship in the wheel), `tests/frp/conftest.py`, `tests/frp/test_real_frp.py`,
`tests/unit/test_frp_fetch.py`, `Makefile`, `README.md` (the supported frp version and the
pins file's format).

- [x] 5.1 `frp-pins.toml` names frp 0.61.1 and, for `linux_amd64`, the official release
      archive's URL and SHA-256, the SHA-256 taken from a download of that archive and
      recorded here, never read from the release's checksums file at run time. Its format
      gains platform entries without changing shape, and the README states it and the
      supported version. (D5)
      Note: `version` and one `[archives.<os>_<arch>]` table per platform (`url`, https;
      `sha256`, lowercase hex); unknown members refused. SHA-256 `bff260b6…2c40`, taken
      from the archive downloaded and cross-checked once against the release's published
      checksums file, digit for digit. The README's "The frp it is tested against" states
      the version, the tests, the format, and frpc 0.61.1's 30-second retry.
- [x] 5.2 The fetch downloads the pinned archive for the running platform, verifies its
      SHA-256 against the pin before extracting anything, extracts `frps` and `frpc` into
      the ignored `.frp-cache/`, and reuses a cached binary only when its archive
      verified. `FRPS_BIN` and `FRPC_BIN` override it. A platform with no pin and no
      override makes the real-frp tests skip in the default suite. Unit
      (`tests/unit/test_frp_fetch.py`), against a local archive file: a matching archive
      extracts both binaries; a mismatching one fails naming both digests and extracts
      nothing. (D5; delta "An archive does not match its pin")
      Note: `tests/frp_fetch.py`; the cached archive is verified on every use, a download
      lands as `.part` until it verifies, and each binary is written under its own name
      whatever the archive's paths. Beyond the plan, the default suite never fetches or
      reads the cache. Unit, 18 cases, all pass.
- [x] 5.3 Fixtures (`tests/frp/conftest.py`) start the plugin, `frps`, and `frpc` as
      processes, every port chosen at runtime on `127.0.0.1` — frps's bind port, the
      plugin's, `allowPorts`, the issuers' ranges, the remote ports — with frps's
      `[[httpPlugins]]` pointing at the plugin; tokens are signed with the TEST 1 key. A
      proxy's state is read from frpc's admin `/api/status` with a bounded wait, never a
      sleep; the wait for frpc's retry of a refused proxy is sized to frpc 0.61.1's retry
      interval, with a comment saying why it is that long. Without binaries every test in
      `tests/frp/` skips. (D5)
      Note: helpers in `tests/frp/stack.py`. Ports all distinct and chosen at runtime;
      polls bounded at 15 s (60 s for a retry, frpc 0.61.1's measured retry being
      30.1–30.2 s); both binaries must report the pinned release by `--version`; under
      `FRP_GATE=1` a missing binary or any skip fails the run.
- [x] 5.4 Integration, real frp (`tests/frp/test_real_frp.py`): a valid grant admitted,
      and traffic reaching a local listener through the remote port; refused, with the
      reason frpc reports — no grant, a forged signature, the wrong port, the wrong
      audience, an expired grant, a port outside its issuer's range, one issuer's grant for
      another issuer's range, a non-`tcp` proxy (`stcp`), and a grant only in client-wide
      metadata. (D5; delta "A valid grant is presented", "A proxy carries no grant of its
      own", and the refusal scenarios; "A grant is refused")
      Note: integration (real frp), all pass. The admitted proxy carries bytes to an
      echo service and is logged `admit`, `verified: true`; each refusal reaches frpc's
      `err` with its reason code and is logged with the same reason.
- [x] 5.5 Integration, real frp: frps refuses the proxy while the plugin is stopped, while
      a stand-in answers HTTP 500, and while it answers a malformed body; and in each
      case, once the plugin answers again, the same frpc's proxy is admitted on its own
      retry without restarting frpc. (D5, D9; delta "Admission fails closed")
      Note: integration (real frp), all pass; the same frpc reports `running` about 30 s
      after the plugin answers and carries traffic. Premise held.
- [x] 5.6 Integration, real frp: a registered proxy keeps running after a SIGHUP reload
      removes its key, and is refused once frpc is restarted — the reconnect forced by
      restart, not by waiting for a heartbeat. (D3's drain premise; delta "A registered
      proxy is not rechecked")
      Note: integration (real frp), passes: a held connection and a new one carry
      traffic after the reload; a new frpc from the same file is refused with
      `key_unknown`. Premise held.
- [x] 5.7 Integration, real frp: an frpc reload adding a second proxy beside a registered
      one produces exactly one decision line in the plugin's log, for the new proxy.
      (D5; delta "A client reload adds a proxy")
      Note: integration (real frp), passes, through `frpc reload`: exactly one `admit`,
      for the new proxy, with a held connection through the first carrying traffic
      across the reload. Premise held; the count's limit is in `design.md`, "Left
      unproven".
- [x] 5.8 The tool's `make test-frp` fetches the binaries and runs `tests/frp/`, failing
      when any test skips or none runs; its `make test` runs everything else and passes
      with the network off. (D5; delta "The gate runs without frp")
      Note: `test-frp` is `FRP_GATE=1 uv run pytest tests/frp -q -rs`; `test` reads no
      binaries but the overrides, so never reaches the network.
- [x] 5.9 Verification: `make -C tools/frp-grant-admission test` with the network off
      (unit, in-process integration; real-frp tests skip); `make -C
      tools/frp-grant-admission test-frp` (real-frp integration, no skips). If 5.5, 5.6,
      or 5.7 shows an frp premise false, stop and return the change to design (D15).
      End-to-end: none (see the preamble).
      Note: `make test` — 192 passed, 15 real-frp skipped; offline by construction (the
      step could not switch the network off). `make test-frp` — 15 passed, none skipped,
      about 100 s. No frp premise was false. End-to-end: none. Round-1 triage fix (42
      observation): the gate prints the binaries' provenance; `make test-frp` printed
      `frp_0.61.1_linux_amd64.tar.gz, verified against its pin: SHA-256 bff260b6…2c40`.

## 6. Repository integration, CI, the floor run, and the `tools/` boundary

Delivers the tool in `make test` and CI, the gate job with the floor run, the guard
standing in for `check-architecture`, and `tools/README.md`'s account of standalone
components (D4, D5, D23; delta "The plugin owns its grant specification" for the floor
run, scenario "The vector runs at the declared floors").

Files: `tools/frp-grant-admission/Makefile`; the root `Makefile`;
`.github/workflows/tests.yml`; `tools/frp-grant-admission/tests/unit/test_structure.py`;
`tools/README.md`.

- [x] 6.1 The tool's `make test-floor` runs `tests/unit` — the vector included — with
      each runtime dependency, PyJWT and `cryptography`, resolved at the lowest release
      `pyproject.toml` declares, as uv's `lowest-direct` resolution gives it, in an
      environment apart from the project's: the committed `uv.lock` and `.venv` are left
      untouched. It prints the installed PyJWT and `cryptography` versions and fails
      unless they equal the floors `pyproject.toml` declares, so the run can never test
      the lock by mistake. It needs the network, and is not part of `make test`. (D23;
      27 F2)
      Note: `.floor/.venv` with `--resolution lowest-direct`, then `python -m
      tests.floor` (prints and checks the floors) and `pytest tests/unit`. The floor run
      found PyJWT 2.8.0 lacks module-level `decode_complete`; fixed in `grant.py` (2.2's
      correction). Unit at the floors: 186 passed; `uv.lock` unchanged.
- [x] 6.2 The root `Makefile` gains `test-frp-grant-admission` (`$(MAKE) -C
      tools/frp-grant-admission test`), appended to the prerequisites of `test`;
      `test-frp-grant-admission-frp`, running the tool's `test-frp`; and
      `test-frp-grant-admission-floor`, running the tool's `test-floor`. `tests.yml`'s
      matrix appends `test-frp-grant-admission` in the same position, which
      `scripts/tests/test_tests_workflow.py` holds equal to `make test`'s targets. (D5,
      D23)
      Note: as planned; the matrix test passes in `make test-release-tooling`.
- [x] 6.3 `tests.yml` gains a job, `frp · real-frp gate`, that checks out, sets
      `UV_PYTHON` from `.python-version` under checkout's condition, installs uv 0.12.19
      as the matrix does, and runs `make test-frp-grant-admission-frp` and `make
      test-frp-grant-admission-floor`. It is in `tests.yml` because that is the workflow
      `scripts/ci_evidence.py` may dispatch. `make check-python-version` passes on the
      edited workflow. (D5, D23; `BUILD_AND_PACKAGING.md`, "One Python version")
      Note: job `frp-grant-admission-gate`; the floor step runs `if: ${{ !cancelled()
      }}` so a real-frp failure does not hide it. `make check-python-version` passes;
      CI evidence in 6.6.
- [x] 6.4 Unit (`tests/unit/test_structure.py`), standing in for `check-architecture`,
      which skips `tools/`: the tool's `uv.lock` resolves no package from the wheelhouse,
      its `pyproject.toml` declares only `cryptography` and `PyJWT` at runtime, each with
      a lower bound and no upper bound, and every import under `src/` is of the standard
      library, `jwt`, `cryptography`, or the package itself. (D4, D23)
      Note: unit, 8 cases, all pass, including no optional dependencies and every
      absolute import at any nesting.
- [x] 6.5 `tools/README.md` gains a section: `tools/` also holds standalone
      infrastructure components — not market runtime services, depending on no internal
      package, intended for their own repositories — naming `frp-grant-admission`, its
      `make test`, `make test-frp`, and `make test-floor`, the root targets, and the gate
      job; the opening paragraph's "not part of the market runtime services" is kept true
      by saying what a standalone component is instead. (D4)
      Note: as planned, the `scripts/` wrapper paragraphs scoped to the developer and
      validation tools. The tool's README gained the floor run's sentence (D23).
- [x] 6.6 Verification: `make -C tools/frp-grant-admission test-floor` (unit at the
      floors: PyJWT 2.8.0 and `cryptography` 42.0.0 printed, every case passing, `git
      status` showing `uv.lock` unchanged); `make test-frp-grant-admission`; `make
      test-release-tooling` (`scripts/tests`, including the matrix test); `make test`;
      `make check-packaging`; `make check-python-version`.
      Owed by validation: `tests.yml`, job `test · test-frp-grant-admission` — passes; and
      job `frp · real-frp gate` — the fetch verifies frp 0.61.1's `linux_amd64` archive
      against its pin, `tests/frp/` passes with no test skipped, and the floor run prints
      PyJWT 2.8.0 and `cryptography` 42.0.0 and passes.
      End-to-end: none (see the preamble).
      Note: `test-floor` 186 passed at PyJWT 2.8.0 and `cryptography` 42.0.0, `uv.lock`
      unchanged; `make test-frp-grant-admission` 200 passed, 15 skipped; `make
      test-release-tooling` 1816 passed; `make test`, `make check-packaging`, `make
      check-python-version` pass; `make test-frp-grant-admission-frp` 15 passed. Owed
      observations met in validation 54 (8.8). End-to-end: none.

## 7. Shipping: the wheel, the image, and the systemd example

Delivers the plain program and the image (D11, D13's network-namespace note).

Files: `tools/frp-grant-admission/Dockerfile` and its ignore file, if one is needed;
`tools/frp-grant-admission/examples/frp-grant-admission.service`;
`tools/frp-grant-admission/README.md`; the tool's `Makefile`; the root `Makefile`.

- [x] 7.1 The tool's `make build` builds its wheel. `examples/frp-grant-admission.service`
      runs `frp-grant-admission serve --config /etc/frp-grant-admission/config.toml` with
      `ExecReload=/bin/kill -HUP $MAINPID` and the hardening `frps.service.j2` carries.
      (D11)
      Note: `make build` is `uv build --wheel --out-dir dist`; the unit runs
      `/opt/frp-grant-admission/bin/frp-grant-admission`, `Before=frps.service`, with
      frps's hardening and, beyond the plan, `DynamicUser=yes`. The wheel holds the
      package, the entry point, and the licence, no tests. The unit was not run under
      systemd.
- [x] 7.2 The `Dockerfile` follows `BUILD_AND_PACKAGING.md`'s "Images": `ARG
      PYTHON_VERSION` defaulting to the root declaration before the first `FROM`; a uv
      builder installing the committed lock unchanged; a `python:${PYTHON_VERSION}-slim`
      runtime for `linux/amd64` running as a non-root user; the tool's version as the
      `org.opencontainers.image.version` label; entrypoint `frp-grant-admission serve
      --config <path>`. It passes `make check-uv-setup`, `make check-project-layout`, and
      `make check-python-version`. (D11)
      Note: build context is the tool's directory alone, behind a deny-all
      `Dockerfile.dockerignore`; `uv sync --locked --no-dev`; uid 10001; `ARG VERSION`
      for the label; `ENTRYPOINT ["frp-grant-admission"]` with a `serve` `CMD`;
      `STOPSIGNAL SIGINT`. The three checks pass.
- [x] 7.3 The root `Makefile` gains `build-frp-grant-admission`, building
      `arkhai:frp-grant-admission$(IMAGE_SUFFIX)`, run by `make build`, and `push-images`
      pushes it as `push_image` pushes the others. (D11)
      Note: builds from the tool's directory with `VERSION` read from its
      `pyproject.toml`, and tags its commit when unsuffixed. Beyond the plan's files,
      `scripts/change_namespace.py`'s `BUILT_IMAGES` gains the image and the
      aggregate-target test sets a bare build's commit tags aside, with a new case for
      this target. `make test-release-tooling` — 1817 passed.
- [x] 7.4 The README gains installation: the plain program from the wheel under the
      systemd example, beside `frps.service`; and the image, run in frps's network
      namespace — a sidecar in frps's pod, Compose's `network_mode: service:frps`, or host
      networking — with the configuration mounted read-only and reload by `docker kill -s
      HUP`. (D11, D13)
      Note: the README's "Installing" covers both, and `tools/README.md` gains the build
      targets. Round-1 triage fix (45 O1–O3): the configuration's directory is mounted,
      never the file or a `subPath`; the plugin is PID 1; the Kubernetes sidecar's
      ConfigMap, reload, and sync delay; no probe command (D11).
- [x] 7.5 Verification: `make -C tools/frp-grant-admission build`; `make
      build-frp-grant-admission`; `docker run --rm arkhai:frp-grant-admission check
      /app/examples/config.toml` or an equivalent that loads the example in the image and
      prints its thumbprint; `make check-packaging`.
      End-to-end: none (see the preamble).
      Note: the wheel built; `make build-frp-grant-admission` built
      `arkhai:frp-grant-admission` (VERSION 0.1.0, cryptography 50.0.2, PyJWT 2.15.1)
      and its commit tag; `docker run --rm arkhai:frp-grant-admission check
      /app/examples/config.toml` printed both issuers with TEST 1's thumbprint
      `kPrK_qmxVWaYVA9wwBF6Iuo3vVzz7TxHCTwXBygrS4k`. Not run: `serve`, SIGHUP, and SIGINT
      in the image. `make check-packaging`, `make test-release-tooling` (1817), `make
      test`, `make check-uv-setup`, `make check-python-version` pass. After the round-1
      triage fixes: `make check-comment-hygiene`, `make test`, and `make check-packaging`
      pass. End-to-end: none.

## 8. Closeout

The eleven parts of `openspec/README.md#plan-closeout-requirements`, in order.

- [x] 8.1 **Comment hygiene.** Run `make check-comment-hygiene`; any finding, or a
      comment the change added that narrates history, returns the change to
      implementation.
      Note: `make check-comment-hygiene` — passes (no change-ID, task-number, or change
      name). The comments added under `tools/frp-grant-admission/`, the root `Makefile`,
      `tests.yml`, and `scripts/` were searched and read for references to a review,
      triage, round, decision number, or migration: none. Pre-closeout review 55 found
      the same.
- [x] 8.2 **Import placement.** Confirm the imports sections 1–7 added are module-level or
      carry a recorded reason; one that should move returns the change to implementation.
      Note: no indented import anywhere under `tools/frp-grant-admission/src` or
      `tests`, and none added in `scripts/`; every import is module-level.
- [x] 8.3 **Documentation compliance.** Re-check each decision's destination in 8.9
      against `openspec/README.md`'s placement table, and that the tool's README names no
      concept of any particular issuing system.
      Note: each destination in `design.md`'s promotion record matches the placement
      table — normative behaviour to `spec.md`, rationale and limits to the companion,
      the repository-wide boundary to `ARCHITECTURE.md`, test methodology to
      `TESTING.md`, byte formats to the tool's README. The README names no lease, site,
      storefront, provisioning, buyer, market, or SCM concept (searched); it keeps
      "relay" for the frps server, judged compliant, and a test helper's `site_b`
      keyword is recorded for a later change (`design.md`, "Closeout judgements").
- [x] 8.4 **Narrative compression.** Shorten completed-task notes to final behaviour,
      evidence, and destinations — section 1's return to design included; move debugging
      narrative and declined suggestions into `design.md` first.
      Note: implementation's choices, declined suggestions, and what it left unproven
      moved to `design.md`, "Implementation record"; notes in sections 1–7 shortened to
      final behaviour, evidence, and destinations; fresh-context-check narratives and
      the unattended step's constraints dropped as provenance.
- [x] 8.5 **Roadmap currency.** No change to `docs/development/ROADMAP.md`: the plugin
      admits nothing until a relay runs it, which `prove-relay-provisioning` delivers and
      whose closeout records in Goal 1. Record that disposition in the design-promotion
      record.
      Note: confirmed — no `ROADMAP.md` gap names this change; recorded in the promotion
      record.
- [x] 8.6 **Campaign index currency.** This change's row in `openspec/changes/README.md`
      (`admit-relay-proxies-by-grant`, under "Lesser goal — Reach hosts and VMs that have
      no inbound route"): status `in closeout`, notes rewritten to the evidence; the
      campaign graph line `admit-relay-proxies-by-grant ──► prove-relay-provisioning
      (implementation)` unchanged; `make check-change-index`.
      Note: row `in closeout`, notes rewritten, linked to the archive directory after
      8.11; graph line and every other row unchanged. `make check-change-index` — passes.
- [x] 8.7 **Packaging.** `make check-packaging`; `make check-architecture-change
      CHANGE=admit-relay-proxies-by-grant`. `make check-agent-skills` is not owed unless
      the change touched `.agents/`, `.claude/`, or `.codex/`.
      Note: `make check-packaging` — passes (locks, Python version, layout, and the four
      architecture rules); `make check-architecture-change` — owns no architecture row.
      `make check-agent-skills` not owed: the change touches none of those directories.
- [x] 8.8 **End-to-end pipeline.** Record the pipeline run validating `HEAD` and its
      result. No `e2e-tests` scenario exercises the plugin; its system-level evidence is
      section 6's gate job, its real-frp tests and its floor run, recorded here with its
      run.
      Note: validation 54 passed at `2da0b5dcd`, the commit pre-closeout review 55 read:
      `e2e.yml` run 41324851196, success on e2e-apicredits, e2e-vm, and e2e-bare-metal;
      no scenario exercises this change. `tests.yml` run 41324855087, success: `test ·
      test-frp-grant-admission` 203 passed, 15 skipped; `frp · real-frp gate` verified
      `frp_0.61.1_linux_amd64.tar.gz` against its pin, 15 real-frp tests passed with no
      skip, and the floor run printed `cryptography 42.0.0` and `PyJWT 2.8.0`, 189
      passed. Baseline: `dev`'s run 41290075756 at `4b896cc4c`; no other job failed. The
      later commits, the merge of `dev` (`b7268ebb1`) and this closeout, change only
      `openspec/` and `docs/`, so the runs describe the code this commit carries; nothing
      was waived.
- [x] 8.9 **Promotion.** Write:
      - `openspec/specs/frp-grant-admission/architecture.md` (new): why grants travel per
        proxy; why the plugin holds no state and calls nothing; its SCM-agnostic
        placement in `tools/` and the later move; the issuer model and the drain rule;
        thumbprint ids; explicit typing as the major version; no leeway, and the port
        reuse it protects; reload by validated SIGHUP; loopback only; and the limits — no
        login admission, no revocation.
      - `openspec/specs/README.md`, "## Capabilities": the row for `frp-grant-admission`
        linking both files.
      - `docs/development/ARCHITECTURE.md`, "### Kind" under "## Package and dependency
        layers": after the sentence placing tooling projects outside the architecture, that
        a standalone component under `tools/` depends on no internal package; and the
        principle that generic infrastructure not specific to SCM does not belong in SCM —
        building it is a warning sign, overridden only when no existing software fits — and
        that a standalone component publishes its interface (specification, vector, pins),
        SCM conforming to it and checking its own copies against it, never the reverse.
      - `docs/development/TESTING.md`, "### 2. Integration Tests": registration and
        traffic are different proofs; a test that a connection was admitted also carries
        traffic through it.
      - The spec is written by the archive (8.11), carrying D18's, D19's, and D22's rules
        and D23's floor run from the delta.
      Complete the design-promotion record in `design.md`, naming each destination above,
      the tool's README for the grant specification (sections 4, 5, 7), and
      `tools/README.md` (6.5). The principle behind D18, D19, and D22 — the plugin owns
      the rules it publishes — stays in `design.md` only, by the owner's direction; record
      that disposition too.
      Note: all four written as listed; the companion also covers where PyJWT ends (the
      division only, not the declined principle), the real-frp proof, shipping, and the
      remaining limits. `TESTING.md` also names real-process tests as a gated
      integration flavour. The promotion record in `design.md` names every destination
      and the principle's disposition.
- [x] 8.10 **Documentation citations.** `make check-doc-citations
      CHANGE=admit-relay-proxies-by-grant`; `openspec validate admit-relay-proxies-by-grant
      --strict` (the pinned validator, run by `make check-change
      CHANGE=admit-relay-proxies-by-grant`).
      Note: before the archive, `make check-change` — 5 of 6 pass, strict OpenSpec
      validation and comment hygiene included; citations resolves every path but
      `openspec/specs/frp-grant-admission/spec.md`, which the archive writes (8.11). After
      the archive, `make check-change` resolves it, every check passing (8.11's note).
- [x] 8.11 **Archival.** `openspec archive admit-relay-proxies-by-grant -y`, merging the
      delta `specs/frp-grant-admission/` into a new
      `openspec/specs/frp-grant-admission/spec.md` (no `--skip-specs`).
      Note: no permanent spec existed, so the delta merged (no `--skip-specs`):
      `openspec archive` with the pinned 1.14.0 validator (through `npx`, `bunx` being
      absent) created the spec with the delta's 8 requirements and 28 scenarios, and moved
      the change to `openspec/changes/archive/2026-11-01-admit-relay-proxies-by-grant/`.
      The merged requirements match the delta; the archiver's placeholder Purpose was
      replaced with the capability's. The index row links the archive directory. `make
      check-change` on the archived change — every check passes: comment hygiene, agent
      skills, documentation citations, task list, change index, and `openspec validate
      --specs --strict`.
