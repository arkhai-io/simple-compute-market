"""The protected run and the development run differ only where they must."""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MAKEFILE = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")

#: The one flag a protected run is right to omit. `--release-mode local` is
#: what makes a run development, and a protected run takes the default.
DEVELOPMENT_ONLY = {"--release-mode"}


def _driver_flags(target: str) -> set[str]:
    """Flags a Makefile target hands the hosted-settlement driver."""

    body = re.search(rf"^{re.escape(target)}:.*?(?=\n\n)", MAKEFILE, re.S | re.M)
    assert body, f"{target} is no longer a Makefile target"
    assert "src.hosted_real_stripe.driver" in body.group(0), (
        f"{target} no longer invokes the driver"
    )
    return set(re.findall(r"^\s+(--[a-z-]+)", body.group(0), re.M))


def test_a_protected_run_is_told_everything_a_development_run_is_told() -> None:
    """Both invocations describe the same run; only the binding differs.

    `hosted-stripe-test` omitted `--storefront-config` and `--buyer-config`,
    so a protected run silently took argparse's default -- the checked-in
    template -- while a development run got the configuration the credential
    assembler had just generated. The template pins a fixed identity and the
    assembler mints a fresh one per run, so the storefront's credential never
    matched the identity the protected run read, and every protected lane died
    at `account_readiness` with `authorization_rejected`.

    A protected run keeps no diagnostics, so all it could report was that
    something about authorization was wrong. Nothing said which file it read.
    """

    protected = _driver_flags("hosted-stripe-test")
    development = _driver_flags("hosted-stripe-test-local")

    missing = development - protected - DEVELOPMENT_ONLY

    assert not missing, (
        "hosted-stripe-test does not pass " + ", ".join(sorted(missing)) + "; a protected "
        "run would fall back to the checked-in default while a development run uses the "
        "value generated for the run"
    )


def test_the_generated_configuration_is_what_both_targets_name() -> None:
    """Neither target may hardcode a path the assembler overrides."""

    for target in ("hosted-stripe-test", "hosted-stripe-test-local"):
        body = re.search(rf"^{re.escape(target)}:.*?(?=\n\n)", MAKEFILE, re.S | re.M)
        assert body
        for flag, variable in (
            ("--storefront-config", "HOSTED_STRIPE_TEST_STOREFRONT_CONFIG"),
            ("--buyer-config", "HOSTED_STRIPE_TEST_BUYER_CONFIG"),
        ):
            assert f'{flag} "$({variable})"' in body.group(0), (
                f"{target} must pass {flag} as $({variable}), which the credential "
                "assembler exports per run"
            )
