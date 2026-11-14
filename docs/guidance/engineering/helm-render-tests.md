---
tags: [engineering, testing, helm]
---

# Helm chart render tests

A chart render test runs `helm template` against a chart with chosen values and
asserts on the manifests it produces, or on its refusal to produce them. It is a
static configuration test: it needs Helm, not a cluster.

**What they cover:** what a deployment's manifests contain for a given set of values
— which documents render into a ConfigMap, which files mount, which settings the
chart derives — and which values the chart's schema refuses. This is where a derived
setting is checked against what it is derived from, so a document that renders and
mounts while its path is unset is caught before any pod runs.

**What they do not cover:** whether a cluster accepts the manifests, whether the
service starts with them, or whether it then behaves. Deploying to a cluster, and
the smoke and system tests, remain the evidence for those; a passing render is not
deployment evidence.

**How to write one:**

- Run every chart's render tests from one entry point, so that one target runs every
  render check; a test reachable only through its chart's own target is easily never
  run.
- Where the runner has no YAML parser, pass values as a JSON file (JSON is YAML) and
  assert on the rendered text. A document the chart renders as JSON can be read back
  and asserted on structurally.
- Assert related artifacts together. When the chart derives a setting from a value,
  assert the rendered artifact, its mount, and the derived setting in one helper,
  all present and all absent, so a test cannot pass with one of the three missing.
- For a schema refusal, assert a non-zero exit and that the error names the
  offending key; a render that fails for an unrelated reason must not count.
- Break the template once while writing the test — remove the mount, say — and
  confirm the test fails, then restore it.
- When the rendered artifact is a document a service parses, parse one rendered
  instance with the service's own parser as well. The render test proves the chart
  emits what it was given; only the parser proves the service accepts it.

## A values schema generated from typed models

Where a service's configuration is defined by typed models, its chart's values schema
is generated from those models rather than written by hand, and a drift test in the
service's own suite fails when a model changes without the schema being regenerated.
The render tests then assert what the schema refuses and accepts.
