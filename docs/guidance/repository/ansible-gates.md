---
tags: [repository, testing, ansible]
---

# Ansible gates

How this repository's Ansible trees are checked, and what each gate proves, as
instances of [`ansible-checks.md`](../engineering/ansible-checks.md).

## Syntax and native checks

The roles reach most of their task files through `include_tasks`, so each such
role has a parse-only playbook, as
[`ansible-checks.md`](../engineering/ansible-checks.md) describes:
`vm-management-task-files.yaml` and `vm-setup-task-files.yaml` in the VM IaC tree.

`domains/vms/provisioning/iac/scripts/validate_playbooks.sh` syntax-checks every playbook the VM IaC tree
ships from one list, which a structure test holds equal to the playbooks
present; `make validate-playbooks` runs it. Tests that run shipped tasks through
real `ansible-playbook` are library integration: the VM suite renders both create
facts, exercises its family-role call boundary, runs the host diagnostics
task file against faked `systemctl` and `virsh`, runs host preparation's
guest-isolation preconditions against faked `virsh`, `virt-install` and
`ebtables` and its check of the guests' private destinations, and renders the
guest interface's template through Ansible's lookup, and the family suite runs its
installer and authenticated status wait against controlled local file and HTTP
boundaries. Native tests skip in the default suite without supported Ansible;
the family HTTP tests also require the `ansible.posix.json` callback.

`make test-provisioning-iac-native` runs the native suites and syntax checks from
the built provisioning image's packaged IaC trees, with no network but loopback.
A missing image, supported Ansible or required callback, no native test, or a
skipped native test fails the gate. Both domains' playbooks are parsed with their
own configuration and with the shared service configuration and image role path.
The shared configuration contains no domain path. A structure test holds the VM
gate's list of native modules to every module defining its skip guard, and the VM
gate runs its few native tests in series. The compute family's gate
(`provisioning/compute/iac/scripts/native_gate_runner.py`) runs each native test
in its own interpreter, as many at once as the host has CPUs, so no test's
working directory, environment, or umask reaches another; it prints each test's
output whole under the test's id as the test ends, then a summary of what ran,
failed, and skipped.

The end-to-end pipeline runs this gate as its own job, `native-ansible-gate`,
beside the domain lanes: it builds only the wheels and the provisioning image
(`make build-e2e-native-gate`), composes no stack, and leaves its output in the
job log.

## The bounded working-data helper

The bounded bare-metal working-data helper has its own evidence boundaries.
`make -C domains test-bare-metal-iac` exercises its unit and library-integration behavior;
`make build-provisioning` followed by `make test-bare-metal-iac-native`
executes native account, filesystem and IPC behavior in a disposable isolated
environment and fails on missing prerequisites or skips. Neither gate proves
that an image contains the intended assets, that the role is active in a
deployment, or that a real lease is reclaimed. A deployed qualification must additionally observe an actual lease through
cleanup and successor access; the real-provisioning marker by itself does not
qualify bounded cleanup. A valid older copy of the host ledger is
not locally distinguishable from current state; operational rollback response
is quarantine pending history verification or host decommission, not a passing
rollback test. A rejected cleanup retains capacity; normal same-job retry is
distinct from terminal failed-job recovery or force-release.
