# injected-time

One source of the time of the world per process: wall time, or an injected instant
that a test sets and moves forward. A process reads every instant it stores, signs,
sends to another party, or compares with an instant another party knows from the
one source its composition root installs, and from no other read. Several
processes set to one injected instant then agree on the time exactly, and a test
reaches any later instant by setting it, never by waiting for it.

The component depends on the standard library alone, Python 3.10 or later. This
README is its interface: the value, the sources, the time file, and the route
service a process's HTTP binding wraps.

## The time value

An instant is a JSON integer of Unix seconds from `0` to `253402300799`, the last
second of the year 9999. A document carrying one is exactly `{"now": <instant>}`.
A boolean, a float (even `1794821400.0`), a string, an instant out of range, a
missing `now`, any other member, a member stated twice, or a body that is not JSON
is refused as `invalid_time` (`InvalidTime`). Every reader applies this one rule:
`parse_time(raw)` for a JSON body, `read_time(document)` for a parsed one, and
`check_instant(value)` for a bare value.

## Sources

| Source | `name` | `now()` |
|---|---|---|
| `WallTime(wall=time.time)` | `wall` | the wall clock, in whole seconds |
| `InjectedTime(start=None, wall=time.time)` | `injected` | the instant last set; it starts at `start`, or at the wall instant it was made, and reads the wall clock never again |
| `TimeFile(path)` | `injected` | the instant the file holds, read on every call |

`InjectedTime.set(instant)` moves the source to `instant`. An instant earlier than
the current one is refused as `time_moves_forward` (`TimeMovesForward`, carrying
both instants), an invalid one as `invalid_time`, and neither changes anything;
setting the current instant again succeeds. `wall`, a function reading the wall
clock in seconds, is how a test stands in for the wall clock.

A process installs its source once, at its composition root, from its
configuration's source value, and reads it through the module-level `now()`:

```python
import injected_time

injected_time.install(injected_time.source_for(settings.time_source, setting="time.source"))
...
stamped_at = injected_time.now()
```

`source_for` accepts exactly `"wall"` and `"injected"`; any other value is refused
(`InvalidTimeSource`), naming the setting and the value. Until a root installs a
source, `now()` reads wall time. `now_datetime()` is the same instant as an aware
UTC `datetime`, its microsecond 0. A function that takes a clock keeps it
injectable by defaulting it to `injected_time.now`.

A duration of the process's own activity — a timeout, a poll budget, a backoff, an
interval — is not the time of the world. Measure it on `time.monotonic()`, which
neither stops while injected time is held nor jumps when it is set.

## The time file

A process with no route of its own to set its time — a command-line tool started
afresh for each step, say — reads its injected time from a time file holding the
time document. `TimeFile(path).now()` reads the file on every call, so a running
process sees a later instant at its next read; a missing, unreadable or invalid
file raises `TimeFileError` naming the file, and there is no fallback to wall time.
`TimeFile(path).write(instant)` replaces the file whole: it writes a complete file
in the same directory and renames it over the old one, so a reader sees the
previous document or the new one, never part of either.

## The route service

`TimeRouteService(source)` is framework-free. A service binds it behind its own
administrator authentication, at a path of its own:

- `status()` is the status section: `{"source": "injected", "now": <instant>}`, or
  `{"source": "wall"}`.
- `set_time(body)` reads the raw request body by the value rule, sets the source,
  and answers `{"source": "injected", "now": <instant>}`. It refuses with
  `TimeRouteError` carrying `status_code`, `code` and `detail`: 422
  `invalid_time` for a body the rule refuses, 409 `time_moves_forward` for an
  earlier instant; neither changes anything.
- `settable` is true only for an `InjectedTime` source. A service binds the
  setting route only then, so an instance on wall time offers no way to change its
  time.

## Development

From this directory:

- `make test` type-checks the package and runs its unit tests, the structure test
  holding its boundary among them.
- `make build` builds its wheel into `dist/`, or into `DIST_DIR`.
