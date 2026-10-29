"""Running a bare-metal access job the way the job authority does."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

from arkhai_bare_metal import BARE_METAL_OFFERING_MODE
from compute_provisioning.hosts import ConnectionEnvelope, ExecutionHost
from compute_provisioning.jobs import JobRun
from compute_provisioning_ansible import AnsibleJobExecutor

from bare_metal_provisioning_adapter.codec import BareMetalAnsibleCodec, BareMetalJobParams

#: A registered whole host reached over ssh, with a separate tenant address.
HOST = ExecutionHost(
    host_id="bm-node-1",
    pool_id="default",
    connection=ConnectionEnvelope(
        kind="ssh",
        version=1,
        public={
            "ssh_host": "10.0.0.5",
            "public_host": "203.0.113.5",
            "ssh_port": 2201,
            "ssh_user": "ops",
            "key_path": "/keys/id_ed25519",
        },
    ),
)


def host_with(**public) -> ExecutionHost:
    """``HOST`` with its connection's public fields changed."""
    return dataclasses.replace(
        HOST,
        connection=dataclasses.replace(
            HOST.connection, public={**HOST.connection.public, **public}
        ),
    )


def shipped_output(fact_name: str, fact: dict) -> str:
    """A run's output as the packaged configuration's YAML result format prints
    it: the ``debug: var:`` fact as YAML, then its ``debug: msg:`` JSON copy as a
    literal block. Fixture values only.

    The codec tests read output rendered here, written from the callback's form,
    rather than by the adapter's own mock renderer, so a mistake in that
    renderer cannot hide one in the codec. The mock renderer is covered on its
    own, read back by the codec and through the service's typed clients.
    """
    yaml_lines = [f"        {key}: '{value}'" for key, value in sorted(fact.items())]
    msg_lines = [f"        {line}" for line in json.dumps(fact, indent=4).splitlines()]
    return "\n".join(
        [
            "PLAY [Bare-metal Node Access Operations] *****",
            "",
            "TASK [Output data as parsable JSON] *****",
            "ok: [bm-node-1] => ",
            f"    {fact_name}:",
            *yaml_lines,
            "",
            "TASK [Output JSON string for external parsing] *****",
            "ok: [bm-node-1] => ",
            "    msg: |-",
            *msg_lines,
            "",
            "PLAY RECAP *****",
            "bm-node-1 : ok=9 changed=2 unreachable=0 failed=0",
            "",
        ]
    )


def json_output(fact_name: str, fact: dict) -> str:
    """A run's output under the JSON result format: the quoted ``var:`` fact."""
    return "ok: [bm-node-1] => " + json.dumps({fact_name: fact}, indent=4) + "\n"


def job_run(params: BareMetalJobParams, host: ExecutionHost = HOST) -> JobRun:
    """A run of a submitted job with ``params``, as the job engine builds it."""
    return JobRun(
        job_id="job-1",
        offering_mode=BARE_METAL_OFFERING_MODE,
        action=params.action,
        host=host,
        parameters=params.model_dump(mode="json"),
        report_handle=lambda handle: None,
        report_logs=lambda logs: None,
    )


def executor(runner) -> AnsibleJobExecutor:
    """The bare-metal executor over ``runner``, as the bare-metal runtime builds it."""
    return AnsibleJobExecutor(
        runner,
        BareMetalAnsibleCodec(),
        Path("/playbooks/node-access.yaml"),
        timeout_seconds=5,
    )
