---
tags: [engineering, testing]
---

# Cross-language conformance

Where one protocol has independent implementations in more than one language, each
implementation reproduces one shared, data-driven conformance trace, rather than
each maintaining its own hand-written assertions of the same behaviour. Keeping the
trace in data, not in each language's test code, is what makes "identical behaviour
across languages" a checkable claim rather than an assumption.
