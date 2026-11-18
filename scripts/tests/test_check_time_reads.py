"""The wall-time read check: every refused form under each import form and an
alias, the permitted forms, and the scope it reads."""

from __future__ import annotations

from pathlib import Path

import pytest

import check_time_reads as checker


def _forms(source: str) -> list[tuple[int, str]]:
    return [(finding.line, finding.form) for finding in checker.reads(source)]


@pytest.mark.parametrize(("source", "form"), [
    # import time, and an alias of it
    ("import time\nstamp = time.time()\n", "time.time"),
    ("import time\nstamp = time.time_ns()\n", "time.time_ns"),
    ("import time\nparts = time.gmtime()\n", "time.gmtime()"),
    ("import time\nparts = time.localtime()\n", "time.localtime()"),
    ("import time as clock\nstamp = clock.time()\n", "time.time"),
    # from time import ..., and an alias of it
    ("from time import time\nstamp = time()\n", "time.time"),
    ("from time import time_ns\nstamp = time_ns()\n", "time.time_ns"),
    ("from time import gmtime\nparts = gmtime()\n", "time.gmtime()"),
    ("from time import localtime as here\nparts = here()\n", "time.localtime()"),
    ("from time import time as wall\nstamp = wall()\n", "time.time"),
    # import datetime, and an alias of it
    ("import datetime\nstamp = datetime.datetime.now()\n", "datetime.now"),
    ("import datetime\nstamp = datetime.datetime.utcnow()\n", "datetime.utcnow"),
    ("import datetime\nstamp = datetime.datetime.today()\n", "datetime.today"),
    ("import datetime\nday = datetime.date.today()\n", "date.today"),
    ("import datetime as dt\nstamp = dt.datetime.now(dt.timezone.utc)\n", "datetime.now"),
    # from datetime import ..., and an alias of it
    ("from datetime import datetime, timezone\nstamp = datetime.now(timezone.utc)\n",
     "datetime.now"),
    ("from datetime import datetime\nstamp = datetime.utcnow()\n", "datetime.utcnow"),
    ("from datetime import datetime\nstamp = datetime.today()\n", "datetime.today"),
    ("from datetime import date\nday = date.today()\n", "date.today"),
    ("from datetime import datetime as DateTime\nstamp = DateTime.now()\n", "datetime.now"),
    # with None, gmtime and localtime convert the current instant too
    ("import time\nparts = time.gmtime(None)\n", "time.gmtime()"),
    ("import time\nparts = time.localtime(secs=None)\n", "time.localtime()"),
])
def test_each_refused_form_is_named_with_its_line(source: str, form: str) -> None:
    assert _forms(source) == [(2, form)]


@pytest.mark.parametrize(("call", "form"), [
    ("time()", "time.time"),
    ("time_ns()", "time.time_ns"),
    ("gmtime()", "time.gmtime()"),
    ("localtime()", "time.localtime()"),
])
def test_each_time_read_is_refused_under_an_alias_of_the_module_and_of_the_function(
        call: str, form: str) -> None:
    name = call.removesuffix("()")
    assert _forms(f"import time as clock\nvalue = clock.{call}\n") == [(2, form)]
    assert _forms(f"from time import {name} as read\nvalue = read()\n") == [(2, form)]


@pytest.mark.parametrize(("cls", "method"), [
    ("datetime", "now"), ("datetime", "utcnow"), ("datetime", "today"), ("date", "today"),
])
def test_each_datetime_read_is_refused_under_an_alias_of_the_module_and_of_the_class(
        cls: str, method: str) -> None:
    form = f"{cls}.{method}"
    assert _forms(f"import datetime as dt\nvalue = dt.{cls}.{method}()\n") == [(2, form)]
    assert _forms(f"from datetime import {cls} as C\nvalue = C.{method}()\n") == [(2, form)]


@pytest.mark.parametrize(("source", "form"), [
    ("import time\n\ndef clock(read=time.time):\n    return read()\n", "time.time"),
    ("from datetime import datetime\nfactory = datetime.now\n", "datetime.now"),
    ("from time import time\nclock = time\n", "time.time"),
])
def test_a_read_passed_as_a_value_is_refused(source: str, form: str) -> None:
    assert [found for _, found in _forms(source)] == [form]


def test_an_import_inside_a_function_binds_its_names() -> None:
    source = "def stamp():\n    import time\n    return time.time()\n"

    assert _forms(source) == [(3, "time.time")]


@pytest.mark.parametrize("source", [
    "import time\nstarted = time.monotonic()\n",
    "import time\nstarted = time.perf_counter()\n",
    "from time import monotonic, perf_counter\na, b = monotonic(), perf_counter()\n",
    "import time\ntime.sleep(1)\n",
    "import time\nparts = time.gmtime(1794821400)\n",
    "import time\nparts = time.localtime(seconds)\n",
    "import time\nparts = time.gmtime(secs=1794821400)\n",
    "import time\nconverter = time.gmtime\n",
    "import time\nconverter = time.localtime\n",
    "from datetime import datetime, timezone\n"
    "stamp = datetime.fromtimestamp(1794821400, timezone.utc)\n",
    "from datetime import datetime\nparsed = datetime.fromisoformat(text)\n",
    "import injected_time\nstamp = injected_time.now()\n",
    "def now():\n    return 0\nstamp = now()\n",
    "class Clock:\n    def time(self):\n        return 0\nstamp = Clock().time()\n",
])
def test_the_permitted_forms_are_not_refused(source: str) -> None:
    assert _forms(source) == []


def test_a_clean_module_has_no_finding() -> None:
    source = (
        '"""A module that takes its clock."""\n'
        "from collections.abc import Callable\n\n"
        "import injected_time\n\n\n"
        "def stamped(clock: Callable[[], int] = injected_time.now) -> int:\n"
        "    return clock()\n"
    )

    assert checker.reads(source) == []


def test_every_read_counts_on_one_line_and_on_two() -> None:
    source = ("import time\na = time.time(); b = time.time_ns()\n"
              "c = time.time() - time.time()\n")

    assert _forms(source) == [(2, "time.time"), (2, "time.time_ns"),
                              (3, "time.time"), (3, "time.time")]


def _write(root: Path, path: str, text: str) -> None:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text)


READ = "import time\nstamp = time.time()\n"


def test_the_scope_is_each_projects_source_and_the_lane_doubles(tmp_path: Path) -> None:
    for project in ("core", "core/buyer", "kit/site", "domains/vms/storefront",
                    "provisioning/compute", "tools/payments-lane-double",
                    "tools/mediation-lane-double", "tools/lane-double-controls",
                    "tools/injected-time", "tools/issue-discovery", "e2e-tests"):
        _write(tmp_path, f"{project}/pyproject.toml", "[project]\nname = 'x'\n")
        _write(tmp_path, f"{project}/src/package/module.py", READ)
        _write(tmp_path, f"{project}/tests/test_module.py", READ)
    _write(tmp_path, "kit/site/src/package/.venv/lib/module.py", READ)

    findings, per_project = checker.check(tmp_path)

    assert sorted({finding.path for finding in findings}) == sorted(
        f"{project}/src/package/module.py"
        for project in ("core", "core/buyer", "kit/site", "domains/vms/storefront",
                        "provisioning/compute", "tools/payments-lane-double",
                        "tools/mediation-lane-double", "tools/lane-double-controls"))
    assert per_project["core"] == 1 and per_project["core/buyer"] == 1


def test_the_command_names_each_finding_and_fails(tmp_path: Path,
                                                  capsys: pytest.CaptureFixture[str]) -> None:
    _write(tmp_path, "kit/site/pyproject.toml", "[project]\nname = 'x'\n")
    _write(tmp_path, "kit/site/src/package/module.py", READ)

    assert checker.main(["--root", str(tmp_path)]) == 1

    output = capsys.readouterr().out
    assert "kit/site/src/package/module.py:2: time.time reads the wall clock" in output
    assert "1  kit/site" in output


def test_the_command_passes_a_clean_tree(tmp_path: Path,
                                         capsys: pytest.CaptureFixture[str]) -> None:
    _write(tmp_path, "kit/site/pyproject.toml", "[project]\nname = 'x'\n")
    _write(tmp_path, "kit/site/src/package/module.py", "import time\ntime.monotonic()\n")

    assert checker.main(["--root", str(tmp_path)]) == 0
    assert capsys.readouterr().out.startswith("OK:")
