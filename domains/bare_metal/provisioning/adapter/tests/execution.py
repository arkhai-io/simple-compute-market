"""Running a bare-metal access job the way the job authority does."""

from __future__ import annotations

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
