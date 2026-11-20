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
sets and confirms them as it does every Compose lane's. The inference gateway
MUST install its process time source from `INFERENCE_GATEWAY_TIME_SOURCE`,
`"wall"` by default or `"injected"`, and its gate MUST read that source for
every timestamp it signs and every response it verifies. Under injected time
the gateway MUST serve `POST /test/time` with `{"now": <Unix seconds>}` and a
status reporting its source and now, behind a control bearer token from its
environment, with the doubles' answers and refusals, ahead of its gate and
whether or not its listing has loaded; on wall time it MUST serve neither. The
model stub, which signs nothing and reads no time a party checks, has no time
source. The full local stack MUST run each of these parties on wall time.

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

#### Scenario: A wall-time gateway serves no control

- **WHEN** a gateway configured for wall time receives `POST /test/time`
- **THEN** it serves no such route and its time is unchanged
