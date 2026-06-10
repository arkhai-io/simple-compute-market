"""Unit tests for the RL negotiation middleware.

Covers the end-to-end path that production runs:

  1. ``torch_arkhai_strategy`` imports cleanly and self-registers under
     the name ``"rl"`` (chain lookup by name).
  2. ``ArkhaiInferencePolicy`` — the inline replacement for
     ``pufferlib.models.Default`` — is state-dict self-consistent:
     a save/load round-trip preserves outputs bit-for-bit.
  3. ``rl_middleware`` → ``TorchArkhaiStrategy.decide()`` produces the
     right ``NegotiationDecision`` shape across the accept/counter/exit
     branches, with the peer's pinned proposal echoed (only
     ``fields["amount"]`` changes).

The whole file skips when torch isn't installed — the storefront's
default install is bisection-only (``[rl]`` extra opts into torch).
No pufferlib is required at any point; the inline policy runs on
plain torch.
"""
from __future__ import annotations

import pytest

torch = pytest.importorskip("torch")

import domains.vms.negotiation.rl.torch_arkhai_strategy as strat_mod
from domains.vms.negotiation.rl import arkhai_common
from market_policy.negotiation_middleware import (
    NegotiationContext,
    NegotiationDecision,
    NegotiationRound,
    load_negotiation_chain,
    run_negotiation_chain,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


_PEER_SKELETON = {
    "chain_name": "anvil",
    "escrow_address": "0x" + "aa" * 20,
    "fields": {"amount": 0, "token": "0x" + "bb" * 20},
    "expiration_unix": 1_900_000_000,
}


def _peer_proposal(amount: int) -> dict:
    """Build a peer proposal with the canonical pinned skeleton + amount."""
    return {**_PEER_SKELETON, "fields": {**_PEER_SKELETON["fields"], "amount": amount}}


def _round0(direction: str, our_amount: float, their_amount: int) -> tuple[list, NegotiationContext]:
    """Build (history, context) for a round-0 decision against a peer counter."""
    proposal = _peer_proposal(their_amount)
    history = [NegotiationRound(
        round_number=0, sender="them", action="initial", proposal=proposal,
    )]
    context = NegotiationContext(
        direction=direction,
        our_reference_amount=float(our_amount),
        our_escrow_proposal=proposal,
    )
    return history, context


class _StubModel(torch.nn.Module):
    """Deterministic stand-in for the trained pufferlib policy.

    Returns dummy logits; the middleware passes them through
    ``extract_actions_from_logits`` which the fixture monkeypatches
    to return whatever ``price_idx`` the test wants. The model itself
    isn't consulted for the index — only the multiplier branch the
    index selects.
    """

    def forward(self, obs):
        batch = obs.shape[0]
        return (torch.zeros(batch, 9), torch.zeros(batch, 2)), torch.zeros(batch, 1)


@pytest.fixture
def stub_strategy(monkeypatch):
    """Replace the singleton's models with deterministic stubs and
    expose a ``set_price_idx`` knob to control which ``_MULTIPLIERS``
    entry is used per test case.

    _MULTIPLIERS = [-0.20, -0.15, -0.10, -0.05, 0.00, +0.05, +0.10, +0.15, +0.20]
                       0      1      2      3     4     5      6      7      8
    """
    strat_mod._singleton = None
    s = strat_mod._get_singleton()
    s._models = {"maximize": _StubModel(), "minimize": _StubModel()}

    holder = {"price_idx": 5}

    def _fake_extract(output):
        return holder["price_idx"], 0  # (price_idx, sell_flag)

    monkeypatch.setattr(arkhai_common, "extract_actions_from_logits", _fake_extract)

    def set_price_idx(idx: int) -> None:
        holder["price_idx"] = idx

    s.set_price_idx = set_price_idx  # type: ignore[attr-defined]
    yield s
    strat_mod._singleton = None


# ---------------------------------------------------------------------------
# Middleware registration + chain wiring
# ---------------------------------------------------------------------------


class TestMiddlewareRegistration:
    def test_rl_middleware_registers_under_name_rl(self):
        """``torch_arkhai_strategy`` self-registers at import time so
        ``load_negotiation_chain(["rl"])`` resolves it without ceremony."""
        chain = load_negotiation_chain(["rl"])
        assert len(chain) == 1
        assert getattr(chain[0], "__name__", "") == "rl_middleware"

    @pytest.mark.parametrize("name", ["erc20_rl", "native_token_rl", "erc1155_rl"])
    def test_rl_middleware_registers_escrow_family_aliases(self, name):
        chain = load_negotiation_chain([name])
        assert len(chain) == 1
        assert chain[0] is strat_mod.rl_middleware


# ---------------------------------------------------------------------------
# ArkhaiInferencePolicy state-dict round-trip
# ---------------------------------------------------------------------------


class TestArkhaiInferencePolicyShape:
    """The inline replacement for ``pufferlib.models.Default``.

    Validates the arch is self-consistent: build → save state_dict →
    rebuild → load_state_dict strict=True → identical outputs. The
    state-dict layout (encoder.0.{weight,bias}, decoder.{weight,bias},
    value.{weight,bias}) is also what the trained ``.pt`` checkpoints
    carry, so an unintentional rename here would silently break
    inference at load time.
    """

    OBS_DIM = 27  # arkhai_common.obs_dim(node_types=5); matches shipped checkpoints

    def test_build_returns_a_model_when_torch_present(self):
        model = arkhai_common.create_model(self.OBS_DIM)
        assert model is not None
        assert hasattr(model, "encoder")
        assert hasattr(model, "decoder")
        assert hasattr(model, "value")
        assert model.action_nvec == (9, 2)

    def test_forward_pass_shape(self):
        """Outputs: ``(logits=(B,9)+(B,2), values=(B,1))``."""
        model = arkhai_common.create_model(self.OBS_DIM)
        obs = torch.randn(3, self.OBS_DIM)
        with torch.no_grad():
            logits, values = model(obs)
        assert isinstance(logits, tuple) and len(logits) == 2
        assert tuple(logits[0].shape) == (3, 9)
        assert tuple(logits[1].shape) == (3, 2)
        assert tuple(values.shape) == (3, 1)

    def test_state_dict_round_trip_is_bit_identical(self):
        """Save → load preserves outputs exactly. Catches accidental
        arch renames (a key drift would either fail strict load or
        load into a differently-shaped tensor with garbage outputs).

        Layers are Linear + GELU only — no dropout, no batchnorm — so
        ``train()`` and inference modes are equivalent. No ``.eval()``
        flip needed for deterministic outputs.
        """
        a = arkhai_common.create_model(self.OBS_DIM)
        b = arkhai_common.create_model(self.OBS_DIM)

        # Sanity: different random init → different outputs
        torch.manual_seed(0)
        obs = torch.randn(2, self.OBS_DIM)
        with torch.no_grad():
            la, _ = a(obs); lb, _ = b(obs)
        assert not torch.equal(la[0], lb[0]), "fresh-init models should differ"

        # Round-trip the state_dict
        b.load_state_dict(a.state_dict(), strict=True)
        with torch.no_grad():
            la, _ = a(obs); lb, _ = b(obs)
        assert torch.equal(la[0], lb[0])
        assert torch.equal(la[1], lb[1])

    def test_state_dict_keys_match_pufferlib_checkpoint_layout(self):
        """The trained ``.pt`` files use ``encoder.0.{weight,bias}``,
        ``decoder.{weight,bias}``, ``value.{weight,bias}``. Any rename
        in the inline arch breaks ``load_state_dict`` against the
        shipped checkpoints — pin the layout here."""
        model = arkhai_common.create_model(self.OBS_DIM)
        keys = set(model.state_dict().keys())
        assert keys == {
            "encoder.0.weight", "encoder.0.bias",
            "decoder.weight", "decoder.bias",
            "value.weight", "value.bias",
        }, f"state_dict layout drifted: {keys}"


# ---------------------------------------------------------------------------
# decide() decision branches (seller-side = maximize)
# ---------------------------------------------------------------------------


class TestSellerDecisions:
    """Seller (``direction='maximize'``): accept high peer offers,
    counter mid-range, exit on lowball."""

    def test_counters_with_proposed_amount_echoing_peer_skeleton(self, stub_strategy):
        """Peer below proposed but above reasonable → counter at
        ``our_reference * (1 + multiplier)``. The returned proposal
        copies every pinned field from the peer's skeleton and only
        overrides ``fields["amount"]``."""
        stub_strategy.set_price_idx(5)  # +5% → proposed = 10500
        history, ctx = _round0("maximize", our_amount=10_000, their_amount=9500)
        chain = load_negotiation_chain(["rl"])
        decision = run_negotiation_chain(chain, history, ctx)

        assert decision.action == "counter"
        assert decision.proposal is not None
        assert decision.proposal["fields"]["amount"] == 10500
        # Peer skeleton echoed verbatim except amount
        assert decision.proposal["chain_name"] == _PEER_SKELETON["chain_name"]
        assert decision.proposal["escrow_address"] == _PEER_SKELETON["escrow_address"]
        assert decision.proposal["fields"]["token"] == _PEER_SKELETON["fields"]["token"]
        assert decision.proposal["expiration_unix"] == _PEER_SKELETON["expiration_unix"]

    def test_accepts_when_peer_within_convergence_of_proposed(self, stub_strategy):
        """``their >= proposed * (1 - conv)`` → accept at the peer's amount."""
        stub_strategy.set_price_idx(5)  # +5% → proposed = 10500
        # 10395 = 10500 * (1 - 0.01) — the convergence threshold
        history, ctx = _round0("maximize", our_amount=10_000, their_amount=10400)
        chain = load_negotiation_chain(["rl"])
        decision = run_negotiation_chain(chain, history, ctx)

        assert decision.action == "accept"
        assert decision.reason == "convergence"
        assert decision.proposal["fields"]["amount"] == 10400

    def test_exits_when_peer_below_reasonable_threshold(self, stub_strategy):
        """``their < our / reasonable`` → exit price_unreasonable.
        reasonable=1.5 → floor = 10000 / 1.5 ≈ 6667."""
        stub_strategy.set_price_idx(4)  # 0% multiplier
        history, ctx = _round0("maximize", our_amount=10_000, their_amount=1_000)
        chain = load_negotiation_chain(["rl"])
        decision = run_negotiation_chain(chain, history, ctx)

        assert decision.action == "exit"
        assert decision.reason == "price_unreasonable"
        assert decision.proposal is None


# ---------------------------------------------------------------------------
# decide() decision branches (buyer-side = minimize)
# ---------------------------------------------------------------------------


class TestBuyerDecisions:
    """Buyer (``direction='minimize'``): accept low peer offers,
    counter clamped at our ceiling, exit on ask-too-high."""

    def test_accepts_when_peer_below_proposed_within_convergence(self, stub_strategy):
        """``their <= proposed * (1 + conv)`` → accept at the peer's amount."""
        stub_strategy.set_price_idx(5)  # +5% → proposed = 10500
        history, ctx = _round0("minimize", our_amount=10_000, their_amount=9500)
        chain = load_negotiation_chain(["rl"])
        decision = run_negotiation_chain(chain, history, ctx)

        assert decision.action == "accept"
        assert decision.reason == "convergence"
        assert decision.proposal["fields"]["amount"] == 9500

    def test_counter_clamped_at_our_reference_ceiling(self, stub_strategy):
        """When the model's proposed amount exceeds our ceiling, the
        counter is clamped to ``our_reference_amount`` — the buyer
        never bids above its own ceiling.

        Picks ``their=13000`` to land between the convergence threshold
        (proposed*1.01 = 12120) and the reasonable ceiling (our*1.5 =
        15000), so the flow reaches the clamp branch instead of
        accepting on convergence.
        """
        stub_strategy.set_price_idx(8)  # +20% → proposed = 12000, above ceiling 10000
        history, ctx = _round0("minimize", our_amount=10_000, their_amount=13_000)
        chain = load_negotiation_chain(["rl"])
        decision = run_negotiation_chain(chain, history, ctx)

        assert decision.action == "counter"
        assert decision.proposal["fields"]["amount"] == 10_000

    def test_exits_when_peer_above_reasonable_threshold(self, stub_strategy):
        """``their > our * reasonable`` → exit price_unreasonable.
        reasonable=1.5 → ceiling = 10000 * 1.5 = 15000."""
        stub_strategy.set_price_idx(4)  # 0%
        history, ctx = _round0("minimize", our_amount=10_000, their_amount=20_000)
        chain = load_negotiation_chain(["rl"])
        decision = run_negotiation_chain(chain, history, ctx)

        assert decision.action == "exit"
        assert decision.reason == "price_unreasonable"


# ---------------------------------------------------------------------------
# Edge cases: open counter, max rounds, stale, model unavailable
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_open_counter_with_no_peer(self, stub_strategy):
        """First counter with no peer proposal yet — opens at
        ``our_reference_amount`` with a minimal proposal dict
        (no skeleton to echo)."""
        chain = load_negotiation_chain(["rl"])
        ctx = NegotiationContext(direction="maximize", our_reference_amount=10_000.0)
        decision = run_negotiation_chain(chain, [], ctx)

        assert decision.action == "counter"
        assert decision.proposal == {"fields": {"amount": 10_000}}

    def test_max_rounds_exit(self, stub_strategy):
        """After ``max_rounds`` of our counters, the chain exits before
        consulting the model."""
        history, ctx = _round0("maximize", our_amount=10_000, their_amount=9500)
        # Inject prior "us" counter rounds
        us = _peer_proposal(10_500)
        for i in range(ctx.max_rounds):
            history.append(NegotiationRound(
                round_number=i + 1, sender="us", action="counter", proposal=us,
            ))
        chain = load_negotiation_chain(["rl"])
        decision = run_negotiation_chain(chain, history, ctx)

        assert decision.action == "exit"
        assert decision.reason == "max_rounds"

    def test_stale_negotiation_exit(self, stub_strategy):
        """Our last two counters identical → exit ``stale_negotiation``."""
        history, ctx = _round0("maximize", our_amount=10_000, their_amount=9500)
        us = _peer_proposal(10_500)
        history.extend([
            NegotiationRound(round_number=1, sender="us", action="counter", proposal=us),
            NegotiationRound(round_number=2, sender="us", action="counter", proposal=us),
        ])
        chain = load_negotiation_chain(["rl"])
        decision = run_negotiation_chain(chain, history, ctx)

        assert decision.action == "exit"
        assert decision.reason == "stale_negotiation"

    def test_exits_when_model_unavailable(self, stub_strategy):
        """No model loaded for the direction → ``rl_model_unavailable``.

        Set the cached entry to ``None`` (rather than purging the
        dict) so the strategy's ``_get_model`` short-circuits on the
        ``direction in self._models`` lookup without trying to read
        the real ``.pt`` file from disk.
        """
        stub_strategy._models = {"maximize": None}
        history, ctx = _round0("maximize", our_amount=10_000, their_amount=9500)
        chain = load_negotiation_chain(["rl"])
        decision = run_negotiation_chain(chain, history, ctx)

        assert decision.action == "exit"
        assert decision.reason == "rl_model_unavailable"
