"""Behavioral coverage for vm-create.yml's GPU-attachment-discovery shell task.

`test_vm_management_contracts.py` proves specific text exists, in order, in
this task's YAML source. It does not -- and by design cannot, being a pure
substring check -- prove the embedded shell logic behaves correctly. This
file runs the real shell content instead, using `shell_harness` to fake the
handful of external commands (`virsh`, `lspci`) it calls.

Regression coverage for a corrupted `continue` statement that shipped as
`continueThen remove all task that contains installation of GPU driver that
is not` -- a syntactically valid (if nonsensical) command invoking a
nonexistent binary, not a parse error. `bash -n` alone would not have
caught it; these tests would.
"""

from pathlib import Path
import unittest

from shell_harness import (
    assert_bash_syntax_valid,
    extract_between,
    fake_binaries,
    run_bash,
)


ROOT = Path(__file__).resolve().parents[1]
VM_CREATE = ROOT / "ansible/roles/vm-management/tasks/vm-create.yml"

# Anchors for the whole "Get all GPUs currently attached to VMs" shell
# block's `cmd:` content, and for just the while-loop that iterates one
# VM's already-discovered GPU_DEVICES list -- the specific fragment the
# corrupted `continue` statement lived in.
_TASK_CMD_START = "- name: Get all GPUs currently attached to VMs\n  shell:\n    cmd: |\n"
_TASK_CMD_END = "\n    executable: /bin/bash\n"
_LOOP_START = 'if [ -n "$GPU_DEVICES" ]; then\n'
_LOOP_END = "\n        fi\n"


def _task_cmd_text() -> str:
    text = VM_CREATE.read_text(encoding="utf-8")
    return extract_between(text, _TASK_CMD_START, _TASK_CMD_END)


def _attachment_loop_fragment() -> str:
    body = extract_between(_task_cmd_text(), _LOOP_START, _LOOP_END)
    return f"{_LOOP_START}{body}\nfi\n"


class GpuAttachmentDiscoveryShellTests(unittest.TestCase):
    def test_full_task_shell_is_syntactically_valid_bash(self) -> None:
        # A baseline sanity check, not the regression test for the actual
        # bug: the corrupted line was syntactically valid bash (an unknown
        # command with a long argument list), so this alone would not have
        # caught it. See test_empty_pci_addr_entries_are_skipped_not_leaked
        # below for the behavioral coverage that would have.
        assert_bash_syntax_valid(_task_cmd_text())

    def test_empty_pci_addr_entries_are_skipped_not_leaked(self) -> None:
        """The regression test for the corrupted `continue` statement.

        Feeds the real while-loop fragment a `GPU_DEVICES` value containing
        a blank line between two real-looking PCI addresses -- the shape
        `[ -z "$pci_addr" ] && continue` exists to handle -- and asserts
        the blank entry is skipped rather than corrupting
        `ATTACHED_GPUS_LIST` or aborting the loop.

        Before the fix, the corrupted line ran `continueThen` as a command
        (command-not-found, non-fatal since this shell has no `set -e`),
        so execution fell through to compute `normalized_pci` from an
        empty `pci_addr`, appending a bogus entry.
        """
        fragment = _attachment_loop_fragment()
        script = (
            'vm="test-vm"\n'
            'GPU_DEVICES="0000:01:00:0\\n\\n0000:02:00:0"\n'
            'GPU_DEVICES=$(printf "%b" "$GPU_DEVICES")\n'
            'ATTACHED_GPUS_LIST=""\n'
            f"{fragment}\n"
            'echo "RESULT:$ATTACHED_GPUS_LIST"\n'
        )
        with fake_binaries({
            "lspci": (
                "#!/bin/sh\n"
                'echo "VGA compatible controller: Fake GPU"\n'
            ),
        }) as fake_bin_dir:
            result = run_bash(script, fake_bin_dir=fake_bin_dir)

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        result_line = next(
            line for line in result.stdout.splitlines() if line.startswith("RESULT:")
        )
        attached = result_line.removeprefix("RESULT:").split()
        self.assertEqual(
            attached,
            ["0000:01:00.0", "0000:02:00.0"],
            msg=(
                "blank pci_addr entry between the two real ones should be "
                "skipped, not turned into a bogus attachment entry"
            ),
        )

    def test_corrupted_continue_statement_would_have_failed_this_test(self) -> None:
        """Proves the regression test above actually exercises the bug.

        Re-runs the same scenario against the literal corrupted text (not
        the file on disk -- this repository's copy is already fixed) to
        confirm the test method above is not vacuously passing regardless
        of the loop's content.
        """
        corrupted_fragment = _attachment_loop_fragment().replace(
            '[ -z "$pci_addr" ] && continue',
            '[ -z "$pci_addr" ] && continueThen remove all task that '
            "contains installation of GPU driver that is not",
        )
        self.assertIn("continueThen", corrupted_fragment)
        script = (
            'vm="test-vm"\n'
            'GPU_DEVICES="0000:01:00:0\\n\\n0000:02:00:0"\n'
            'GPU_DEVICES=$(printf "%b" "$GPU_DEVICES")\n'
            'ATTACHED_GPUS_LIST=""\n'
            f"{corrupted_fragment}\n"
            'echo "RESULT:$ATTACHED_GPUS_LIST"\n'
        )
        with fake_binaries({
            "lspci": "#!/bin/sh\necho \"VGA compatible controller: Fake GPU\"\n",
        }) as fake_bin_dir:
            result = run_bash(script, fake_bin_dir=fake_bin_dir)

        result_line = next(
            line for line in result.stdout.splitlines() if line.startswith("RESULT:")
        )
        attached = result_line.removeprefix("RESULT:").split()
        self.assertNotEqual(
            attached,
            ["0000:01:00.0", "0000:02:00.0"],
            msg=(
                "the corrupted continue statement should leak a bogus "
                "entry from the blank pci_addr -- if this assertion fails, "
                "the regression test above is not actually exercising the bug"
            ),
        )


if __name__ == "__main__":
    unittest.main()
