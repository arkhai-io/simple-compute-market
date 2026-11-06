"""Run named `unittest` modules' tests concurrently, one interpreter per test.

    native_gate_runner.py <tests dir> <module pattern>...

Each test runs in its own child interpreter, so no test's working directory,
environment, or umask reaches another, and each test's output is captured and
printed whole, under a header naming the test, once the test ends. At most
`os.cpu_count()` tests run at once. The run fails on any failure or error, on any
skip, on a child that ends without reporting its result, on a module that cannot
be imported, and on a pattern that names no test: a native gate that skips has not
proven what it runs.

Standard library only, so the runtime image it runs in gains no test dependency.
"""

import concurrent.futures
import json
import os
import subprocess
import sys
import time
import unittest


def _test_ids(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from _test_ids(item)
        else:
            yield item.id()


def _child(test_id):
    """Run one test, verbosely, and end the output with its result as JSON."""
    # The parent starts the child in the tests directory; the test modules import
    # one another by name, as discovery made possible in the parent.
    sys.path.insert(0, os.getcwd())
    suite = unittest.defaultTestLoader.loadTestsFromName(test_id)
    result = unittest.TextTestRunner(stream=sys.stdout, verbosity=2).run(suite)
    report = {
        "id": test_id,
        "ran": result.testsRun,
        "skipped": [[test.id(), reason] for test, reason in result.skipped],
        "failures": len(result.failures) + len(result.unexpectedSuccesses),
        "errors": len(result.errors),
    }
    print(json.dumps(report), flush=True)
    # A skip is the parent's to judge, from the report; a skip in a class or
    # module fixture runs no test but is still a skip.
    return 0 if result.wasSuccessful() and (result.testsRun or result.skipped) else 1


def _report(output, test_id):
    """The child's JSON line, or None when it ended without one.

    Searched from the end rather than taken as the last line: an interpreter's
    shutdown may still write a warning after it."""
    for line in reversed(output.splitlines()):
        try:
            report = json.loads(line)
        except ValueError:
            continue
        if isinstance(report, dict) and report.get("id") == test_id:
            return report
    return None


def _run(test_id, tests_dir):
    started = time.monotonic()
    # Unbuffered, so the child's stderr and stdout reach the one pipe in the order
    # they were written.
    child = subprocess.run(
        [sys.executable, "-u", os.path.abspath(__file__), "--child", test_id],
        cwd=tests_dir,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        errors="replace",
        check=False,
    )
    return test_id, child.returncode, child.stdout, time.monotonic() - started


def main(arguments):
    if len(arguments) == 2 and arguments[0] == "--child":
        return _child(arguments[1])
    if len(arguments) < 2:
        print(__doc__, file=sys.stderr)
        return 2
    started = time.monotonic()
    tests_dir, patterns = os.path.abspath(arguments[0]), arguments[1:]

    loader = unittest.defaultTestLoader
    ids = []
    found_nothing = []
    for pattern in patterns:
        found = list(_test_ids(loader.discover(tests_dir, pattern=pattern, top_level_dir=tests_dir)))
        if not found:
            found_nothing.append(pattern)
        ids.extend(found)
    for error in loader.errors:
        print(f"native gate: cannot load a test module:\n{error}", file=sys.stderr)
    for pattern in found_nothing:
        print(f"native gate: no test found for {pattern}", file=sys.stderr)
    if loader.errors or found_nothing:
        return 1

    failed, skipped, reasons = [], [], []
    with concurrent.futures.ThreadPoolExecutor(max_workers=os.cpu_count() or 1) as pool:
        running = [pool.submit(_run, test_id, tests_dir) for test_id in ids]
        for done in concurrent.futures.as_completed(running):
            test_id, status, output, seconds = done.result()
            report = _report(output, test_id)
            if report is None:
                verdict = f"failed, exit status {status} with no result reported"
            elif status or report["failures"] or report["errors"]:
                verdict = f"failed, exit status {status}"
            elif report["skipped"]:
                verdict = "skipped"
            else:
                verdict = "passed"
            if verdict == "skipped":
                skipped.append(test_id)
            elif verdict != "passed":
                failed.append(f"{test_id} {verdict}")
            if report is not None:
                reasons.extend(report["skipped"])
            # Only this loop prints, so each test's block stays whole.
            print(f"=== {test_id}: {verdict} in {seconds:.1f}s ===")
            print(output, end="" if output.endswith("\n") or not output else "\n", flush=True)

    print(f"native gate: {len(ids)} run, {len(failed)} failed, {len(skipped)} skipped"
          f" in {time.monotonic() - started:.1f}s", flush=True)
    for test_id, reason in reasons:
        print(f"native gate: {test_id} skipped: {reason}", file=sys.stderr)
    for description in failed:
        print(f"native gate: {description}", file=sys.stderr)
    return 1 if failed or reasons else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
