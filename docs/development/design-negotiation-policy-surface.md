# Negotiation policy owns the escrow parameter surface — design + scope

Companion to `design-settlement-lifecycle-and-capacity.md` Part I, which
records that "negotiation vocabulary for proposing/accepting plan shapes
(intervals, bond sizes, oracle choice, mechanism choice) is schema
policy, exactly like price." This doc is the concrete mechanism for that
line on the buyer side: the configured negotiation policy — not the
schema plugin's CLI, not the round loop — is the interface to a deal's
concrete escrow parameters, and the CLI flags are the policy's
projection of its own parameter space.

## Why

Each negotiation policy is compatible with a *set* of escrow formats,
and it is the policy that decides which concrete parameters exist and
whether to expose them transparently (`--max-price`) or opaquely
(`--budget`, or nothing at all for take-it-or-leave formats). Today
that knowledge is smeared across three places that are not the policy:

- **`domains/vms/buyer/buy_cli.py` / `negotiate_cli.py`** hardcode the
  scalar-rate parameter surface (`--initial-price`, `--max-price`,
  `--price-markup`) on the verbs, regardless of which policy the chain
  will actually run.
- **`buyer_client.negotiate_with_seller`** owns the round-0 opening: it
  *sniffs* the escrow shape (`uses_scalar_amount` — `fields.amount`
  present, or token-without-tokenId, or a rate with `field=="amount"`)
  to decide whether the scalar opening bid applies. That heuristic is
  the policy's compatibility knowledge, reconstructed by inspection at
  the wrong layer. The same function picks the escrow tuple implicitly
  (`accepted_escrows[0]`) and hardcodes the per-hour→absolute
  translation.
- **`cli_helpers.resolve_prices_from_matches`** owns price derivation
  and the interactive prompts — strategy-specific behavior (a markup
  ceiling exists *for* haggling room) living in CLI helpers.

What already exists and is correctly placed: the buyer chain itself.
`[negotiation] policies` in buyer.toml composes middleware by name
(`kit/policy` registry), including a per-escrow-kind dispatch map
(`make_escrow_kind_dispatch_middleware`) — so "policy ↔ escrow-format
compatibility" already has a configured home for rounds 1..N. The
seller side has the same shape (guards + terminal as configured
middleware). The gap is everything *around* the chain: flags, round-0
opening, tuple selection, derivation.

## Decisions

- **The policy is the interface to concrete escrow parameters.** A
  policy declares (a) which escrow formats it can negotiate, (b) its
  parameter surface (CLI flags + config keys), and (c) the strategy —
  including the round-0 opening, which today is not chain-driven.
- **Three-way CLI split.** Core owns the verb skeleton, run-log
  chaining, identity/signing. The schema plugin owns *what* is bought
  (filter vocabulary, provision terms, rendering). The policy owns
  *how it is paid for* (escrow tuple selection, price/plan parameters,
  strategy). `--gpu-model` is plugin vocabulary; `--max-price` is
  policy vocabulary.
- **Policy resolution happens at app-assembly time** (buyer.toml), the
  same way schema plugins are resolved — flags on `buy`/`negotiate`
  must exist before parsing, so the policy cannot itself be a flag on
  those verbs. A `--policy-param key=value` escape hatch (analogous to
  `--filter`) covers overrides and policies without named-flag sugar.
- **Escrow tuple selection becomes declared compatibility.** The buyer
  matches the listing's `accepted_escrows` against the configured
  policy's declared formats and picks the first tuple the policy
  claims — refusing with "no compatible escrow format" instead of
  silently taking `accepted_escrows[0]` and hoping.
- **The default policy is `listed_price`** (landed ahead of this doc —
  see work item 1): open at the listing's advertised price and accept
  anything at or under the buyer's bound, never counter. Haggling
  rounds carry no information today — neither side exchanges *reasons*
  for a new number, so bisection against a seller whose floor is
  already published is wasted network traffic and negotiation-watchdog
  state. Bisection stays registered for buyers who opt in
  (`[negotiation] policies`), and becomes interesting again only when
  proposals carry justification (load, duration discounts, plan-shape
  trade-offs) — at which point richer policies join it.
- **There is no "terminal" middleware type, and exhaustion is an
  error.** Every middleware has the same shape — return a decision or
  pass with ``None`` — and whether one decides is not externally
  knowable, so nothing may be appended to a chain *because* it returned
  ``None``: that would just be running a different chain than the one
  configured (you should have configured that chain). A chain that
  exhausts raises ``NegotiationChainExhausted``; the buyer's round loop
  releases the seller's live thread with a protocol-level exit
  (``buyer_chain_no_decision``) before the error propagates. The same
  no-substitution rule applies to resolution: a typo'd
  ``[negotiation] policy`` name errors instead of silently becoming the
  default, and the chain's round-0 decision is honored — exit/reject
  before opening means the seller is never contacted.
- **Hook calling convention: the policy's values are namespaced.** A
  policy hook receives its own collected values (declared ``cli_params``
  plus parsed ``--policy-param`` pairs) as one ``params`` mapping;
  everything else is a canonical keyword the caller always provides
  (``matches``, ``console``, ``interactive``). The two namespaces are
  structurally separate, so a policy parameter can never collide with a
  canonical argument — no reserved-prefix convention needed — and the
  dispatch layer knows no policy's vocabulary (the scalar trio is no
  longer hardcoded anywhere outside the scalar policies).
- **Settlement plans slot in as policies.** When Part I's plan carrier
  lands, an interval-plan or bonded policy contributes its vocabulary
  (`--interval`, bond sizes) through the same seam; `listed_price` and
  the scalar flags are the degenerate single-scalar case.

## Work items

1. **`listed_price` default.** *(Done — landed with this doc.)* New
   terminal middleware in `domains/vms/negotiation/policies.py`: accept
   the seller's proposal when its amount is within the buyer's bound
   (`our_reference_amount`), exit otherwise — no counters beyond the
   opening. `DEFAULT_TERMINAL` flips from `"bisection"` to
   `"listed_price"`. Price derivation when flags are omitted becomes
   silent and direct: initial = max = the listing's advertised price
   (no markup headroom, no interactive prompt — there is nothing to
   confirm when the answer is "pay what's listed"). `--price-markup`
   only applies when `--initial-price` alone is given (bisection-era
   compat for opt-in hagglers). Explicit flags keep their meaning: the
   bound is the user's, and `listed_price` accepts any seller number
   within it.
2. **Policy objects with a registration surface.** *(Done.)*
   `market_policy.buyer_policy` defines `BuyerPolicy`
   (`{middlewares, compatible, cli_params, derive_prices}`) + the
   registry; the VM domain registers `listed_price` and `bisection` in
   `domains/vms/buyer/policy_surface.py`; buyer.toml
   `[negotiation] policy` names the configured one. Variance from the
   sketch: flag injection happens in the schema plugin's `register()`
   (via `inject_policy_cli_params`, `__signature__`-based), not in
   core's `build_app` — core stays free of a kit/policy dependency
   until a second schema plugin shows what is invariant, the same
   criterion as the server scaffold. `--policy-param key=value` lands
   in `context.intermediate` verbatim.
3. **Round-0 moves into the chain.** *(Done.)* The chain runs on an
   empty history to produce the pinned opening; `NegotiationContext`
   carries `our_opening_amount` separately from the bound; the scalar
   policies own the shape test (`escrow_shape_uses_scalar_amount`) —
   exact escrows pass through untouched, and the
   `uses_scalar_amount` heuristic in `negotiate_with_seller` is gone.
   Deferred remainder: the per-hour→absolute translation and
   token-decimals scaling still live in the CLI bodies, not the policy
   object — move them when a policy with non-per-hour semantics
   arrives.
4. **Tuple selection by declared compatibility.** *(Done.)*
   `select_escrow_entry` filters by the configured policy's
   `compatible` predicate; an incompatible-only listing yields "no
   compatible escrow format". Derivation (`derive_scalar_prices`,
   anchored on `extract_seller_min_price`) is the scalar policies' own.
5. **CLI/test migration.** *(Done.)* `buy`/`negotiate` define no
   pricing flags; the configured policy contributes them at app
   assembly (the default surface is byte-for-byte the old one). The
   run-log records the policy name at run start and resume paths
   rebuild the chain from it — a run resumes under the policy that
   opened it, not whatever the config says today.

All five items landed gated on the buyer/storefront suites and the
canonical e2e.
