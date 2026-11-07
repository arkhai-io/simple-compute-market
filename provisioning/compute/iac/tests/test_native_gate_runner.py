"""The native gate's runner against planted `unittest` modules, in real child interpreters.

Each case writes small test modules into a temporary directory and runs the real
runner over them as the gate does, so discovery, the per-test child processes, and
the report the gate prints are all exercised.
"""

import os
from pathlib import Path
import re
import subprocess
import sys
import textwrap

import pytest

RUNNER = Path(__file__).resolve().parents[1] / "scripts/native_gate_runner.py"
HEADER = re.compile(r"^=== (\S+): (.+) in [0-9.]+s ===$")


def plant(directory, name, source):
    (directory / name).write_text(textwrap.dedent(source))


def run(directory, *patterns):
    return subprocess.run([sys.executable, str(RUNNER), str(directory), *patterns],
                          capture_output=True, text=True, check=False, timeout=180)


def blocks(stdout):
    """Each test's verdict and the lines printed under its header."""
    found, current = {}, None
    for line in stdout.splitlines():
        header = HEADER.match(line)
        if header:
            current = header.group(1)
            found[current] = (header.group(2), [])
        elif line.startswith("native gate: "):
            current = None
        elif current:
            found[current][1].append(line)
    return {test: (verdict, "\n".join(lines)) for test, (verdict, lines) in found.items()}


PASSING = """
    import unittest

    class TestPasses(unittest.TestCase):
        def test_one(self):
            print("output of one")

        def test_two(self):
            self.assertTrue(True)
"""


def test_every_test_passing_exits_zero_and_is_counted(tmp_path):
    plant(tmp_path, "test_first.py", PASSING)
    plant(tmp_path, "test_second.py", """
        import unittest

        class TestAlsoPasses(unittest.TestCase):
            def test_three(self):
                pass
    """)
    result = run(tmp_path, "test_first.py", "test_second.py")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "native gate: 3 run, 0 failed, 0 skipped" in result.stdout
    found = blocks(result.stdout)
    assert set(found) == {"test_first.TestPasses.test_one", "test_first.TestPasses.test_two",
                          "test_second.TestAlsoPasses.test_three"}
    assert {verdict for verdict, _ in found.values()} == {"passed"}
    assert "output of one" in found["test_first.TestPasses.test_one"][1]


def test_a_failing_test_fails_the_run_and_its_traceback_stays_in_its_own_block(tmp_path):
    plant(tmp_path, "test_mixed.py", """
        import unittest

        class TestMixed(unittest.TestCase):
            def test_good(self):
                pass

            def test_bad(self):
                self.fail("planted failure")
    """)
    result = run(tmp_path, "test_mixed.py")
    assert result.returncode != 0
    assert "native gate: 2 run, 1 failed, 0 skipped" in result.stdout
    found = blocks(result.stdout)
    verdict, bad = found["test_mixed.TestMixed.test_bad"]
    assert verdict.startswith("failed")
    assert "Traceback" in bad and "planted failure" in bad
    verdict, good = found["test_mixed.TestMixed.test_good"]
    assert verdict == "passed"
    assert "planted failure" not in good
    assert "test_mixed.TestMixed.test_bad failed" in result.stderr


def test_a_skipped_test_fails_the_run_naming_the_test_and_its_reason(tmp_path):
    plant(tmp_path, "test_skips.py", """
        import unittest

        class TestSkips(unittest.TestCase):
            def test_needs_a_fixture(self):
                self.skipTest("no planted fixture")
    """)
    result = run(tmp_path, "test_skips.py")
    assert result.returncode != 0
    assert "native gate: 1 run, 0 failed, 1 skipped" in result.stdout
    assert "native gate: test_skips.TestSkips.test_needs_a_fixture skipped: no planted fixture" in result.stderr


def test_a_skip_in_a_class_fixture_is_counted_as_a_skip(tmp_path):
    plant(tmp_path, "test_class_skips.py", """
        import unittest

        class TestClassSkips(unittest.TestCase):
            @classmethod
            def setUpClass(cls):
                raise unittest.SkipTest("no planted class fixture")

            def test_never_runs(self):
                pass
    """)
    result = run(tmp_path, "test_class_skips.py")
    assert result.returncode != 0
    assert "native gate: 1 run, 0 failed, 1 skipped" in result.stdout
    assert "skipped: no planted class fixture" in result.stderr


def test_output_after_the_result_line_does_not_hide_the_result(tmp_path):
    plant(tmp_path, "test_late_output.py", """
        import atexit
        import unittest

        atexit.register(print, "written at interpreter exit")

        class TestLateOutput(unittest.TestCase):
            def test_passes(self):
                pass
    """)
    result = run(tmp_path, "test_late_output.py")
    assert result.returncode == 0, result.stdout + result.stderr
    verdict, block = blocks(result.stdout)["test_late_output.TestLateOutput.test_passes"]
    assert verdict == "passed"
    assert block.endswith("written at interpreter exit")


def test_a_pattern_naming_no_test_fails_the_run_naming_it(tmp_path):
    plant(tmp_path, "test_first.py", PASSING)
    result = run(tmp_path, "test_first.py", "test_absent.py")
    assert result.returncode != 0
    assert "native gate: no test found for test_absent.py" in result.stderr
    assert blocks(result.stdout) == {}


def test_a_module_that_cannot_be_imported_fails_the_run_naming_it(tmp_path):
    plant(tmp_path, "test_broken.py", """
        import a_module_no_test_environment_has
    """)
    result = run(tmp_path, "test_broken.py")
    assert result.returncode != 0
    assert "native gate: cannot load a test module" in result.stderr
    assert "test_broken" in result.stderr
    assert "a_module_no_test_environment_has" in result.stderr
    assert blocks(result.stdout) == {}


def test_a_child_ending_before_its_result_is_reported_failed_with_its_status(tmp_path):
    plant(tmp_path, "test_killed.py", """
        import os
        import unittest

        class TestKilled(unittest.TestCase):
            def test_exits(self):
                os._exit(3)
    """)
    result = run(tmp_path, "test_killed.py")
    assert result.returncode != 0
    assert "native gate: 1 run, 1 failed, 0 skipped" in result.stdout
    verdict, _ = blocks(result.stdout)["test_killed.TestKilled.test_exits"]
    assert verdict == "failed, exit status 3 with no result reported"
    assert "test_killed.TestKilled.test_exits failed, exit status 3" in result.stderr


@pytest.mark.skipif((os.cpu_count() or 1) < 2, reason="needs two CPUs to run two tests at once")
def test_tests_run_concurrently(tmp_path):
    markers = tmp_path / "markers"
    markers.mkdir()
    # Each test marks that it has started, then waits, bounded, for the other's mark:
    # the pair passes only when both run at once.
    plant(tmp_path, "test_meeting.py", f"""
        from pathlib import Path
        import time
        import unittest

        MARKERS = Path({str(markers)!r})

        def meet(mine, theirs):
            (MARKERS / mine).touch()
            deadline = time.monotonic() + 60
            while not (MARKERS / theirs).exists():
                if time.monotonic() > deadline:
                    raise AssertionError(theirs + " never started while " + mine + " ran")
                time.sleep(0.01)

        class TestMeeting(unittest.TestCase):
            def test_a(self):
                meet("a", "b")

            def test_b(self):
                meet("b", "a")
    """)
    result = run(tmp_path, "test_meeting.py")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "native gate: 2 run, 0 failed, 0 skipped" in result.stdout
