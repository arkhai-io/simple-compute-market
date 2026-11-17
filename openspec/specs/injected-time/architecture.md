# Injected Time Architecture

The [normative contract](spec.md) states what every process that reads time owes
and what the time component provides. This document explains why time has one
source per process, why injected time is frozen, forward-only and set only on an
instance configured for it, and where each party binds its controls. How the lanes
use it is [`test-compatibility`'s "Lane time and the doubles' controls"](../test-compatibility/architecture.md#lane-time-and-the-doubles-controls).

## One source per process

A process reads the time of the world — any instant it stores, signs, sends to
another party, or compares with an instant another party knows — from one time
source, which its composition root installs from its configuration before anything
reads the time, and from nothing else
([`implementation.md`, "One time source per process"](../../../docs/guidance/engineering/implementation.md#one-time-source-per-process)).
The source is wall time unless the process is configured for injected time. Where a
class or function already takes a clock — end service, the deal watch, the rate
parts, the compute delivery path — its default is the process source, so a unit
test still passes its own clock and production reads the installed one.

The marketplace's signing makes the time one claim shared by every party: every
signed hop checks the other side's timestamp against the verifier's own instant
within a skew, in both directions. A party whose time moves alone breaks every
signed exchange with a party that did not move once the gap passes the skew; when
every party on a hop is set to the same instant, every hop stays within it. So time
is not a clock for one purpose, such as a lease clock or a test clock beside an
authentication clock: each process moves its whole perception of time, and
evidence it signs is dated consistently with the decisions it makes
([`ARCHITECTURE.md`, "Authenticated service boundaries"](../../../docs/development/ARCHITECTURE.md#authenticated-service-boundaries)).

Every read goes through the source explicitly rather than through a library that
patches Python's time functions process-wide. Such a patch moves every third-party
read too, including those measuring elapsed work: under frozen time a library's
deadline written against `time.time()` never expires. It would also patch the
interpreter at runtime in production and stay invisible at the call site. A
process-wide faked clock through a preloaded C library has the same reach, needs
the library in the release images and a variable outside the configuration
system, and is invisible to every test below the lane.

The buyer, a command-line process started afresh for each step with no API of its
own, reads its injected time from a time file its configuration names, on every
read, so a running command sees a later instant at its next read; the harness
writes the file through the component's writer. The buyer never asks a service for
the time: in production that would make a seller the buyer's clock.

### Elapsed work is measured on the monotonic clock

A duration of the process's own activity — a timeout, a poll budget, a backoff, a
rate-limiter window, a loop interval — is not the time of the world. It is measured
on `time.monotonic()`, which neither stops while injected time is held nor jumps
when it is set: under frozen time a duration measured on the source is always zero,
and a timeout measured on it never expires. Each read is classified once: a value
stored, signed, sent, or compared with an instant another party knows reads the
source; a value only subtracted from another reading in the same process is
elapsed work.

`make check-time-reads`, part of `make check-packaging`, refuses a direct
wall-clock read in production source and in the lane doubles, naming each file and
line ([`packaging-checks.md`](../../../docs/guidance/repository/packaging-checks.md#checks)).
SQL time defaults are outside it; "Database times" below says why.

## The component

The source is generic infrastructure, so it is a standalone component,
`tools/injected-time` (distribution `arkhai-injected-time`, import
`injected_time`), rather than a foundation kit: it depends on the standard library
alone, names no market concept, is published, and holds its boundary in a
structure test of its own, as `tools/frp-grant-admission` does
([`implementation.md`, "Generic infrastructure is a standalone component"](../../../docs/guidance/engineering/implementation.md#generic-infrastructure-is-a-standalone-component)).
Its [README](../../../tools/injected-time/README.md) is its interface. It holds:

- the process source — `WallTime`, `InjectedTime`, and `TimeFile` — its
  installation from a configured source value, and the module-level `now()` and
  `now_datetime()` every reader calls;
- the one rule reading a time value, `parse_time`, `read_time` and
  `check_instant`;
- the forward-only set;
- the time file's reader and writer, so the harness and the buyer share one
  definition of the file;
- `TimeRouteService`, a framework-free route service answering a setting request
  and the status time section, with `settable` telling a binding whether to mount
  the setting route.

Every published package that reads the time of the world, the doubles and the
sample app depend on it
([`published-packages.md`, "Published packages"](../../../docs/guidance/repository/published-packages.md#published-packages)).
Each service's HTTP binding of the route service stays its own:

| Party | Setting | Setting route, under injected time | Status time section | Administrator authentication |
|---|---|---|---|---|
| VM, bare-metal and API-credits storefronts | `[Time] source` | `POST /api/v1/admin/time` | `GET /api/v1/system/status` | signed |
| Compute provisioning service | `time.source` | `POST /api/v1/system/time` | `GET /api/v1/system/status` | signed |
| API-credits service | `time.source` | `POST /api/v1/system/time` | `GET /api/v1/system/status` | signed, `admin` role |
| Registry | `TIME_SOURCE` | `POST /admin/time` | `GET /admin/status` | bearer `REGISTRY_ADMIN_API_KEY` |
| Payments and mediation doubles | their `*_TIME_SOURCE` | `POST /test/time` | `GET /test/status` | control bearer token |
| API-credits sample app | `APICREDITS_SAMPLE_APP_TIME_SOURCE` | `POST /test/time` | `GET /test/status` | control bearer token |
| Buyer | `[time] source`, `[time] file` | none: the harness writes its time file | none | none |

The storefronts bind one kit-owned route service,
`market_storefront_kit.time_controls.StorefrontTimeRouteService`, at the same path,
as they bind the trading pause, so one typed client drives all three. The
services' typed clients — the storefront client, the provisioning client, the
API-credits service's client and the registry client — each offer `set_time` and
read the status time section; the doubles and the sample app are driven through
`lane-double-controls`' client. The metering middleware, which is published, has
no control of its own: it reads the source its host installs.

On the signed administrator surfaces, the time-setting operation alone is exempt
from request freshness, since an advance of more than the skew would otherwise
cross every signed hop: a caller that moves itself first signs at an instant the
service still refuses
([`marketplace-identity`'s spec](../marketplace-identity/spec.md)). Under frozen
time a replay of that operation is either an exact retry, which the request-id
reservation answers, or names an instant already reached, which the forward-only
set refuses; and the route exists only under injected time.
The registry's control is behind its bearer administrator key, which carries no
timestamp and needs no exemption.

## Frozen injected time

An injected source returns exactly the instant last set until it is set again: time
moves only when a test moves it. Every party agrees exactly, because an advance
sets each one to the same instant rather than adding a delta to clocks read at
slightly different moments, and nothing elapses unseen: an approval window, a
delivery deadline or an Agreement's start arrives only when time is set to it. A
source running from the set instant at real rate would let parties drift by however
far apart their settings landed, and an offset says nothing about which instant a
party is at.

The instant is Unix seconds, a JSON integer from `0` to `253402300799`, the last
second of the year 9999 and the largest instant a UTC `datetime` holds, in the
setting request and answer, the status section and the time file. Integer seconds
match the signing protocol's integer timestamps, which would truncate a finer
instant on every signed hop, and make comparing two parties' instants exact. One
parser in the component reads the value wherever it is parsed, so a boolean, a
float, a string or any other member is refused everywhere alike.

A process configured for injected time starts frozen at the wall instant it
started. Starting from the wall time, rather than a fixed epoch, keeps time-pinned
material valid — a payments receipt key's pin, checked at the snapshot's instant,
and a certificate, checked on real time.

Injected time moves only forward, and a set to an earlier instant is refused with
nothing changed. Moving a process backwards would date its journals out of order
and reopen replay windows once replay state is pruned against the clock.

## Configured, announced, never refused

Each party's time source is one setting, wall time by default, in its own
configuration format; any value but `"wall"` or `"injected"` refuses startup,
naming the setting and the value. The production image carries the control,
because no party can recognise production: there is no environment setting to read,
and inventing a deployment-wide one would add a concept nothing else uses and one
more value an operator can set wrong. A refusal coupled to payments `livemode`
would protect only the parties with payments configured while suggesting all were
protected. So production configuration simply never sets `"injected"`
([`configuration.md`, "A test control the production image carries is off by default"](../../../docs/guidance/engineering/configuration.md#a-test-control-the-production-image-carries-is-off-by-default)):
a process with injected time logs it at startup and reports it with its current
instant on its status, a party with an Arkhai payments section whose `livemode` is
`true` also logs a warning, and a static check refuses `"injected"` in every
committed configuration outside the lanes' own
([`deployment-state`'s spec](../deployment-state/spec.md)).

## No live change

The time source is configuration. The setting route exists only on an instance
configured for injected time, so a wall-time instance has none, and switching
source means reconfiguring and restarting. A service's time is a claim it signs and
exchanges: freezing or advancing a live service would date its records and evidence
falsely, break every signed hop with counterparties on real time, and stop none of
the external authorities' deadlines. Diagnosis and recovery use the pause controls
and the explicit operator actions — ending a deal, terminating or force-releasing a
lease, stepping a loop — and an incident is reproduced on a copy: the database
restored into a local or lane stack configured for injected time
([operator handbook, "Injected time"](../../../docs/operator-handbook.md#injected-time)).

## Database times

A database time that production logic reads — a column a query orders, filters or
expires by, or a decision compares — is supplied by the application from the
process source: an ORM default is a Python `default=` or `onupdate=` callable
reading the source, and raw SQL passes the time as a parameter. A database's own
clock knows nothing of injected time, so a hold or a lease stamped by
`CURRENT_TIMESTAMP` would expire on the database's wall clock. An audit-only
`created_at` or `updated_at` nothing reads keeps its SQL default: determinism needs
only the times something decides by, and supplying every one would mean rebuilding
tables in seven migration chains, and an upgrade for every operator, for columns no
test or decision reads. Which columns are read is judged per column, not by a
check; each store's integration test asserts, under injected time, the times its
read columns hold. The stores of the site ledger, the resource pools, fulfillment
and the storefront kits are held to this by this capability rather than by their
own.

## Related contracts

- [Test compatibility](../test-compatibility/spec.md): lane time across every party
- [Marketplace identity](../marketplace-identity/spec.md): signing at the process source and the time-setting operation's freshness exemption
- [Market composition](../market-composition/spec.md), [physical provisioning](../physical-provisioning/spec.md), [registry discovery](../registry-discovery/spec.md), [API credits](../api-credits/spec.md), [buyer orchestration](../buyer-orchestration/spec.md): each party's setting, route and status
- [Site capacity](../site-capacity/spec.md): the site's decisions at its process's source
- [Deployment and state](../deployment-state/spec.md): no committed configuration outside the lanes injects time
