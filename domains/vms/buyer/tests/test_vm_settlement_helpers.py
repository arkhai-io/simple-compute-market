from domains.vms.provisioning import make_vm_provision_terms
from domains.vms.settlement import escrow_proposal_from_accepted_entry, select_escrow_entry


_ESCROW = "0x" + "11" * 20
_TOKEN = "0x" + "22" * 20
_OTHER = "0x" + "33" * 20
_ARBITER = "0x" + "44" * 20


def test_select_escrow_entry_filters_by_chain_and_token():
    listing = {
        "accepted_escrows": [
            {
                "chain_name": "other",
                "escrow_address": _OTHER,
                "literal_fields": {"token": _OTHER},
            },
            {
                "chain_name": "anvil",
                "escrow_address": _ESCROW,
                "literal_fields": {"token": _TOKEN},
            },
        ],
    }

    assert select_escrow_entry(
        listing,
        chain_name="anvil",
        token_contract_filter=_TOKEN,
        assume_yes=True,
        rpc_url="http://rpc",
        buyer_address="0x" + "aa" * 20,
    )["escrow_address"] == _ESCROW


def test_escrow_proposal_from_accepted_entry_carries_demands_for_selected_chain():
    entry = {
        "chain_name": "anvil",
        "escrow_address": _ESCROW,
        "literal_fields": {"token": _TOKEN},
        "rates": [{"field": "amount", "per": "hour", "value": "100"}],
    }
    listing = {
        "demands": [
            {"chain_name": "other", "arbiter": _OTHER, "demand_data": {}},
            {"chain_name": "anvil", "arbiter": _ARBITER, "demand_data": {"x": 1}},
            {"arbiter": _ARBITER, "demand_data": {"global": True}},
        ],
    }

    proposal = escrow_proposal_from_accepted_entry(
        listing=listing,
        entry=entry,
        expiration_unix=123,
    )

    assert proposal.chain_name == "anvil"
    assert proposal.escrow_address == _ESCROW
    assert proposal.fields == {"token": _TOKEN}
    assert proposal.literal_fields == {"token": _TOKEN}
    assert [rate.model_dump() for rate in proposal.rates] == entry["rates"]
    assert proposal.expiration_unix == 123
    assert [d.arbiter for d in proposal.demands] == [_ARBITER, _ARBITER]


def test_make_vm_provision_terms_uses_compute_compat_shape():
    terms = make_vm_provision_terms(
        duration_seconds=3600,
        ssh_public_key="ssh-ed25519 example",
    )
    assert terms.duration_seconds == 3600
    assert terms.ssh_public_key == "ssh-ed25519 example"
    assert terms.kind == "compute.v1"
