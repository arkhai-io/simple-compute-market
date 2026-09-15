"""Static contract checks for the reviewed software-TPM qualification image."""

from pathlib import Path


DOCKERFILE = Path(__file__).with_name("software-tpm-custody.Dockerfile")


def test_image_pins_the_supported_binding_source_and_runtime_closure():
    content = DOCKERFILE.read_text(encoding="utf-8")

    assert content.count("FROM ubuntu@sha256:") == 2
    assert "ARG TPM2_PYTSS_VERSION=2.2.1" in content
    assert (
        "ARG TPM2_PYTSS_SHA256="
        "b8f15473422f377f59c7217dcd1479165cce62dfa33934ec976a278baf2e9efe"
    ) in content
    assert "sha256sum --check --strict" in content
    assert "--no-build-isolation --no-deps" in content
    for package in (
        "libtss2-esys-3.0.2-0",
        "libtss2-fapi1",
        "libtss2-tcti-device0",
        "libtss2-tcti-swtpm0",
        "libtss2-tctildr0",
    ):
        assert package in content
    assert 'version("tpm2-pytss") == "2.2.1"' in content
    assert "ldd \"$binding\"" in content
    assert "! grep -F 'not found'" in content


def test_image_does_not_retain_the_disproved_tools_57_build():
    content = DOCKERFILE.read_text(encoding="utf-8")

    assert "TPM2_TOOLS_VERSION" not in content
    assert "tpm2_load --version" not in content
    assert "tpm2-abrmd" not in content
