## ADDED Requirements

### Requirement: Inference end-to-end deal path

The inference domain MUST have an end-to-end scenario, built on the shared
domain-neutral helpers, that proves one complete deal against running services:
discovery by model on the inference registry, negotiation of a new key,
settlement on the development chain, delivery of a key and a materialization
carrying the listing's rate card, a successful model request, refusal of an
unlisted model without charge, exhaustion, a top-up of the existing key, and a
streamed response. The scenario MUST run against a deterministic model server so
its assertions are exact.

#### Scenario: The lane runs

- **WHEN** the inference end-to-end lane runs, building the inference images
  and every registry its scenarios read
- **THEN** the inference deal scenario runs in it and observes each stage in
  order through the public buyer and seller boundaries

#### Scenario: The buyer's schema filter is exercised

- **WHEN** the scenario discovers inference listings with compute and
  API-credits registries also configured
- **THEN** only the inference registry is queried

#### Scenario: A lane setting is missing

- **WHEN** the lane's configuration lacks a value the inference scenario reads
- **THEN** the scenario fails naming the setting rather than skipping

### Requirement: The inference lane runs every party on lane time

The inference end-to-end lane MUST run its storefront, inference service,
gateway, three registries and both doubles on injected time from configuration
only the lane loads, and its runner profile MUST name each of them, the chain
and the buyer's lane-time file as lane-time parties, so the lane-time fixture
sets and confirms them as it does every Compose lane's. The fixture MUST set
the storefront and the inference service through their signed administrator
routes and the gateway through its time control, with the doubles' typed
control client and the gateway's control token, as `inference`'s "Each
inference party's time is configured and set through its own control" gives
each. The model stub, which signs nothing and reads no time a party checks,
has no time source. The full local stack MUST run each of these parties on
wall time.

#### Scenario: The lane's parties are set together

- **WHEN** the inference lane's session starts
- **THEN** the fixture sets the storefront, the service, the registries, both
  doubles, the gateway, the chain and the buyer's file to one instant and
  every one of them reports it

#### Scenario: A request is charged after an advance

- **WHEN** the gateway's time and the inference service's are set forward
  together and a buyer sends a completion with a funded key
- **THEN** the gate's signed calls are accepted by the service and the request
  is charged

## MODIFIED Requirements

### Requirement: Every party in a lane shares one lane time the scenario sets

Each Compose lane MUST run every party on injected time: every storefront, provisioning service, registry, the API-credits service and the sample app, and the inference service and the inference gateway, where the lane runs them, both doubles, and the buyer, with the harness's own signing clients reading its process source. One harness fixture MUST set every party at the session's start to the wall instant at that moment, or to the latest instant a party already holds when that is later, so the start never sets a party back — a party whose instant the start cannot read holds none, and one that then refuses the instant set fails the setup naming it — and its set MUST move, in order, the harness's own source, each service, both doubles, the sample app and the inference gateway, the chain and the buyer's lane-time file to one instant, then read every party's status and fail naming any that does not report it, a party whose status has no time section among them. Lane time MUST only move forward and MUST never be reset; a stage MAY set any forward instant, and a backward set MUST fail naming the party and both instants. A party the run's profile names but cannot reach MUST fail the setup rather than skip.

#### Scenario: Funds run out without waiting

- **WHEN** a rate deal's funding reaches its boundary at 1794823200 and a stage sets lane time to 1794823200, then steps the storefront's servicing and the lease watchdog
- **THEN** the storefront records the exhaustion stop, the site ends the lease at 1794823200, and teardown follows, with no wait on wall time

#### Scenario: A party misses a set

- **WHEN** a lane-time set leaves one registry at its previous instant
- **THEN** the fixture fails naming that registry and the instant it reports

#### Scenario: An older image ignores the setting

- **WHEN** a lane configures injected time for a service image that predates the setting, which boots on wall time
- **THEN** the session fixture fails naming that service, since its status has no time section

#### Scenario: A module follows an advanced one

- **WHEN** a module ends with lane time at 1794830000
- **THEN** the next module starts at 1794830000 or later, with every party reporting the same instant
