# Issue Discovery Tool

This package powers the repository-level issue-discovery harness. The stable
entrypoint from the repo root is:

```bash
./scripts/issue-discovery --help
```

The tool is YAML-driven. It is intended to run existing validation commands,
collect artifacts, and generate issue-ready summaries without silently fixing
runtime state.
