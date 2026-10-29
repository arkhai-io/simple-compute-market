"""The e2e-tests chart's scenario pod runs a validation's scenarios as the deal test runs.

A Helm validation runs its scenarios inside the release's namespace, as the
e2e-scenarios test pod, with `e2e-tests.scenarios.markers` naming them. The pod
must read the configuration the deal test reads — the shared test-config's `helm`
profile and the e2e-tests Secret — and mount its credential and volumes, so each
test here renders the local release and compares the two pods. Standard library
only.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

UMBRELLA = Path(__file__).resolve().parents[1]
LOCAL = (UMBRELLA / "values.yaml", UMBRELLA / "local-values.yaml")
MARKERS = "contracts or e2e_alkahest_escrow_codecs"
SCENARIOS = "charts/e2e-tests/templates/tests/e2e-scenarios-test.yaml"
DEAL = "charts/e2e-tests/templates/tests/e2e-deal-test.yaml"


def _helm_template(overlay: dict | None = None) -> subprocess.CompletedProcess[str]:
    with tempfile.NamedTemporaryFile("w", suffix=".json") as handle:
        json.dump(overlay or {}, handle)
        handle.flush()
        command = ["helm", "template", "arkhai-node-operator", str(UMBRELLA)]
        for path in (*LOCAL, Path(handle.name)):
            command += ["--values", str(path)]
        return subprocess.run(command, check=False, capture_output=True, text=True)


def _render(overlay: dict | None = None) -> str:
    rendered = _helm_template(overlay)
    assert rendered.returncode == 0, rendered.stderr
    return rendered.stdout


def _source(manifest: str, path: str) -> str | None:
    for document in manifest.split("\n---\n"):
        if any(line.startswith("# Source: ") and line.endswith(path)
               for line in document.splitlines()):
            return document
    return None


def _scenarios_release() -> str:
    return _render({"e2e-tests": {"scenarios": {"markers": MARKERS}}})


def test_no_scenario_pod_renders_unless_scenarios_are_named() -> None:
    assert _source(_render(), SCENARIOS) is None
    assert _source(_render(), DEAL) is not None


def test_the_scenario_pod_runs_the_named_scenarios_as_a_helm_test() -> None:
    pod = _source(_scenarios_release(), SCENARIOS)

    assert pod is not None
    assert "  name: arkhai-node-operator-e2e-tests-e2e-scenarios" in pod.splitlines()
    assert '"helm.sh/hook": test' in pod
    command = pod.split("      command:\n", 1)[1].split("      env:\n", 1)[0]
    assert command.splitlines() == [
        "        - .venv/bin/pytest", "        - -m", f'        - "{MARKERS}"',
        "        - -v", "        - --tb=short"]


def test_the_scenario_pod_reads_and_mounts_what_the_deal_test_does() -> None:
    manifest = _scenarios_release()
    pod, deal = _source(manifest, SCENARIOS), _source(manifest, DEAL)

    assert pod is not None and deal is not None
    # Everything from the environment on: configuration, credentials, volumes.
    assert pod.split("      env:\n", 1)[1] == deal.split("      env:\n", 1)[1]
    image = [line.strip() for line in deal.splitlines() if line.strip().startswith("image:")]
    assert image and image == [line.strip() for line in pod.splitlines()
                               if line.strip().startswith("image:")]


def test_scenarios_that_are_not_a_marker_expression_are_refused() -> None:
    for scenarios in ({"markers": 5}, {"markers": MARKERS, "marker": "typo"}):
        refused = _helm_template({"e2e-tests": {"scenarios": scenarios}})

        # Helm releases word a schema error differently; each names the key.
        assert refused.returncode != 0
        assert "scenarios" in refused.stderr, refused.stderr


def main() -> int:
    failures = 0
    for name, test in sorted(globals().items()):
        if name.startswith("test_") and callable(test):
            try:
                test()
                print(f"ok    {name}")
            except Exception as exc:  # noqa: BLE001 - every error is a failed test
                failures += 1
                print(f"FAIL  {name}: {type(exc).__name__}: {exc}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
