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
2. **Policy objects with a registration surface.** Extend the
   `kit/policy` registry entry from a bare middleware callable to a
   policy object: `{middleware, compatible_formats, cli_params,
   build_context}` (a `BuyerPolicyPlugin`, mirroring
   `BuyerSchemaPlugin`). `build_app` resolves the configured policy
   from buyer.toml and lets it register its flags on `buy`/`negotiate`;
   `--policy-param` lands in `context.intermediate`.
3. **Round-0 moves into the chain.** `negotiate_with_seller` asks the
   policy for the opening proposal (the chain already has an
   `"initial"` action in its vocabulary) instead of injecting
   `fields.amount` behind the `uses_scalar_amount` heuristic. The
   per-hour→absolute translation and token-decimals scaling move into
   the scalar policies' `build_context`.
4. **Tuple selection by declared compatibility.** Replace
   `accepted_escrows[0]` + shape sniffing with policy-driven matching;
   `extract_seller_min_price` becomes the scalar policies' anchor
   helper rather than a free function the orchestrator owns.
5. **CLI/test migration.** `buy`/`negotiate` lose the hardcoded pricing
   flags (re-contributed by the default policy, so the surface is
   unchanged for users); resume paths read the policy from the run-log
   so a run resumes under the policy that started it; buyer + e2e
   suites updated.

Items 2–4 land together or not at all (the seam is one cut); item 5
follows. Each lands gated on the buyer/storefront suites and the
canonical e2e, like every reorganization slice.
