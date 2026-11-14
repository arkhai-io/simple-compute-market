---
tags: [engineering, diagrams]
---

# Diagrams

What holds a diagram to what it draws, and where its source and export live.

## A diagram is held to code only when generated

A diagram is held to code only when it is generated deterministically from a
well-structured source. Otherwise it is documentation, maintained by review like the
prose around it: no check holds its boxes to the modules or files it draws, since
nothing derives one from the other.

## Source beside export

Keep a diagram's editable source beside its export, and embed the export in the
document that explains it.
