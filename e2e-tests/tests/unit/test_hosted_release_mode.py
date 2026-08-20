"""Provenance classifies a run; it does not decide whether the body may run."""

from __future__ import annotations

import hashlib
import itertools
import json
from pathlib import Path

import pytest

from src.hosted_real_stripe.driver import _parser
from src.hosted_real_stripe.evidence import (
    HostedReleaseIdentityEvidence,
    IdentityEvidence,
    MarketplaceIdentityEvidence,
)
from src.hosted_real_stripe.gates import (
    LOCAL_COORDINATE,
    AuthorizationRejected,
    AuthorizationUnavailable,
    ReleaseIdentityRejected,
    local_release_identity,
    require_connected_account,
    require_loopback_webhook,
    require_release_identity,
    require_test_secret,
)

DIGEST = "sha256:" + "a" * 64
IMAGE = "sha256:" + "c" * 64
WHEEL = "sha256:" + "d" * 64
MARKET_DIGEST = "sha256:" + "e" * 64
MARKET_IMAGE = "sha256:" + "f" * 64
HOSTED_COMMIT = "a" * 40
TRUSTED_COMMIT = "c" * 40
OBSERVED_COMMIT = "b" * 40
MARKET_REF = ".github/workflows/publish.yml@refs/tags/v0.2.0"

CAPABILITIES = (
    "scheme-tagged-identities.v1",
    "account-owner-admission.v1",
    "account-owner-rotation.v1",
    "account-owner-retirement.v1",
    "signer-injected-client.v1",
    "provider-neutral-seller-onboarding.v1",
    "conditional-escrow.v2",
    "stripe-connect-separate-charges-transfers.v2",
    "portable-attestation.v1",
    "eas-arbiter.v1",
    "payer-profile.v1",
    "funding-authorization.v1",
    "funding-profile.card.v1",
    "funding-profile.us_bank_transfer.v1",
    "funding-profile.us_ach_debit.v1",
    "normalized-funding-reversal.v1",
    "operator-recovery-redaction.v1",
)
PROFILES = ("card.v1", "us_bank_transfer.v1", "us_ach_debit.v1")


def _stage_contract(
    directory: Path,
    *,
    version: str = "0.2.1",
    schema: int = 5,
    capabilities: tuple[str, ...] = CAPABILITIES,
    profiles: tuple[str, ...] = PROFILES,
) -> tuple[Path, str]:
    """Write what a bound release states it serves, released or built here.

    Both kinds of producer generate this artifact; only a released one has its
    hash covered by a signature.
    """

    directory.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(
        {
            "api_version": version,
            "schema_version": schema,
            "funding_profiles": list(profiles),
            "identity_contract": {"capabilities": list(capabilities)},
        }
    ).encode()
    (directory / f"conformance-v{version}.json").write_bytes(raw)
    return directory, "sha256:" + hashlib.sha256(raw).hexdigest()


#: A locally rendered environment is structurally complete -- every allowlisted
#: key is present -- and simply has nothing to say for the coordinates a local
#: build has no released source for.
_LOCAL_MARKETPLACE = {
    "HOSTED_MARKETPLACE_VERIFIED_ARTIFACT_PROVENANCE_SHA256": "",
    "HOSTED_MARKETPLACE_VERIFIED_ARTIFACT_SCHEMA_SHA256": "",
    "HOSTED_MARKETPLACE_VERIFIED_ARTIFACT_WHEELHOUSE_SHA256": "",
    "HOSTED_MARKETPLACE_VERIFIED_IMAGE": "",
    "HOSTED_MARKETPLACE_VERIFIED_MANIFEST_SHA256": "",
    "HOSTED_MARKETPLACE_VERIFIED_REPOSITORY": "arkhai-io/simple-compute-market",
    "HOSTED_MARKETPLACE_VERIFIED_SOURCE_COMMIT": "",
    "HOSTED_MARKETPLACE_VERIFIED_WORKFLOW_REF": "",
    "HOSTED_MARKETPLACE_VERIFIED_WORKFLOW_RUN_ID": "",
}


def _released_hosted(
    release_dir: Path,
    conformance_sha: str,
    *,
    version: str = "0.2.1",
    schema: int = 5,
    capabilities: tuple[str, ...] = CAPABILITIES,
    profiles: tuple[str, ...] = PROFILES,
) -> dict[str, str]:
    return {
        "HOSTED_SETTLEMENT_VERIFIED_IMAGE": "registry.example/authority@" + IMAGE,
        "HOSTED_SETTLEMENT_VERIFIED_MANIFEST_SHA256": DIGEST,
        "HOSTED_SETTLEMENT_VERIFIED_CLIENT_WHEEL_SHA256": WHEEL,
        "HOSTED_SETTLEMENT_VERIFIED_RELEASE_DIR": str(release_dir),
        "HOSTED_SETTLEMENT_VERIFIED_SOURCE_COMMIT": HOSTED_COMMIT,
        "HOSTED_SETTLEMENT_VERIFIED_REPOSITORY": "arkhai-io/stripe-settlement-service",
        "HOSTED_SETTLEMENT_VERIFIED_WORKFLOW_REF": (
            ".github/workflows/release.yml@main"
        ),
        "HOSTED_SETTLEMENT_VERIFIED_MANIFEST_DIGEST": DIGEST,
        "HOSTED_SETTLEMENT_VERIFIED_AUTHORITY_ID": "hosted-authority",
        "HOSTED_SETTLEMENT_VERIFIED_AUTHORITY_SCHEME": "eip191",
        "HOSTED_SETTLEMENT_VERIFIED_AUTHORITY_ADDRESS": "0x" + "1" * 40,
        "HOSTED_SETTLEMENT_VERIFIED_API_VERSION": version,
        "HOSTED_SETTLEMENT_VERIFIED_SCHEMA_VERSION": str(schema),
        "HOSTED_SETTLEMENT_VERIFIED_RELEASE_VERSION": version,
        "HOSTED_SETTLEMENT_VERIFIED_CONFORMANCE_SHA256": conformance_sha,
        "HOSTED_SETTLEMENT_VERIFIED_MIGRATIONS_SHA256": DIGEST,
        "HOSTED_SETTLEMENT_VERIFIED_OPENAPI_SHA256": DIGEST,
        "HOSTED_SETTLEMENT_VERIFIED_PROVENANCE_SHA256": DIGEST,
        "HOSTED_SETTLEMENT_VERIFIED_SERVICE_WHEEL_SHA256": DIGEST,
        "HOSTED_SETTLEMENT_VERIFIED_FUNDING_PROFILES": ",".join(profiles),
        "HOSTED_SETTLEMENT_VERIFIED_CAPABILITIES": ",".join(capabilities),
    }


def _local_hosted(
    release_dir: Path,
    _conformance_sha: str,
    *,
    version: str = "0.2.1",
    schema: int = 5,
    capabilities: tuple[str, ...] = CAPABILITIES,
    profiles: tuple[str, ...] = PROFILES,
) -> dict[str, str]:
    """Every provenance key empty; the contract keys read from the build."""

    values = _released_hosted(
        release_dir,
        "",
        version=version,
        schema=schema,
        capabilities=capabilities,
        profiles=profiles,
    )
    values.update(
        {
            "HOSTED_SETTLEMENT_VERIFIED_AUTHORITY_ADDRESS": "",
            "HOSTED_SETTLEMENT_VERIFIED_AUTHORITY_ID": "",
            "HOSTED_SETTLEMENT_VERIFIED_AUTHORITY_SCHEME": "",
            "HOSTED_SETTLEMENT_VERIFIED_CLIENT_WHEEL_SHA256": "",
            "HOSTED_SETTLEMENT_VERIFIED_CONFORMANCE_SHA256": "",
            "HOSTED_SETTLEMENT_VERIFIED_MANIFEST_SHA256": "",
            "HOSTED_SETTLEMENT_VERIFIED_MIGRATIONS_SHA256": "",
            "HOSTED_SETTLEMENT_VERIFIED_OPENAPI_SHA256": "",
            "HOSTED_SETTLEMENT_VERIFIED_PROVENANCE_SHA256": "",
            "HOSTED_SETTLEMENT_VERIFIED_SERVICE_WHEEL_SHA256": "",
            "HOSTED_SETTLEMENT_VERIFIED_SOURCE_COMMIT": "",
            "HOSTED_SETTLEMENT_VERIFIED_WORKFLOW_REF": "",
            # Named, not pinned: a build here has an image id, not a digest.
            "HOSTED_SETTLEMENT_VERIFIED_IMAGE": "localhost/authority:0.3.0",
        }
    )
    return values


#: Every rendered environment gets its own directory. A test that prepares one
#: and then passes it in would otherwise have it overwritten by the default
#: another helper renders on the way past.
_ENVIRONMENTS = itertools.count()


def _compose_env(
    tmp_path: Path,
    *,
    hosted=_released_hosted,
    hosted_options: dict | None = None,
    hosted_overrides: dict[str, str] | None = None,
    **marketplace: str,
) -> Path:
    options = dict(hosted_options or {})
    directory = tmp_path / f"env{next(_ENVIRONMENTS)}"
    release_dir, conformance_sha = _stage_contract(directory / "release", **options)
    values = {
        **_LOCAL_MARKETPLACE,
        **marketplace,
        **hosted(release_dir, conformance_sha, **options),
        **(hosted_overrides or {}),
    }
    path = directory / "hosted.env"
    path.write_text(
        "\n".join(f"{key}={value}" for key, value in values.items()) + "\n",
        encoding="utf-8",
    )
    return path


def _staged_contract_path(compose_env: Path, version: str = "0.2.1") -> Path:
    return compose_env.parent / "release" / f"conformance-v{version}.json"


def _local(tmp_path: Path, *, observed: str = OBSERVED_COMMIT, **overrides):
    arguments = {
        "observed_marketplace_commit": observed,
        "hosted_source_commit": HOSTED_COMMIT,
        "hosted_workflow_run_id": "123456",
        "hosted_workflow_ref": ".github/workflows/release.yml@main",
        "hosted_manifest_sha256": DIGEST,
        "hosted_client_wheel_sha256": WHEEL,
        "hosted_image_digest": IMAGE,
        "compose_env_path": _compose_env(tmp_path),
    }
    arguments.update(overrides)
    return local_release_identity(**arguments)


def _local_producer(tmp_path: Path, **overrides):
    """A development run whose producer was built here, not published."""

    arguments = {
        "observed_marketplace_commit": OBSERVED_COMMIT,
        "compose_env_path": _compose_env(tmp_path, hosted=_local_hosted),
    }
    arguments.update(overrides)
    return local_release_identity(**arguments)


def test_a_development_run_records_its_own_commit_and_says_it_is_local(tmp_path) -> None:
    identity = _local(tmp_path)

    assert identity.mode == "local"
    assert identity.marketplace_commit == OBSERVED_COMMIT
    # No attested marketplace coordinate exists for a locally built stack, and
    # the record says so rather than inventing or omitting one.
    assert identity.marketplace_image_digest == LOCAL_COORDINATE
    assert identity.marketplace_manifest_sha256 == LOCAL_COORDINATE
    assert identity.marketplace_workflow_run_id == LOCAL_COORDINATE


def test_a_development_run_binds_the_released_producer_exactly(tmp_path) -> None:
    """Only the marketplace half is locally built; the producer is still signed."""

    identity = _local(tmp_path)

    assert identity.hosted_image_digest == IMAGE
    assert identity.hosted_manifest_sha256 == DIGEST
    assert identity.hosted_authority_scheme == "eip191"

    with pytest.raises(ReleaseIdentityRejected):
        _local(tmp_path, hosted_image_digest="sha256:" + "0" * 64)
    with pytest.raises(ReleaseIdentityRejected):
        _local(tmp_path, hosted_source_commit="f" * 40)
    with pytest.raises(ReleaseIdentityRejected):
        _local(tmp_path, hosted_workflow_run_id="not-a-run")


def test_a_development_run_still_needs_a_real_working_tree_commit(tmp_path) -> None:
    with pytest.raises(ReleaseIdentityRejected):
        _local(tmp_path, observed="not-a-commit")


def _attested_env(tmp_path: Path, **options) -> Path:
    return _compose_env(
        tmp_path,
        **options,
        HOSTED_MARKETPLACE_VERIFIED_ARTIFACT_PROVENANCE_SHA256=DIGEST,
        HOSTED_MARKETPLACE_VERIFIED_ARTIFACT_SCHEMA_SHA256=DIGEST,
        HOSTED_MARKETPLACE_VERIFIED_ARTIFACT_WHEELHOUSE_SHA256=DIGEST,
        HOSTED_MARKETPLACE_VERIFIED_IMAGE="registry.example/marketplace@" + MARKET_IMAGE,
        HOSTED_MARKETPLACE_VERIFIED_MANIFEST_SHA256=MARKET_DIGEST,
        HOSTED_MARKETPLACE_VERIFIED_SOURCE_COMMIT=TRUSTED_COMMIT,
        HOSTED_MARKETPLACE_VERIFIED_WORKFLOW_REF=MARKET_REF,
        HOSTED_MARKETPLACE_VERIFIED_WORKFLOW_RUN_ID="654321",
    )


def _attested(tmp_path: Path, **overrides):
    arguments = {
        "marketplace_commit": TRUSTED_COMMIT,
        "observed_marketplace_commit": TRUSTED_COMMIT,
        "marketplace_workflow_run_id": "654321",
        "marketplace_workflow_ref": MARKET_REF,
        "marketplace_manifest_sha256": MARKET_DIGEST,
        "marketplace_image_digest": MARKET_IMAGE,
        "hosted_source_commit": HOSTED_COMMIT,
        "hosted_workflow_run_id": "123456",
        "hosted_workflow_ref": ".github/workflows/release.yml@main",
        "hosted_manifest_sha256": DIGEST,
        "hosted_client_wheel_sha256": WHEEL,
        "hosted_image_digest": IMAGE,
        "compose_env_path": _attested_env(tmp_path),
    }
    arguments.update(overrides)
    return require_release_identity(**arguments)


def test_an_attested_run_is_recorded_as_attested(tmp_path) -> None:
    assert _attested(tmp_path).mode == "attested"


def test_a_protected_run_fails_closed_rather_than_downgrading(tmp_path) -> None:
    """A branch cannot become evidence by failing the commit check."""

    with pytest.raises(ReleaseIdentityRejected):
        _attested(tmp_path, observed_marketplace_commit=OBSERVED_COMMIT)


def test_a_newer_hosted_release_is_bound_without_a_harness_edit(tmp_path) -> None:
    """Nothing about 0.3.0 or schema 6 is written down here or in the gates."""

    later = {
        "version": "0.3.0",
        "schema": 6,
        "capabilities": (*CAPABILITIES, "payer-direct-instrument-setup.v1"),
    }
    identity = _local(
        tmp_path,
        compose_env_path=_compose_env(tmp_path, hosted_options=later),
    )

    assert identity.hosted_contract.release_version == "0.3.0"
    assert identity.hosted_contract.schema_version == "6"
    assert "payer-direct-instrument-setup.v1" in identity.hosted_contract.capabilities


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("HOSTED_SETTLEMENT_VERIFIED_API_VERSION", "0.9.9"),
        ("HOSTED_SETTLEMENT_VERIFIED_SCHEMA_VERSION", "9"),
        ("HOSTED_SETTLEMENT_VERIFIED_FUNDING_PROFILES", "card.v1"),
        ("HOSTED_SETTLEMENT_VERIFIED_CAPABILITIES", "payer-profile.v1"),
    ],
)
def test_an_authority_that_does_not_serve_the_bound_contract_is_refused(
    tmp_path, key: str, value: str
) -> None:
    """The disagreement is named, and named before Compose creates anything."""

    with pytest.raises(ReleaseIdentityRejected, match="does not serve the bound"):
        _local(
            tmp_path,
            compose_env_path=_compose_env(tmp_path, hosted_overrides={key: value}),
        )


def test_a_released_producer_still_pins_the_contract_artifact_by_hash(
    tmp_path,
) -> None:
    """The trust root is unchanged: the signature covers what is read."""

    path = _compose_env(tmp_path)
    staged = _staged_contract_path(path)
    staged.write_text(staged.read_text(encoding="utf-8") + " ", encoding="utf-8")

    with pytest.raises(ReleaseIdentityRejected, match="not the one the release signed"):
        _local(tmp_path, compose_env_path=path)


def test_a_locally_built_producer_is_bound_and_says_it_has_no_release(
    tmp_path,
) -> None:
    identity = _local_producer(tmp_path)

    assert identity.mode == "local"
    assert identity.hosted_image == "localhost/authority:0.3.0"
    assert identity.hosted_manifest_sha256 == LOCAL_COORDINATE
    assert identity.hosted_authority_id == LOCAL_COORDINATE
    assert identity.hosted_source_commit == LOCAL_COORDINATE
    # What it serves is asserted exactly as a released producer's is.
    assert identity.hosted_contract.capabilities == frozenset(CAPABILITIES)


def test_a_local_producer_without_its_contract_artifacts_fails_closed(
    tmp_path,
) -> None:
    """It reports what is missing, not another release's coordinates."""

    path = _compose_env(tmp_path, hosted=_local_hosted)
    _staged_contract_path(path).unlink()

    with pytest.raises(ReleaseIdentityRejected, match="conformance-v0.2.1.json"):
        _local_producer(tmp_path, compose_env_path=path)


def test_a_local_producer_may_not_be_handed_released_coordinates(tmp_path) -> None:
    """There are none to hand it, so supplying any means something is wrong."""

    with pytest.raises(ReleaseIdentityRejected, match="no released coordinates"):
        _local_producer(tmp_path, hosted_manifest_sha256=DIGEST)


def test_a_half_released_producer_environment_is_refused(tmp_path) -> None:
    with pytest.raises(ReleaseIdentityRejected, match="not partly both"):
        _local_producer(
            tmp_path,
            compose_env_path=_compose_env(
                tmp_path,
                hosted=_local_hosted,
                hosted_overrides={
                    "HOSTED_SETTLEMENT_VERIFIED_MANIFEST_SHA256": DIGEST
                },
            ),
        )


def test_a_protected_run_refuses_a_locally_built_producer(tmp_path) -> None:
    """No flag raises a development stack to attested; the binding refuses it."""

    with pytest.raises(ReleaseIdentityRejected, match="never a locally built one"):
        _attested(
            tmp_path,
            compose_env_path=_attested_env(tmp_path, hosted=_local_hosted),
        )


def test_every_combination_of_released_and_local_halves_admits(tmp_path) -> None:
    """Four combinations run; exactly one of them may be recorded attested."""

    both_released = _attested(
        tmp_path / "a", compose_env_path=_attested_env(tmp_path / "a")
    )
    local_consumer = _local(tmp_path / "b", compose_env_path=_compose_env(tmp_path / "b"))
    local_producer = _local_producer(tmp_path / "c")
    both_local = _local_producer(
        tmp_path / "d",
        compose_env_path=_compose_env(tmp_path / "d", hosted=_local_hosted),
    )
    released_consumer_local_producer = local_release_identity(
        observed_marketplace_commit=TRUSTED_COMMIT,
        compose_env_path=_attested_env(tmp_path / "e", hosted=_local_hosted),
    )

    assert both_released.mode == "attested"
    for development in (
        local_consumer,
        local_producer,
        both_local,
        released_consumer_local_producer,
    ):
        assert development.mode == "local"


def test_a_bound_release_that_lacks_a_scenario_capability_says_so(tmp_path) -> None:
    """The prerequisite is named before the run reaches for it."""

    from src.hosted_real_stripe.gates import require_hosted_capabilities

    identity = _local_producer(tmp_path)

    require_hosted_capabilities(
        identity.hosted_contract, frozenset({"funding-profile.card.v1"})
    )
    with pytest.raises(
        AuthorizationUnavailable, match="payer-direct-instrument-setup.v1"
    ):
        require_hosted_capabilities(
            identity.hosted_contract,
            frozenset({"payer-direct-instrument-setup.v1"}),
        )


def test_no_safety_gate_takes_a_mode_or_a_release(tmp_path) -> None:
    """Design D4, checked mechanically rather than by reading.

    Every branch this change adds sits below the provenance split. A safety
    assertion that grew a mode parameter would be configurable out of, which is
    the one thing none of them may become.
    """

    import inspect

    from src.hosted_real_stripe import gates

    for name in (
        "require_test_secret",
        "require_connected_account",
        "require_loopback_webhook",
        "verify_loopback_webhook_endpoint",
        "require_ready_account",
    ):
        parameters = set(inspect.signature(getattr(gates, name)).parameters)
        assert not parameters & {
            "mode",
            "release_mode",
            "released",
            "allow_local",
            "release",
        }, name
    source = inspect.getsource(gates)
    body = source[source.index("def require_test_secret") :]
    assert "release_mode" not in body


def test_safety_gates_are_not_mode_aware() -> None:
    """They take no mode, so no run can be configured out of them."""

    with pytest.raises(AuthorizationRejected):
        require_test_secret("sk_live_private")
    with pytest.raises(AuthorizationUnavailable):
        require_test_secret(None)
    with pytest.raises(AuthorizationRejected):
        require_loopback_webhook("https://authority.example/webhooks/stripe")
    with pytest.raises(AuthorizationRejected):
        require_connected_account("not-an-account")


def test_the_driver_defaults_to_attested_and_accepts_local() -> None:
    parser = _parser()
    base = [
        "--compose-env", "compose.env",
        "--hosted-manifest-sha256", DIGEST,
        "--hosted-client-wheel-sha256", WHEEL,
        "--hosted-image-digest", IMAGE,
        "--hosted-source-commit", HOSTED_COMMIT,
        "--hosted-workflow-run-id", "123456",
        "--hosted-workflow-ref", ".github/workflows/release.yml@main",
        "--observed-marketplace-commit", OBSERVED_COMMIT,
        "--run-identity", "trusted-run-identity",
        "--scenario", "collection",
        "--funding-profile", "card.v1",
        "--interaction", "interactive",
        "--evidence", "evidence.json",
        "--account-ref", "acct_1TestAccount",
        "--authority-environment", "hosted-stripe-test",
    ]

    assert parser.parse_args(base).release_mode == "attested"
    assert parser.parse_args([*base, "--release-mode", "local"]).release_mode == "local"
    with pytest.raises(SystemExit):
        parser.parse_args([*base, "--release-mode", "attested-ish"])


def test_evidence_knows_which_runs_may_be_cited() -> None:
    marketplace = MarketplaceIdentityEvidence(
        repository="arkhai-io/simple-compute-market",
        commit=TRUSTED_COMMIT,
        workflow_run_id="654321",
        workflow_ref=MARKET_REF,
        manifest_sha256=MARKET_DIGEST,
        image_digest=MARKET_IMAGE,
        image="registry.example/marketplace@" + MARKET_IMAGE,
        wheelhouse_sha256=DIGEST,
        settlement_config_schema_sha256=DIGEST,
        provenance_sha256=DIGEST,
    )
    hosted = HostedReleaseIdentityEvidence(
        repository="arkhai-io/stripe-settlement-service",
        source_commit=HOSTED_COMMIT,
        workflow_run_id="123456",
        workflow_ref=".github/workflows/release.yml@main",
        manifest_sha256=DIGEST,
        client_wheel_sha256=WHEEL,
        image_digest=IMAGE,
    )
    attested = IdentityEvidence(
        marketplace=marketplace, hosted_release=hosted, run_ref="run_abc"
    )

    assert attested.release_mode == "attested"
    assert attested.qualifies is True
    assert not IdentityEvidence(
        marketplace=marketplace,
        hosted_release=hosted,
        run_ref="run_abc",
        release_mode="local",
    ).qualifies


def test_a_development_run_can_read_what_a_protected_run_must_not(tmp_path) -> None:
    """The staged output that names the failure is exactly what leaks."""

    import sys

    from src.hosted_real_stripe.runtime import MarketplaceLifecycleSession, ProcessUnavailable

    # Writes to stderr and exits at once, which is how a bridge that dies on
    # startup behaves: stdout reaches EOF before stderr has been drained.
    command = [
        sys.executable,
        "-c",
        (
            "import sys; print('a payer profile could not be created', file=sys.stderr);"
            "sys.stderr.flush()"
        ),
    ]

    protected = MarketplaceLifecycleSession(command, cwd=tmp_path, request_timeout=10.0)
    protected.start()
    try:
        with pytest.raises(ProcessUnavailable) as refused:
            protected.request("ensure_payer_profile_fixture")
    finally:
        protected.stop()
    assert "payer profile could not be created" not in str(refused.value)

    development = MarketplaceLifecycleSession(
        command,
        cwd=tmp_path,
        request_timeout=10.0,
        retain_diagnostics=True,
    )
    development.start()
    try:
        with pytest.raises(ProcessUnavailable) as disclosed:
            development.request("ensure_payer_profile_fixture")
    finally:
        development.stop()
    assert "payer profile could not be created" in str(disclosed.value)


def test_only_a_development_run_prints_the_failure_behind_the_code(capsys) -> None:
    """Nothing but the proven mode may turn the disclosure on."""

    from src.hosted_real_stripe.driver import _disclose
    from src.hosted_real_stripe.runtime import ProcessUnavailable

    cause = RuntimeError("the storefront never registered a payer profile")
    caught = ProcessUnavailable("marketplace lifecycle state was unavailable")
    caught.__cause__ = cause

    _disclose(caught, mode="attested", stage="payer_profile", code="payer_profile_unavailable")
    assert capsys.readouterr().err == ""

    _disclose(caught, mode="local", stage="payer_profile", code="payer_profile_unavailable")
    printed = capsys.readouterr().err
    assert "payer_profile -> payer_profile_unavailable" in printed
    assert "marketplace lifecycle state was unavailable" in printed
    # The cause chain is what a stage-level code otherwise throws away.
    assert "the storefront never registered a payer profile" in printed


def test_the_driver_asks_for_the_tail_only_when_the_run_is_local() -> None:
    """The session is constructed from the proven mode, not from the flag."""

    source = (
        Path(__file__).resolve().parents[2] / "src" / "hosted_real_stripe" / "driver.py"
    ).read_text(encoding="utf-8")

    assert 'retain_diagnostics=release.mode == "local"' in source


def _teardown_argv(tmp_path, **options) -> tuple[str, ...]:
    from src.hosted_real_stripe.runtime import ComposeStack

    stack = ComposeStack(
        compose_env=tmp_path / "compose.env",
        compose_files=(tmp_path / "compose.yml",),
        cwd=tmp_path,
        **options,
    )
    recorded: list[tuple[str, ...]] = []
    stack._run = lambda argv, **_kwargs: recorded.append(tuple(argv))  # type: ignore[method-assign]
    stack.stop()
    assert len(recorded) == 1
    return recorded[0]


def test_a_run_does_not_inherit_the_previous_run_authority_state(tmp_path) -> None:
    """One run, one authority database — a second bind is a hard conflict."""

    assert _teardown_argv(tmp_path)[-3:] == ("down", "--remove-orphans", "--volumes")


def test_a_retained_run_drops_only_the_anonymous_volumes_it_added(tmp_path) -> None:
    """The cache is a named volume; a service's scratch space is not.

    Sparing the named volume also spares every anonymous one, which leaks a
    volume per run. Only volumes this run added are removed, and only the
    unnamed ones — anything that predates the stack belongs to somebody else.
    """

    from src.hosted_real_stripe.runtime import ComposeStack

    mine = "f" * 64
    theirs = "a" * 64
    stack = ComposeStack(
        compose_env=tmp_path / "compose.env",
        compose_files=(tmp_path / "compose.yml",),
        cwd=tmp_path,
        retain_authority_state=True,
    )
    stack._preexisting_volumes = frozenset({theirs})  # type: ignore[assignment]
    stack._volumes = lambda: frozenset({theirs, mine, "vms_hosted-settlement-data"})  # type: ignore[method-assign]
    recorded: list[tuple[str, ...]] = []
    stack._run = lambda argv, **_kwargs: recorded.append(tuple(argv))  # type: ignore[method-assign]

    stack.stop()

    removals = [argv for argv in recorded if "rm" in argv]
    assert removals == [("docker", "volume", "rm", mine)]


def test_a_development_run_may_keep_the_payer_fixture_it_paid_for(tmp_path) -> None:
    """The setup page is the one step a saved-instrument lane cannot automate.

    The topology declares exactly one named volume and it is the authority's,
    so keeping it inherits the payer profile, its instrument, and the account
    owner binding — and nothing about the marketplace side of the run.
    """

    argv = _teardown_argv(tmp_path, retain_authority_state=True)

    assert argv[-2:] == ("down", "--remove-orphans")
    assert "--volumes" not in argv


def test_a_protected_run_refuses_an_inherited_payer_fixture() -> None:
    """Protected evidence has to come from an authority that remembers nothing."""

    import argparse

    from src.hosted_real_stripe.driver import AuthorizationRejected, run

    args = argparse.Namespace(retain_authority_state=True, release_mode="attested")
    with pytest.raises(AuthorizationRejected, match="may not inherit authority state"):
        run(args)


def test_the_staged_bridge_does_not_inherit_an_ambient_proxy(tmp_path, monkeypatch) -> None:
    """A loopback-only subprocess has no business reading proxy settings."""

    import json
    import sys

    from src.hosted_real_stripe.runtime import MarketplaceLifecycleSession

    monkeypatch.setenv("ALL_PROXY", "socks5h://127.0.0.1:10808")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:10809")
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_never_forwarded")

    session = MarketplaceLifecycleSession(
        [
            sys.executable,
            "-c",
            (
                "import json,os,sys;"
                "sys.stdin.readline();"
                "print(json.dumps({'ok': True, 'seen': sorted("
                "k for k in os.environ if 'PROXY' in k.upper() or 'STRIPE' in k.upper())}));"
                "sys.stdout.flush()"
            ),
        ],
        cwd=tmp_path,
        request_timeout=10.0,
    )
    session.start()
    try:
        response = session.request("ensure_payer_profile_fixture")
    finally:
        session.stop()

    assert response["seen"] == []
    assert json.dumps(response)


def test_a_protected_run_with_no_producer_pins_still_fails_closed(tmp_path) -> None:
    """They stopped being required arguments; they did not stop being required.

    A locally built producer has none to supply, so the driver no longer demands
    them at the command line. An attested environment supplied with none of them
    is refused by the binding rather than admitted with nothing checked.
    """

    for omitted in (
        "hosted_source_commit",
        "hosted_workflow_run_id",
        "hosted_manifest_sha256",
        "hosted_client_wheel_sha256",
        "hosted_image_digest",
    ):
        with pytest.raises(ReleaseIdentityRejected):
            _attested(tmp_path, **{omitted: ""})
