---
tags: [repository, diagrams]
---

# The change workflow's diagrams

How the change workflow's diagrams stand to the shared rule on diagrams,
[`diagrams.md`](../../../docs/guidance/engineering/diagrams.md). Its diagrams sit in
[`diagrams/`](diagrams/), each draw.io source beside its SVG export, as
[`openspec/README.md`, "Documentation placement"](../../README.md#documentation-placement)
says of every diagram here.

## Exceptions to shared guidance

| Shared rule | Kind | Here | Reason |
|---|---|---|---|
| [`diagrams.md`, "A diagram is held to code only when generated"](../../../docs/guidance/engineering/diagrams.md#a-diagram-is-held-to-code-only-when-generated) | overrides | The workflow graph's diagram is laid out by hand and held to the graph table, the structured source it draws, by a test and by `make change-graph` ([the companion's "Routing is code, with the model as backstop"](README.md#routing-is-code-with-the-model-as-backstop)) | No deterministic layout from the table reads as well as the hand-laid one; the override ends when one does ([the companion's "Current limits"](README.md#current-limits)) |
