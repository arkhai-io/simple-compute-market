FROM ubuntu@sha256:281c5745f657873d78e5531fc5ba8575f46ab7769b94550ac99543f122679986 AS pytss-builder

ARG TPM2_PYTSS_VERSION=2.2.1
ARG TPM2_PYTSS_SHA256=b8f15473422f377f59c7217dcd1479165cce62dfa33934ec976a278baf2e9efe

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        curl \
        libtss2-dev \
        pkg-config \
        python3-asn1crypto \
        python3-cffi \
        python3-cryptography \
        python3-dev \
        python3-packaging \
        python3-pip \
        python3-pkgconfig \
        python3-setuptools \
        python3-setuptools-scm \
        python3-venv \
        python3-wheel \
        python3-yaml \
    && rm -rf /var/lib/apt/lists/*

RUN curl --fail --location --silent --show-error \
        --output /tmp/tpm2-pytss.tar.gz \
        "https://files.pythonhosted.org/packages/source/t/tpm2-pytss/tpm2-pytss-${TPM2_PYTSS_VERSION}.tar.gz" \
    && echo "${TPM2_PYTSS_SHA256}  /tmp/tpm2-pytss.tar.gz" | sha256sum --check --strict \
    && python3 -m venv --system-site-packages /opt/custody-venv \
    && /opt/custody-venv/bin/pip install --no-build-isolation --no-deps \
        /tmp/tpm2-pytss.tar.gz

FROM ubuntu@sha256:281c5745f657873d78e5531fc5ba8575f46ab7769b94550ac99543f122679986

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        cryptsetup-bin \
        libtss2-esys-3.0.2-0 \
        libtss2-fapi1 \
        libtss2-mu0 \
        libtss2-rc0 \
        libtss2-sys1 \
        libtss2-tcti-device0 \
        libtss2-tcti-swtpm0 \
        libtss2-tctildr0 \
        python3 \
        python3-asn1crypto \
        python3-cffi \
        python3-cryptography \
        python3-packaging \
        python3-yaml \
        swtpm \
        tpm2-tools \
    && rm -rf /var/lib/apt/lists/*

COPY --from=pytss-builder /opt/custody-venv /opt/custody-venv

RUN /opt/custody-venv/bin/python -c \
        'from importlib.metadata import version; import tpm2_pytss; assert version("tpm2-pytss") == "2.2.1"' \
    && binding="$(find /opt/custody-venv -type f -name '_libtpm2_pytss*.so' -print -quit)" \
    && test -n "$binding" \
    && ldd "$binding" > /tmp/pytss.ldd \
    && ! grep -F 'not found' /tmp/pytss.ldd \
    && rm /tmp/pytss.ldd

WORKDIR /workspace/domains/vms/provisioning/iac

ENV ARKHAI_RUN_SOFTWARE_TPM_CUSTODY=1
ENV PATH="/opt/custody-venv/bin:${PATH}"

CMD ["python", "tests/test_bare_metal_storage_software_tpm.py"]
