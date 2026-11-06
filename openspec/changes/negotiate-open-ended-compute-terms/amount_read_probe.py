"""Replay amount-reader classification without installing market packages."""
from __future__ import annotations

import importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location(
    "amount_guard", ROOT / "scripts/check_agreement_amount_reads.py",
)
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)

negative = (
    "def spend(agreement):\n    return agreement.amount\n",
    "def spend(agreement):\n    alias = agreement\n    return alias['amount']\n",
    "def read(wrapper):\n    return wrapper.value.get('amount')\n",
    "def read(x):\n    key = 'amount'\n    alias = key\n    return getattr(x, alias)\n",
    "def read(x):\n    key = 'amount'\n    return x[key]\n",
    "def read(x):\n    return x.__getitem__('amount')\n",
    "def read(x):\n    lookup = x.get\n    return lookup('amount')\n",
    "def read(x):\n    lookup = getattr\n    return lookup(x, 'amount')\n",
    "from operator import attrgetter as pick\ndef read(x):\n    return pick('amount')(x)\n",
)
positive = (
    "amount: int\n",
    "def serialize(x):\n    return x.model_dump()\n",
    "def write(x):\n    x.amount = 1\n    x['amount'] = 1\n",
)
for source in negative:
    assert guard.amount_reads(source), source
for source in positive:
    assert not guard.amount_reads(source), source

with TemporaryDirectory() as directory:
    root = Path(directory)
    (root / "core").mkdir()
    (root / "scripts").mkdir()
    manifest = root / "scripts/agreement_amount_reads.json"
    manifest.write_text("[]")
    path = root / "core/consumer.py"
    path.write_text(negative[1])
    assert "unclassified amount read" in "\n".join(guard.problems(root))
    manifest.write_text(
        '[{"path":"core/consumer.py","scope":"spend",'
        '"expression":"alias[\'amount\']","count":1,'
        '"reason":"Invocation-local diagnostic classification."}]'
    )
    assert not guard.problems(root)
    path.write_text(negative[1].replace("return alias['amount']", "return alias['amount'] + alias['amount']"))
    assert "2 occurrences" in "\n".join(guard.problems(root))
    path.write_text(positive[0])
    assert "stale" in "\n".join(guard.problems(root))
print("attribute, mapping, aliases, wrappers, reflection, occurrence drift and stale entries: PASS")
assert not guard.problems(ROOT)
print("production source inventory, including new source files: PASS")
