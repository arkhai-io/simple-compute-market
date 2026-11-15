---
tags: [engineering, helm]
---

# Helm

How a chart delivers a service's configuration: deriving what it mounts, toggling a
profile, and the ways Helm's merge and encoding change a value on its way through.
The Kubernetes rules a chart renders are [Kubernetes](kubernetes.md); testing a
chart's output is [Helm chart render tests](helm-render-tests.md).

## A chart derives a mounted file's path from the mount

Where a chart mounts a file a setting names, such as a CA bundle, and renders that
setting, it derives the path from the mount rather than taking it as a value beside
the mount, so the two cannot disagree
([Configuration, "A private CA is mounted once, and each client names it"](configuration.md#a-private-ca-is-mounted-once-and-each-client-names-it)).

## A chart value toggles a mock profile

A boolean chart value, such as `exampleMode`, can conditionally append a profile name
to the active profiles in the Deployment template, causing the service's own
composition root to select a mock implementation of an external dependency instead of
the real one. The corresponding profile file supplies safe no-op values for that
mode. Helm test pods layer in test-only configuration the same way: the shared
non-secret values merge through one profile, and a pod needing secret material mounts
an additional Secret-backed profile on top.

## A hex value stays a string

A YAML loader reads an unquoted `0x`-prefixed value as an integer, and Helm's YAML
encoder leaves a long hex value, such as a 160-bit address, unquoted. So a profile
holding hex values either quotes every one or is written in JSON syntax, which YAML
reads with every string kept a string.

## Key a value that overlays change per entry; do not list it

Helm merges maps key by key and replaces lists whole. A chart value that overlays
change per entry is therefore a map from each entry's name to the entry, not a list,
so an overlay states only what it changes in one entry: an `orders` chart's
`workers` value maps each worker's name to its settings, and an overlay changing one
worker's replica count states that worker alone.

## An integer above 2^53 is a string

Every number in a values file passes through a float on its way into Helm, so an
integer above 2^53 is written as a string.
