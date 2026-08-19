## ADDED Requirements

### Requirement: Delivery sinks compose without importing implementations

Core and kit packages MUST assemble a configured delivery sink set through the
installed-plugin contract alone and MUST NOT import, name, or branch on any
concrete sink implementation. Enabling delivery MUST NOT make a mechanism kit a
dependency of a core role package, and a sink MUST NOT be reachable only by
importing a composition root. A sink that fails to load, fails to deliver, or
blocks MUST NOT degrade registry discovery, negotiation, settlement, servicing, or
command assembly.

#### Scenario: Core delivers without depending on a mechanism kit

- **WHEN** the core buyer role package delivers a revealed introduction
- **THEN** it resolves sinks through the plugin contract and imports no
  mechanism-specific package to do so

#### Scenario: A sink degrades

- **WHEN** an installed sink raises on load or blocks while delivering
- **THEN** market orchestration on that side proceeds unchanged and the sink is
  reported as a local delivery fault
