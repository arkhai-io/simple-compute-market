"""Patch pufferlib's eval loop with three fixes:

1. Guard driver.render() so --render-mode None actually skips it.
2. Replace `while True:` with a bounded episode loop (default 5 episodes,
   override with --max-runs N).
3. Unpack the full step tuple and print per-step reward/action output.

Re-run after every `uv sync`:
    uv run python scripts/patch_puffer_eval.py
or:
    make patch-puffer-eval
"""
import pathlib
import sys

PATCHES = [
    (
        "render guard",
        "        render = driver.render()",
        (
            "        render = ("
            "driver.render()"
            " if getattr(driver, 'render_mode', 'auto') not in ('None', None)"
            " else None"
            ")"
        ),
    ),
    (
        "bounded episode loop",
        "    frames = []\n    while True:",
        "    frames = []\n    _ep, _step, _max_ep = 0, 0, args.get('max_runs', 5)\n    while _ep < _max_ep:",
    ),
    (
        "step unpack + logging + episode reset",
        "        ob = vecenv.step(action)[0]",
        "\n".join([
            "        ob, _rew, _done, _trunc, _ = vecenv.step(action)",
            "        _step += 1",
            "        print(",
            "            f'[eval] ep {_ep+1}/{_max_ep}  step {_step:4d}"
            "  rew {float(_rew[0]):+.4f}  act {action[0].tolist()}',"
            "            flush=True,",
            "        )",
            "        if bool(_done[0]) or bool(_trunc[0]):",
            "            _ep += 1",
            "            if _ep < _max_ep:",
            "                ob, _ = vecenv.reset()",
            "                for _v in state.values():",
            "                    _v.zero_()",
            "            _step = 0",
        ]),
    ),
]

venv = pathlib.Path(".venv")
matches = list(venv.rglob("pufferlib/pufferl.py"))
if not matches:
    print("ERROR: pufferlib not found in .venv — run `uv sync` first", file=sys.stderr)
    sys.exit(1)

target = matches[0]
text = target.read_text()
changed = False

for desc, old, new in PATCHES:
    if old not in text:
        print(f"  skip  [{desc}] — already applied or pattern not found")
        continue
    text = text.replace(old, new)
    print(f"  patch [{desc}]")
    changed = True

if changed:
    target.write_text(text)
    print(f"Written to {target}")
else:
    print("Nothing to do — all patches already applied.")
