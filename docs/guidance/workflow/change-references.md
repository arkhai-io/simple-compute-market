---
tags: [workflow, comments]
---

# Change references

Comments and docstrings describe the current system, never the change that
produced them. Do not reference:

- an OpenSpec change's id, or name its directory — a change that has landed or one
  that has not, since a reader of the code can see neither, and the name goes stale
  as soon as the change is archived;
- a task number;
- `tasks.md`.

If the only reason a comment can give is that a change is coming, it describes a
plan rather than the system.

Avoid:

```python
# Moved here during POOLS-7 task 1.8.
```

Naming the change that owns an open gap is the roadmap's job, not the code's.
