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
      Note: as planned; `cryptography>=42`, `PyJWT>=2.8.0` (1.2). The console script
      names `frp_grant_admission.cli:main`, which section 3 writes. `pyproject.toml`
      gains `readme = "README.md"` in section 4, when the README exists. The lock
      resolves cryptography 50.0.2 and PyJWT 2.15.1; `make check-packaging` passes.
- [x] 1.2 **Decision gate on PyJWT's `iat`.** Find the lowest PyJWT release whose
      `jwt.decode` refuses, with zero leeway, an `iat` later than the clock, as D12 step 7
      and the delta's "A grant is not yet valid" require of "`nbf` and `iat` validated as
      PyJWT does"; declare `PyJWT>=` that release and record it in this task's note. If no
      release does, stop: the design must decide whether the plugin checks `iat` itself,
      and the change returns to design (`openspec/README.md#open-questions-and-prescribed-tasks`).
      (D8, D12)
      Note: **2.6.0** is the lowest release refusing an `iat` later than the clock
      (`if iat > (now + leeway): raise ImmatureSignatureError`), and the first whose
      expiry check is `exp <= now - leeway`, refusing at exactly `exp` as D12 requires;
      2.0.0, 2.4.0, and 2.5.0 have no future-`iat` check and refuse only `exp < now`.
      2.2's `strict_aud` option first appears in **2.8.0** (absent in 2.6.0 and 2.7.0),
      so the declared floor is `PyJWT>=2.8.0`. Evidence: each release locked in turn and
      its installed `jwt/api_jwt.py` read. Every release from 2.8.0 to 2.15.1 compares
      in `_validate_iat`, `_validate_nbf`, and `_validate_exp(payload, now, leeway)`, but
      reads `now` itself (`datetime.now()` in `_validate_claims`) and takes no clock
      argument — see 2.2's note for how the injected clock reaches those comparisons.
      Correction (replanned): the gate is settled by the design, not by this note. D18
      makes the time checks the plugin's own, so PyJWT's `iat` behaviour no longer bears
      on the floor, and D20 keeps `PyJWT>=2.8.0` for `strict_aud` alone; the clock never
      reaches PyJWT (2.2). Done when `pyproject.toml` declares `PyJWT>=2.8.0`, as it does.
- [x] 1.3 `config.py` loads a TOML file with `tomllib` into an immutable configuration:
      `listen` and a list of issuers, each with `name`, `audience`, `ports.start`,
      `ports.end`, and `keys`, each key a `public_key` — single-line standard base64 of
      the DER SubjectPublicKeyInfo of an Ed25519 key. Each key's id is derived at load as
      its RFC 7638 JWK thumbprint (base64url, unpadded, SHA-256 of
      `{"crv":"Ed25519","kty":"OKP","x":"<base64url raw key>"}`), and the configuration
      maps each id to its key and issuer. Types are strict: a quoted port is an error.
      (D3, D3a, D13)
      Note: `load_config(path)` and `parse_config(text)` return a frozen `Config`
      (`listen`, `issuers`, and a read-only `keys` map from thumbprint to `Key`, which
      names its `Issuer`); `thumbprint()` is the derivation. A key must be canonical: its
      base64 decodes strictly and re-encodes to the same DER, so trailing bytes are
      refused.
- [x] 1.4 Loading collects every problem and refuses the file, naming each: a key listed
      twice (by thumbprint, in any issuers); two issuers with the same `name`; two
      issuers whose ranges overlap, naming both; an issuer with no keys; a range outside
      1–65535 or with `end` before `start`; a key that is not Ed25519 SPKI DER base64;
      a missing or mistyped field; and a `listen` that is not an IPv4 address in
      `127.0.0.0/8` or `[::1]` with a port from 1 to 65535 — a hostname such as
      `localhost` included, decided without a resolver. (D3, D13; 14 F2)
      Note: beyond the plan, an unknown field at any level is refused too, so a file
      written for a later format (D3's "a later list of ranges") fails to load rather
      than loading with part of it ignored. The listen address is parsed with
      `ipaddress` alone, which also refuses `127.1` and `[::ffff:127.0.0.1]`. A file that
      cannot be read or is not TOML is one problem naming why.
- [x] 1.5 `examples/config.toml` is D13's example, with RFC 8032's TEST 1 public key and
      a comment saying it is a test value never to be used on any network. (D13;
      `AGENTS.md` public-repository discipline)
      Note: D13 elides the second issuer's key; the example gives it RFC 8032's TEST 2
      public key, labelled the same way, since a key cannot be listed twice.
- [x] 1.6 `.gitignore` ignores the tool's frp cache directory (section 5) and its
      environment. (D5)
      Note: the cache directory is `.frp-cache/`, which section 5's fetch must use.
- [x] 1.7 Unit (`tests/unit/test_config.py`): the example loads; the TEST 1 key's derived
      id is RFC 8037 Appendix A.3's `kPrK_qmxVWaYVA9wwBF6Iuo3vVzz7TxHCTwXBygrS4k`; two keys
      in one issuer both resolve to it; each refusal in 1.4 is reported, and a file with
      several problems reports all of them; `listen` values `0.0.0.0:7300`,
      `192.0.2.1:7300`, `localhost:7300`, and `[::]:7300` are refused, and
      `127.0.0.1:7300`, `127.1.2.3:7300`, and `[::1]:7300` load.
      Note: unit, 45 cases, all pass; they also hold the example's keys to RFC 8032's
      TEST 1 and TEST 2 hex. The RFC 8032 keys the tests and the vector use live in
      `tests/rfc8032.py` (TEST 1, 2, and 3).
- [x] 1.8 Verification: `make -C tools/frp-grant-admission test` (unit); `make
      check-packaging` (a new project and lock).
      End-to-end: none (see the preamble).
      Note: `make -C tools/frp-grant-admission test` — unit, 45 passed (the suite at this
      section's end); `make check-packaging` — passes. End-to-end: none, confirmed.
      Handoff: `scripts/uv_project.py lock` needs an existing `uv.lock`, and uv refuses an
      empty one, so the first lock was made from a stub holding `version = 1` and
      `requires-python`; `make lock` keeps a third-party package at its locked version,
      so moving one means relocking from that stub.
- [x] 1.9 Re-check section 1 after the rename and the merge of `dev` (D16, D21): the work
      of 1.1–1.8 is unchanged; `make -C tools/frp-grant-admission test` (unit) passes;
      `make check-packaging` passes; `make check-change CHANGE=admit-relay-proxies-by-grant`
      reports no failure but its citations check's, which may name only files the change
      creates — comment hygiene included, now that no code line contains the change's
      name. Then check 1.1–1.9 and commit the section.
      Note: unchanged — `git log -- tools/frp-grant-admission` shows only the section's
      work-in-progress commit `2c4e080b8`, and the tree under it is clean. `make -C
      tools/frp-grant-admission test` — unit, 45 passed; `make check-packaging` — passes;
      `make check-change` — 5 of 6 pass, comment hygiene and strict OpenSpec validation
      included; citations reports 8 missing paths, every one a file the change creates
      (`openspec/specs/frp-grant-admission/spec.md` and `architecture.md` at closeout,
      `tools/frp-grant-admission/README.md` in section 4, `tests/unit/test_structure.py`
      in section 6). End-to-end: none, confirmed.
      Correction (fresh-context check): an issuer skipped for a bad field was left out of
      the overlap check, so 1.4's "collects every problem" did not hold — fixing a key
      could reveal an overlap. A valid range is now checked whatever its issuer's other
      fields. Unit tests added for that, for each structural refusal 1.7 had covered only
      by sample (`issuers` missing or not an array of tables, `keys` missing or not tables,
      `ports.start` or `ports.end` missing, a non-string `public_key`), and for unknown
      fields in `ports` and key tables; `__version__`, a hand copy of `pyproject.toml`'s
      version that nothing read, removed. Unit, 55 passed.

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
      Note: `Reason` is an enum of `(code, text)`; `reason.reply` is the
      `"<code>: <text>"` frps passes to frpc. Unit, `tests/unit/test_reasons.py` (not in
      the plan's file list): the codes are exactly these sixteen in this order, and each
      text is one short line — passes. The two mappings the design left open — an
      unreadable header is `grant_malformed`, and an `alg` other than `EdDSA` is
      `signature_invalid` — are recorded in D12 (fresh-context check).
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
      Note: `check_grant(grant, config, remote_port, now)` returns a frozen
      `GrantResult` (`reason`, `issuer`, `kid`, `sub`, `jti`, `exp`, `verified`;
      `admitted` is `reason is None`). The unverified header is read by the module
      itself (`_read_unverified`), padded or unpadded, and must be canonical base64url
      decoding to a JSON object, else `grant_malformed` before the `kid` lookup; claims
      that cannot be read are reported as none and left to PyJWT to refuse. PyJWT's
      `InvalidSignatureError` and `InvalidAlgorithmError` map to `signature_invalid`
      (so `alg: none` is `signature_invalid`), `MissingRequiredClaimError` to
      `claim_missing`, `InvalidAudienceError` to `audience_mismatch`, and any other
      `PyJWTError` to `grant_malformed`. `verified` is true only once the signature,
      audience, required claims, and every claim type pass; a grant refused for its time
      or port still reports verified claims, a `port` of the wrong type included. A
      wrong-typed `sub` or `jti` is checked after the time checks, as (f) follows (e). A
      grant string holding an unpaired surrogate, which JSON can carry and UTF-8 cannot,
      is `grant_malformed`; a `RecursionError` from PyJWT's parsing of deeply nested
      claims, which some declared releases let escape, is `grant_malformed` too — a
      defence with no test, since whether 4 KiB of nesting overflows the parser depends
      on the Python version's recursion limit. Correction: "never reads the system clock"
      holds for the check's own code only: PyJWT reads `datetime.now()` while decoding,
      but every time check it would make with it is off, so no verdict depends on it.
      Correction (section 6): (d) is called on a `jwt.PyJWT()` instance, since PyJWT
      2.8.0, the declared floor, exports no module-level `jwt.decode_complete`; the
      function and its options are D12 step 8's. D12 and D22 still write
      `jwt.decode_complete`; documents promoted at closeout should say PyJWT's
      `decode_complete`.
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
      Note: the vector carries all three RFC 8032 test keys (TEST 1 and TEST 2 in issuer
      `site-a`, 6100–6199; TEST 3 in `site-b`, 6200–6249), each with seed, raw public
      key, SPKI base64, and `kid`; the forged cases are signed with TEST 2 while naming
      TEST 1's `kid`. Every case replays at 2027-01-01T00:00:00Z unless it states
      another time. The builder's JCS is the subset the vector uses (ASCII member names
      and strings, integers up to 2^53, non-integral floats with no exponent) and refuses
      anything else rather than serializing it as JCS would not. The builder is regenerated with `uv run python -m
      tests.vector_builder` from the tool's directory; when the committed file differs,
      `test_vector.py` writes the builder's output to its temporary directory and names
      it, which is how this session placed the file (the unattended step may not run the
      builder directly).
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
      Note: 38 verification cases, every named case above included, plus: only the
      required claims, `iat` and `nbf` equal to the clock (admitted), after `exp`,
      outside every issuer's range, `alg: none`, no `kid`, no `aud`, no `port`, not a
      JWT, and claims that are not an object. **Departure for review:** the 4 KiB cap
      (D12 step 5) is proven in `test_grant.py`, not the vector, against D12's "each rule
      has a vector case". Its cases are over 4,000 characters of filler each, and the
      unattended step could not run the builder to place them (2.3's note), so copying
      them by hand was the only way in; a signer's conformance gains nothing from them.
      Adding them later is a builder edit and a regeneration. An unpadded segment can
      never make some totals, so the exact-size grant carries a padded signature segment.
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
      Note: unit, all pass. `test_vector.py` reproduces each signing case from the file's
      own seed with its own JCS, not the builder's, and checks each key entry's seed,
      public key, SPKI, and `kid` against one another and the thumbprint case against
      RFC 8037's. `test_grant.py` asserts every field of the result for an admitted,
      forged, malformed, expired, wrong-port, and `port`-as-text grant, and the fields it
      names for an unknown-`kid` and a wrong-typed grant; the 4 KiB cap (exactly 4096
      bytes admitted; the shortest grant over it refused as `grant_malformed` with every
      field empty); and the clock: a grant expiring in 2001 admitted at a passed 2001
      clock and refused at its `exp`, and one issued in 2100 admitted at a passed 2100
      clock and refused a second earlier. That shows no verdict depends on the wall
      clock, not that nothing reads it (2.2's correction).
- [x] 2.6 Verification: `make -C tools/frp-grant-admission test` (unit).
      End-to-end: none (see the preamble).
      Note: `make -C tools/frp-grant-admission test` — unit, 116 passed. `make test` —
      passes (the tool is not part of it until section 6). `make check-packaging` —
      passes. `make check-change` — 5 of 6 pass; citations reports the same 8 paths as
      1.9, every one a file the change creates. End-to-end: none, confirmed. The vector
      has not run at the floors yet: section 6's `make test-floor` is the first run on
      PyJWT 2.8.0 and `cryptography` 42.0.0.
      Handoff: the fresh-context check's findings were fixed — an overclaiming module
      docstring (D23's two tested points), the surrogate and `RecursionError` paths, the
      builder's JCS subset (it passed `5.0`, which JCS writes `5`), the `verified`
      docstring, and the notes above; declined, with reason in 2.4's note, a vector case
      for the 4 KiB cap. This step cannot run `uv run python …`; only `uv run pytest`
      and `make … test*` targets. A changed vector is placed by copying the file
      `test_vector.py` names on failure, which is why the cap's long cases are unit
      tests.

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
      Note: the request's checks are a pure module of their own, `request.py` (not in the
      plan's file list): `decide_request(request, config, now)` and `decide_body(body,
      config, now)` return a `Decision` whose `answer()` is frps's reply, so they are
      unit-tested from a request dict and `decision_log.py` can name a decision without
      importing the server. `server.py` holds `Plugin` (the configuration reference, the
      reload, and the clock, `time.time` unless injected, read once per request and
      floored to whole seconds) and `PluginServer`, a `ThreadingHTTPServer` with daemon
      threads, whose socket family follows the address (`::1` binds IPv6) and whose
      `server_bind` skips the standard library's host-name lookup, so binding makes no
      resolver call. The handler answers `POST` to path `/` with any query (frps
      appends `?version=0.1.0&op=NewProxy`); another path is 404, and another method is
      the standard library's 501. A body with no or a bad `Content-Length`, over 64 KiB,
      or whose next bytes do not arrive within the socket timeout is
      `malformed_request`; the timeout bounds each wait on the socket, not the whole
      body, so a body trickled faster than it holds a thread longer. At most 64 KiB + 1
      bytes are read whatever the declared length. A non-string `metas.grant` is
      `grant_malformed`, an empty one `grant_missing`. The handler's access log is
      silenced and a bind failure is a `config_refused` line, so stderr carries only
      JSON lines but for a traceback from an unexpected exception.
- [x] 3.2 `decision_log.py` writes one JSON line to stderr per decision, in D10's shape —
      `ts`, `event` (`admit` or `refuse`), `reason` on a refusal, `proxy`, `type`,
      `remote_port`, `issuer` where known, `kid`, `sub`, `jti`, `exp` where present, and
      `verified` — and one line per configuration load or reload, listing each issuer's
      name, range, and key thumbprints, or every problem found. It never writes the grant
      or the request's metadata. (D10)
      Note: a decision line is D10's shape, its fields omitted where absent but
      `verified`, which is always present (false when no grant was read); `ts` comes
      from the same clock reading as the decision. A load is `{"event":
      "config_loaded", "trigger": "startup" | "reload", "listen", "issuers": [{"name",
      "audience", "ports": {"start", "end"}, "keys"}]}`, and a reload naming another
      listen address adds `listen_at_restart`, `listen` staying the bound one. A refusal
      is `{"event": "config_refused", "trigger", "problems"}`, with `"kept": "the running
      configuration"` on reload. Lines are strict ASCII JSON, one write each, under a
      reentrant lock; a non-finite number a sender wrote is logged as Python writes it
      (`NaN` as `"nan"`, `1e400` as `"inf"`), and a field nested too deeply for a Python
      recursion to walk — the JSON parser accepts deeper — as `"<nested too deeply to
      log>"`, so no decision loses its line. Unit,
      `tests/unit/test_decision_log.py` (not in the plan's file list): an admission's
      exact line; a forged grant logged unverified with no segment of the grant in the
      log; a request refusal naming only what the request sent, with no client-wide
      metadata; a proxy name holding a quote and a newline staying one line; a `NaN`
      name and an infinite port logged as text; a proxy name nested 5,000 deep logged as
      the placeholder; and the three configuration lines — passes.
- [x] 3.3 SIGHUP re-reads the file through section 1's loader: a valid file replaces the
      configuration reference in one assignment; an invalid one leaves the running
      configuration and logs every problem. `listen` is bound once at startup: a reload
      that changes it applies the rest and logs that the new address takes effect at
      restart. (D9; 14 F2)
      Note: `install_reload_on_sighup(plugin)` sets the handler and returns the one it
      replaced. Python runs it in the main thread, which otherwise only serves the
      socket, so the one write it can interrupt there is another reload's, when a
      second SIGHUP lands during a reload; the log's lock is reentrant, so that never
      deadlocks. `serve` installs it only after binding and writing its startup line; a
      SIGHUP before then ends the process by its default action, which frps meets as a
      plugin that does not answer. A reload that raises anything keeps the running
      configuration: a file nesting too deeply for `tomllib` is a `ConfigError` from the
      loader, any other exception in `Plugin.reload` a one-problem `config_refused`
      (untested: nothing in the loader is known to raise one), and the handler catches
      whatever escapes, since an exception leaving a signal handler would end
      `serve_forever`. Unit, `tests/unit/test_reload_signal.py` (not in the plan's file
      list): a plugin whose reload raises, signalled twice, is reloaded twice with the
      traceback on stderr and nothing raised — passes. `Plugin` compares a reloaded `listen` with the one it started with, not with the
      socket's address, so a test server bound to an ephemeral port reports the change
      as an operator's would.
- [x] 3.4 `cli.py`: `frp-grant-admission serve --config <path>` refuses to start, exiting
      non-zero with every problem, on a file that does not load; `frp-grant-admission
      check <path>` loads a file without touching a running plugin, prints each issuer
      with its range and its keys' thumbprints, and exits non-zero naming every problem
      when it does not load. (D9)
      Note: `main(argv)` returns the exit status, and `cli.py` runs it as `python -m
      frp_grant_admission.cli` too. `serve` is `start(path, log)` — load, bind, write
      the startup `config_loaded` line, install the SIGHUP handler — then
      `serve_forever`. On a file that does not load it writes one `config_refused`
      line, `trigger: startup`, with every problem, and exits 1; a listen address it
      cannot bind is a `config_refused` line naming it, and exits 1. `check` prints `listen <address>`,
      then `issuer <name>: audience <audience>, ports <start>-<end>` and an indented `key
      <thumbprint>` per key, and on a file that does not load prints every problem to
      stderr and exits 1.
- [x] 3.5 Unit (`tests/unit/test_request.py`): each request refusal of 3.1 from a request
      dict, including a grant only in `content.user.metas`, `remote_port` 0, a non-empty
      `group`, `op` `Login`. Unit (`tests/unit/test_cli.py`): `check` prints thumbprints
      for the example and fails naming each problem of an invalid file; `serve` exits
      non-zero on one.
      Note: unit, all pass. `test_request.py`: an admission's answer and named fields;
      the refusal answer's `"<code>: <text>"`; every request refusal — not an object,
      `op` missing, not a string, `Login`, `CloseProxy`, no `content` or not an object,
      `proxy_type` `stcp`, `TCP`, or absent, a non-empty `group`, `remote_port` 0, 65536,
      a string, `true`, or absent, `metas` absent or without a grant, an empty grant, a
      non-string grant; an empty `group` admitted; a grant only in `content.user.metas`
      refused as `grant_missing` with no grant read; the request checks deciding before
      a forged grant is read; the grant checked against the requested port; and bodies
      that are not JSON or over 64 KiB. `test_cli.py`: `check` on the example and on a
      file with four problems, `check` on a missing file, `serve` refusing to start on
      the four-problem file (one `config_refused` line with four problems, and a return
      of 1), and `serve` without `--config`. `test_config.py` gains a file nesting too
      deeply for the parser, refused with one problem. The frps request shape is shared by the unit and
      integration tests from `tests/frps_request.py`.
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
      Note: integration (in-process), all pass. `tests/integration/test_server.py`, 12
      cases: the server on `127.0.0.1:0` in a thread, its clock fixed at the vector's
      time, logging to a stream whose lines a test waits for under a condition with a
      5-second bound. Each case listed above, plus a body sent with no
      `Content-Length` (refused as `malformed_request`, and logged), a body stalled past
      a 0.2-second socket timeout the test sets (refused and logged), the server on
      `[::1]` admitting a grant (skipped where no IPv6 loopback can be bound; it ran
      here), and a `POST` to another path (404). `tests/integration/test_start.py`, 2
      cases (not in the plan's file list): `start` binds the address the file names,
      writes the startup line, reloads on a SIGHUP sent to the process (an issuer added,
      its reload line awaited), and answers a request on the system clock (only the
      answer's shape is asserted, since the vector's grant is not yet valid on it); and
      an address already in use is a `config_refused` line, no server, and no handler
      installed. The configured port is found free just before `start` binds it, a race
      the test accepts. The over-64-KiB body is exactly 64 KiB + 1 bytes, so the server reads all
      of it and its reply is not lost to a reset; a longer body is refused the same way,
      but frps may then see the connection reset rather than the refusal, which fails
      closed alike. SIGHUP is sent to the test process with the reload handler installed
      in pytest's main thread and restored after each test; each test waits for the
      reload's log line before posting, so it never depends on when the handler runs.
      The invalid reload's file has two problems
      (an overlap and `localhost`), and both are logged. Section 5 proves reload and
      fail-closed against real frps.
- [x] 3.7 Verification: `make -C tools/frp-grant-admission test` (unit and in-process
      integration).
      End-to-end: none (see the preamble).
      Note: `make -C tools/frp-grant-admission test` — unit and in-process integration,
      174 passed, none skipped. `make check-packaging` — passes. `make test` — passes
      (the tool joins it in section 6). End-to-end: none, confirmed.
      Handoff: the fresh-context check, run twice, found and this section fixed `[::1]`
      failing to bind, a SIGHUP during startup able to deadlock on the log's lock, a
      reload error other than `ConfigError` ending the server, `NaN` making a line
      invalid JSON, deep nesting losing a line, and the standard library's host-name
      lookup at bind; and notes that overstated their tests. Not fixed: the socket timeout bounds each wait rather than the body (D12
      says "socket timeout"; a per-body deadline is a design change if wanted), and a
      forged grant's line carries `issuer` and the unverified `exp`, which D10's example
      line omits — 3.2's "where known, where present" puts them there, and the README
      (section 4) states the fields. The configuration lines' shapes, `verified` always
      present, the `Content-Length` rules, and 404 versus 501 are this section's choices;
      section 4's README states the log's fields.

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
      Note: the README states the specification as version 1.0 within `frp-grant 1.x`,
      matching the vector's `frp-grant 1.0`, and holds every part listed above; the frp
      version, the pins file's format (section 5), and installation (section 7) are
      left to their sections, so it names no frp version yet. Its admission steps are
      D12's, with an unreadable header at step 5 as D12 now records. Beyond the plan,
      the example issuers are renamed `issuer-a` and `issuer-b` in the README and in
      `examples/config.toml` (with `test_config.py` and `test_cli.py` following), since
      D13's `vm-site` and `bm-site` name one issuing system's concepts, which the
      README must not; for the same reason the vector's issuers become `issuer-a` and
      `issuer-b` (the builder's configuration and the committed file's `configuration`
      text alone change, no token, and the tests follow). **For the owner:** the README
      keeps the word "relay" for the frps server it guards, as the delta spec and the
      reason texts do, though D14 and D17 call "relay" this repository's word; whether
      the README must say "server" instead is the owner's or the review's to settle.
      The README states frp's behaviour the plugin relies on — frps asking once per
      registration and again after a reconnect, failing closed, frpc retrying a refused
      proxy, a reload registering only changed proxies — as the design does; section 5
      tests each against real frp. It says the vector is replayed at the locked
      dependencies only: section 6 adds the floor run and the sentence saying so.
- [x] 4.2 Verification: every section, field, type, and reason code the README names
      exists in the code and the vector (read against sections 1–3); `make
      check-comment-hygiene`; `make check-packaging` (`readme` added).
      End-to-end: none.
      Note: read against the code and the vector — the claim table against
      `grant.py`, the reason table against `reasons.py` and where each is returned
      (corrected while reading: a wrong-typed `port` is `port_mismatch`, not
      `grant_malformed`, and `malformed_request` covers a missing `op` or `content`),
      the configuration rules against `config.py`, the log's fields against
      `decision_log.py`, and the vector's members against `vector/frp-grant-1.json`.
      The fresh-context check then corrected: a floor run the README claimed before
      section 6 delivers it; `verified`'s meaning (true too for a grant refused for its
      time or port); `claim_missing` covering a `null` claim; when the log carries the
      proxy's fields and the grant's; step 1's socket timeout and `content` object; and
      the vector's `warning` and `name` members. Its finding that PyJWT 2.15.1 may map
      an empty `aud` to `claim_missing` where 2.8.0 says `audience_mismatch` is not
      checked here and no vector case holds it: section 6's floor run is where such a
      difference would show, and the vector could gain the case.
      `make -C tools/frp-grant-admission test` — unit and in-process integration, 174
      passed; `make check-comment-hygiene` — passes; `make check-packaging` — passes,
      the lock unchanged by `readme`; `make test` — passes; `make check-change` — 5 of 6 pass, citations
      reporting 7 paths, every one a file the change creates at closeout or in
      section 6. End-to-end: none, confirmed.

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
      Note: `version` and one `[archives.<os>_<arch>]` table per platform, each `url`
      (https only) and `sha256` (64 lowercase hex); an unknown member at either level is
      refused, so a later shape fails to load rather than half-loading. The SHA-256,
      `bff260b6…2c40`, is the digest of the archive GitHub served this session's fetch
      (the fetch's own mismatch error named it against a zero placeholder, and the next
      run verified the download against it). **For the owner:** it was not cross-checked
      against the release's published `frp_sha256_checksums.txt`, since this unattended
      step was denied WebFetch; comparing the two once by hand is worth doing, as the
      pin is trust on first use. The README gains "The frp it is tested against": the
      version, what the tests run against it, the pins format, and why the release's
      checksums file is never read; and states frpc 0.61.1's 30-second retry, measured
      below.
- [x] 5.2 The fetch downloads the pinned archive for the running platform, verifies its
      SHA-256 against the pin before extracting anything, extracts `frps` and `frpc` into
      the ignored `.frp-cache/`, and reuses a cached binary only when its archive
      verified. `FRPS_BIN` and `FRPC_BIN` override it. A platform with no pin and no
      override makes the real-frp tests skip in the default suite. Unit
      (`tests/unit/test_frp_fetch.py`), against a local archive file: a matching archive
      extracts both binaries; a mismatching one fails naming both digests and extracts
      nothing. (D5; delta "An archive does not match its pin")
      Note: `tests/frp_fetch.py`. The archive is cached under its own name and verified
      on every use, so a binary is (re)extracted only from an archive that verifies that
      run; a download lands as `<name>.part` and takes the archive's name only once it
      verifies, so a mismatching download leaves nothing. Each binary is read from its
      one member named `frps` or `frpc` and written under that name, so no path in the
      archive decides where anything is written. **Beyond the plan:** the default suite
      never fetches and never reads the cache — only `FRPS_BIN` and `FRPC_BIN` give it
      binaries — so `make test` skips the real-frp tests even on a machine where the gate
      has cached them, rather than turning a 7-second suite into a two-minute one; the
      cache is the gate's. The bytes hashed are the bytes extracted (one open file), and
      any download failure, `http.client`'s included, is a `FetchError` leaving no
      `.part`. Unit, 18 cases, all pass: matching archive extracted (both binaries,
      executable, nothing else); mismatching archive names both digests and creates no
      destination; an archive missing `frpc`; a `file:` download verified, cached, and
      reused once its source is gone; a mismatching download, and one cut short, leave
      the cache empty; a tampered cached archive (and binary) downloaded and extracted
      again; the default suite refused binaries despite a verified cache; a platform with
      no pin; the overrides, alone and paired; the committed pins file; seven refusals
      of the pins format (unknown members, a version, a URL that is not https or not a
      `.tar.gz`, an uppercase digest, no archives).
- [x] 5.3 Fixtures (`tests/frp/conftest.py`) start the plugin, `frps`, and `frpc` as
      processes, every port chosen at runtime on `127.0.0.1` — frps's bind port, the
      plugin's, `allowPorts`, the issuers' ranges, the remote ports — with frps's
      `[[httpPlugins]]` pointing at the plugin; tokens are signed with the TEST 1 key. A
      proxy's state is read from frpc's admin `/api/status` with a bounded wait, never a
      sleep; the wait for frpc's retry of a refused proxy is sized to frpc 0.61.1's retry
      interval, with a comment saying why it is that long. Without binaries every test in
      `tests/frp/` skips. (D5)
      Note: the helpers are in `tests/frp/stack.py` (not in the plan's file list), so
      `conftest.py` holds only the fixtures and the gate's hooks, as `tests/frps_request.py`
      keeps shared helpers elsewhere. The plugin runs as `python -m
      frp_grant_admission.cli serve`, its stderr read by a thread whose lines a test
      waits on under a condition; frps and frpc run from generated TOML. Ports, all
      distinct: a block of eight consecutive free ports split as issuer A (3), issuer B
      (3), one outside every range, and `allowPorts` over all eight; then frps's, the
      plugin's, and each frpc's admin port free singly. Issuer A holds TEST 1 and TEST 2,
      so 5.6 can remove TEST 1 and leave it a key. Grants are signed on the system clock
      (the plugin's clock here), not the vector's 2027 one. frpc's status and frps's
      readiness are polled within a bound (15 s; 60 s for a retry) at 0.2 s intervals — a
      poll is the only observation an external process offers — and the plugin's log is
      awaited on a condition. The retry wait's comment states frpc 0.61.1's measured
      retry, 30.1–30.2 s after a refusal. Both binaries must report, by `--version`, the
      release the pins file names, whether fetched or given by the overrides, so the gate
      cannot pass on an unpinned frp. Under `FRP_GATE=1` a missing binary fails, and
      hooks fail the run on any skip, in collection or in a test (unexercised: no test
      here skips by design); pytest itself exits 5 when none run, which `make test-frp
      PYTEST_ADDOPTS="-k no_such_test"` showed.
- [x] 5.4 Integration, real frp (`tests/frp/test_real_frp.py`): a valid grant admitted,
      and traffic reaching a local listener through the remote port; refused, with the
      reason frpc reports — no grant, a forged signature, the wrong port, the wrong
      audience, an expired grant, a port outside its issuer's range, one issuer's grant for
      another issuer's range, a non-`tcp` proxy (`stcp`), and a grant only in client-wide
      metadata. (D5; delta "A valid grant is presented", "A proxy carries no grant of its
      own", and the refusal scenarios; "A grant is refused")
      Note: integration (real frp), all pass. The valid grant: frpc reports `running`,
      bytes sent to the remote port on frps come back from an echo service behind the
      proxy, and the plugin logged `admit`, `issuer-a`, `verified: true`. Each refusal:
      frpc reports `start error` with the reason code in its `err` — so the reason
      reaches frpc through frps, as frps's default `detailedErrorsToClient` passes it —
      and the plugin logged `refuse` with the same reason for that proxy. The
      client-wide case also shows no `kid` read and `verified: false`.
- [x] 5.5 Integration, real frp: frps refuses the proxy while the plugin is stopped, while
      a stand-in answers HTTP 500, and while it answers a malformed body; and in each
      case, once the plugin answers again, the same frpc's proxy is admitted on its own
      retry without restarting frpc. (D5, D9; delta "Admission fails closed")
      Note: integration (real frp), all pass. frpc reports `start error` and the remote
      port refuses a connection; the stand-in is an in-process HTTP server on the
      plugin's port, answering 500 or HTTP 200 with `{not json`, and records that frps
      asked it exactly one `NewProxy`. The plugin then starts on that port, and the frpc
      the test started — still running, and the only one started — reports `running`
      about 30 s later, carries traffic, and the plugin logged the admission. Premise
      held: frps refused on each failure, and frpc retried without a restart.
- [x] 5.6 Integration, real frp: a registered proxy keeps running after a SIGHUP reload
      removes its key, and is refused once frpc is restarted — the reconnect forced by
      restart, not by waiting for a heartbeat. (D3's drain premise; delta "A registered
      proxy is not rechecked")
      Note: integration (real frp), passes. A connection held through the proxy carries
      traffic before and after the reload line (TEST 1 removed, TEST 2 kept); frpc then
      still reports `running` and a new connection carries traffic; a new frpc from the
      same file is refused with `key_unknown`, and that is the plugin's only refusal.
      Premise held: frps did not recheck the registered proxy when the plugin's
      configuration changed, and refused it when it was registered again.
- [x] 5.7 Integration, real frp: an frpc reload adding a second proxy beside a registered
      one produces exactly one decision line in the plugin's log, for the new proxy.
      (D5; delta "A client reload adds a proxy")
      Note: integration (real frp), passes, through `frpc reload -c <file>` (frpc's admin
      API). A connection held through the first proxy carries traffic before and after
      the reload, and the decision lines after the reload are exactly one `admit`, for
      the new proxy, which then carries traffic. The count is taken once the new proxy's
      decision is logged: frpc sends every `NewProxy` a reload causes when the reload
      runs, so a second decision for the first proxy would be logged by then — a strong
      negative, not one a bounded test can make airtight. Premise held.
- [x] 5.8 The tool's `make test-frp` fetches the binaries and runs `tests/frp/`, failing
      when any test skips or none runs; its `make test` runs everything else and passes
      with the network off. (D5; delta "The gate runs without frp")
      Note: `test-frp` is `FRP_GATE=1 uv run pytest tests/frp -q -rs`; `test` is
      unchanged, `tests` with the real-frp tests skipping, since without the gate it
      reads no binaries but the overrides and so never reaches the network.
- [x] 5.9 Verification: `make -C tools/frp-grant-admission test` with the network off
      (unit, in-process integration; real-frp tests skip); `make -C
      tools/frp-grant-admission test-frp` (real-frp integration, no skips). If 5.5, 5.6,
      or 5.7 shows an frp premise false, stop and return the change to design (D15).
      End-to-end: none (see the preamble).
      Note: `make -C tools/frp-grant-admission test` — unit and in-process integration,
      192 passed, the 15 real-frp tests skipped. The network was not switched off: this
      step cannot do that, and the suite is offline by construction (no fetch without
      the gate, a unit case proving it). `make -C tools/frp-grant-admission test-frp` —
      integration (real frp), 15 passed, none skipped, about 100 s, run three times: the
      first downloaded and verified the archive, the later ones reused the verified
      cache, the last after the fresh-context check's fixes; a run from the cache timed
      each test (the three retry cases 30.1–30.2 s, the rest under 1 s). `make test` —
      passes (the tool joins it in section 6). `make check-change` — 5 of 6 pass;
      citations reports the 7 paths of 4.2, every one a file the change creates at
      closeout or in section 6. No frp premise was false. End-to-end: none, confirmed.
      Handoff: the fresh-context check found no blocking defect; this section fixed what
      it found — 5.7's count strengthened by a held connection, the README's real-frp
      coverage stated case by case, the binaries' version checked against the pin, a
      tautological pid check, the stand-in now recording frps's request, collection
      skips counted, ports made distinct, refusal cases named rather than indexed, the
      fetch's edge cases, the retry comment stated as measured, and helpers moved out of
      `conftest.py`. Declined: refusing the overrides under the gate (D5 makes them how
      another platform runs it; the version check covers the risk). For 8.9: the real-frp
      tests are a third integration flavour, under `tests/frp/` rather than
      `integration/`; the TESTING.md promotion may say so beside the
      registration-and-traffic principle. The pin is trust on first use until the owner
      compares it with the release's checksums file (5.1).

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
      Note: the run builds `.floor/.venv` (`.floor/` added to the tool's `.gitignore`;
      named `.venv` so the repository's scans skip it, see 6.6's handoff) with `uv venv
      --clear`, installs `-r pyproject.toml --group dev` with
      `--resolution lowest-direct` — reading the project's dependencies as direct
      requirements is what makes lowest-direct floor them; `uv run --resolution`
      would relock `uv.lock` — then the project itself `--no-deps -e .`, then runs
      `python -m tests.floor` (`tests/floor.py`, not in the plan's file list: reads the
      floors from `pyproject.toml`, prints each installed version, and exits 1 unless
      each equals its floor, `42` and `42.0.0` alike) and `pytest tests/unit`. No version
      is repeated in the Makefile. pytest is floored too, at the dev group's 8.3.4.
      **The floor run found a defect:** PyJWT 2.8.0 has no module-level
      `jwt.decode_complete`, so at the declared floor every grant check raised
      `AttributeError` (45 unit failures). `grant.py` now calls `decode_complete` on one
      `jwt.PyJWT()` instance, which every declared release carries — the same function
      D12 step 8 names, with the same options, so no decision changes; its comment
      records why. Unit at the floors (PyJWT 2.8.0, `cryptography` 42.0.0 printed): 186
      passed, the vector included; `git status` showed `uv.lock` unchanged, and no
      command of the recipe names the project's `.venv` (which Git ignores, so no status
      could show it).
- [x] 6.2 The root `Makefile` gains `test-frp-grant-admission` (`$(MAKE) -C
      tools/frp-grant-admission test`), appended to the prerequisites of `test`;
      `test-frp-grant-admission-frp`, running the tool's `test-frp`; and
      `test-frp-grant-admission-floor`, running the tool's `test-floor`. `tests.yml`'s
      matrix appends `test-frp-grant-admission` in the same position, which
      `scripts/tests/test_tests_workflow.py` holds equal to `make test`'s targets. (D5,
      D23)
      Note: as planned; the three targets are declared `.PHONY`, and the two
      network-bound ones carry `##` help. The matrix test passes (in `make
      test-release-tooling`, 1816 passed).
- [x] 6.3 `tests.yml` gains a job, `frp · real-frp gate`, that checks out, sets
      `UV_PYTHON` from `.python-version` under checkout's condition, installs uv 0.12.19
      as the matrix does, and runs `make test-frp-grant-admission-frp` and `make
      test-frp-grant-admission-floor`. It is in `tests.yml` because that is the workflow
      `scripts/ci_evidence.py` may dispatch. `make check-python-version` passes on the
      edited workflow. (D5, D23; `BUILD_AND_PACKAGING.md`, "One Python version")
      Note: job id `frp-grant-admission-gate`, name `frp · real-frp gate`, after the
      matrix; it builds no wheelhouse, since the tool's lock installs nothing from it.
      The floor step runs `if: ${{ !cancelled() }}`, so a failing real-frp step does not
      hide the floor run's result. The workflow's header comment says the gate is its
      own job. `make
      check-python-version` — passes. Not yet run in CI: owed by validation (6.6).
- [x] 6.4 Unit (`tests/unit/test_structure.py`), standing in for `check-architecture`,
      which skips `tools/`: the tool's `uv.lock` resolves no package from the wheelhouse,
      its `pyproject.toml` declares only `cryptography` and `PyJWT` at runtime, each with
      a lower bound and no upper bound, and every import under `src/` is of the standard
      library, `jwt`, `cryptography`, or the package itself. (D4, D23)
      Note: unit, 8 cases, all pass: every locked package but the project (`editable =
      "."`) comes from `https://pypi.org/simple`, so neither the wheelhouse nor any path;
      `[project] dependencies` are exactly `cryptography` and `PyJWT`, each written
      `<name>>=<release>` (the same parser the floor run uses, so the two cannot read
      the declarations differently), and the project declares no optional
      dependencies; an upper bound, an exact pin, a bare name, or a marker is refused;
      releases compare as releases; and every absolute import anywhere in
      `src/frp_grant_admission`, the one package under `src/` (any nesting,
      `ast.walk`), is of `sys.stdlib_module_names`, `jwt`, `cryptography`, or
      `frp_grant_admission`.
- [x] 6.5 `tools/README.md` gains a section: `tools/` also holds standalone
      infrastructure components — not market runtime services, depending on no internal
      package, intended for their own repositories — naming `frp-grant-admission`, its
      `make test`, `make test-frp`, and `make test-floor`, the root targets, and the gate
      job; the opening paragraph's "not part of the market runtime services" is kept true
      by saying what a standalone component is instead. (D4)
      Note: the opening paragraph now names both kinds of project, and the wrapper and
      entrypoint paragraphs are scoped to the developer and validation tools, which a
      standalone component is not invoked like. The new section says what a standalone
      component is (generic, no market concept, no internal package, liftable, owning
      its interface with the market conforming to it, its own licence and version), that
      a structure test stands in for `check-architecture`, and lists the component's
      three targets, the root ones, and the gate job. The tool's README also gains the
      sentence 4.1 left for this section: the vector is replayed at the lock and at the
      floors, two tested points, with the structure, not every release's verdicts, what
      the specification promises (D23).
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
      Note: `make -C tools/frp-grant-admission test-floor` — unit at the floors, PyJWT
      2.8.0 and `cryptography` 42.0.0 printed, 186 passed, `uv.lock` unchanged (after
      6.1's `decode_complete` fix; before it, 45 failed). `make test-frp-grant-admission`
      — unit and in-process integration, 200 passed, 15 real-frp skipped. `make
      test-release-tooling` — 1816 passed, the matrix test included. `make test` —
      passes, with the tool's suite in it. `make check-packaging` — passes. `make
      check-python-version` — passes. Also `make test-frp-grant-admission-frp` —
      integration (real frp), 15 passed after the `grant.py` change; and
      `make test-frp-grant-admission-floor`, as above. The owed lines are confirmed as
      written: the job names match `tests.yml`. End-to-end: none, confirmed.
      Handoff: the floor environment first lived at `.floor-venv/`, which
      `make check-comment-hygiene` scans, since it skips only directories named `.venv`;
      it moved to `.floor/.venv`. **For the owner:** the earlier directory,
      `tools/frp-grant-admission/.floor-venv/`, is still on disk in this clone — Git
      ignores it through the `*` `.gitignore` uv writes in every environment, but the
      hygiene scan reports four RFC citations in `cryptography`'s source inside it until
      it is deleted (`rm -rf tools/frp-grant-admission/.floor-venv`), which this step may
      not do. Every hygiene finding since is inside it. The fresh-context check found no
      correctness defect; this section fixed the stale 6.1 note, 6.4's overstated scope
      (and added the optional-dependencies check), the reason `grant.py`'s comment gave
      for sharing one `PyJWT`, the `.venv` evidence wording, a `tools/README.md`
      paragraph still speaking of every tool as a `scripts/` entrypoint's package, and
      the gate job's floor step being skipped after a real-frp failure.

## 7. Shipping: the wheel, the image, and the systemd example

Delivers the plain program and the image (D11, D13's network-namespace note).

Files: `tools/frp-grant-admission/Dockerfile` and its ignore file, if one is needed;
`tools/frp-grant-admission/examples/frp-grant-admission.service`;
`tools/frp-grant-admission/README.md`; the tool's `Makefile`; the root `Makefile`.

- [ ] 7.1 The tool's `make build` builds its wheel. `examples/frp-grant-admission.service`
      runs `frp-grant-admission serve --config /etc/frp-grant-admission/config.toml` with
      `ExecReload=/bin/kill -HUP $MAINPID` and the hardening `frps.service.j2` carries.
      (D11)
- [ ] 7.2 The `Dockerfile` follows `BUILD_AND_PACKAGING.md`'s "Images": `ARG
      PYTHON_VERSION` defaulting to the root declaration before the first `FROM`; a uv
      builder installing the committed lock unchanged; a `python:${PYTHON_VERSION}-slim`
      runtime for `linux/amd64` running as a non-root user; the tool's version as the
      `org.opencontainers.image.version` label; entrypoint `frp-grant-admission serve
      --config <path>`. It passes `make check-uv-setup`, `make check-project-layout`, and
      `make check-python-version`. (D11)
- [ ] 7.3 The root `Makefile` gains `build-frp-grant-admission`, building
      `arkhai:frp-grant-admission$(IMAGE_SUFFIX)`, run by `make build`, and `push-images`
      pushes it as `push_image` pushes the others. (D11)
- [ ] 7.4 The README gains installation: the plain program from the wheel under the
      systemd example, beside `frps.service`; and the image, run in frps's network
      namespace — a sidecar in frps's pod, Compose's `network_mode: service:frps`, or host
      networking — with the configuration mounted read-only and reload by `docker kill -s
      HUP`. (D11, D13)
- [ ] 7.5 Verification: `make -C tools/frp-grant-admission build`; `make
      build-frp-grant-admission`; `docker run --rm arkhai:frp-grant-admission check
      /app/examples/config.toml` or an equivalent that loads the example in the image and
      prints its thumbprint; `make check-packaging`.
      End-to-end: none (see the preamble).

## 8. Closeout

The eleven parts of `openspec/README.md#plan-closeout-requirements`, in order.

- [ ] 8.1 **Comment hygiene.** Run `make check-comment-hygiene`; any finding, or a
      comment the change added that narrates history, returns the change to
      implementation.
- [ ] 8.2 **Import placement.** Confirm the imports sections 1–7 added are module-level or
      carry a recorded reason; one that should move returns the change to implementation.
- [ ] 8.3 **Documentation compliance.** Re-check each decision's destination in 8.9
      against `openspec/README.md`'s placement table, and that the tool's README names no
      concept of any particular issuing system.
- [ ] 8.4 **Narrative compression.** Shorten completed-task notes to final behaviour,
      evidence, and destinations — section 1's return to design included; move debugging
      narrative and declined suggestions into `design.md` first.
- [ ] 8.5 **Roadmap currency.** No change to `docs/development/ROADMAP.md`: the plugin
      admits nothing until a relay runs it, which `prove-relay-provisioning` delivers and
      whose closeout records in Goal 1. Record that disposition in the design-promotion
      record.
- [ ] 8.6 **Campaign index currency.** This change's row in `openspec/changes/README.md`
      (`admit-relay-proxies-by-grant`, under "Lesser goal — Reach hosts and VMs that have
      no inbound route"): status `in closeout`, notes rewritten to the evidence; the
      campaign graph line `admit-relay-proxies-by-grant ──► prove-relay-provisioning
      (implementation)` unchanged; `make check-change-index`.
- [ ] 8.7 **Packaging.** `make check-packaging`; `make check-architecture-change
      CHANGE=admit-relay-proxies-by-grant`. `make check-agent-skills` is not owed unless
      the change touched `.agents/`, `.claude/`, or `.codex/`.
- [ ] 8.8 **End-to-end pipeline.** Record the pipeline run validating `HEAD` and its
      result. No `e2e-tests` scenario exercises the plugin; its system-level evidence is
      section 6's gate job, its real-frp tests and its floor run, recorded here with its
      run.
- [ ] 8.9 **Promotion.** Write:
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
- [ ] 8.10 **Documentation citations.** `make check-doc-citations
      CHANGE=admit-relay-proxies-by-grant`; `openspec validate admit-relay-proxies-by-grant
      --strict` (the pinned validator, run by `make check-change
      CHANGE=admit-relay-proxies-by-grant`).
- [ ] 8.11 **Archival.** `openspec archive admit-relay-proxies-by-grant -y`, merging the
      delta `specs/frp-grant-admission/` into a new
      `openspec/specs/frp-grant-admission/spec.md` (no `--skip-specs`).
