# Domain Docs

How the engineering skills should consume this repo's domain documentation when exploring the codebase.

## Before exploring, read these

- **`CONTEXT-MAP.md`** at the repo root: it points at one `CONTEXT.md` per context. Read each one relevant to the topic.
- **`CONTEXT.md`** at the repo root: the platform context, covering the shared packages in `core/`, `kit/`, and `provisioning/`.
- **`domains/<domain>/CONTEXT.md`**: the subcontext for the market domain being worked in.
- **`docs/adr/`**: system-wide decisions. Also read `domains/<domain>/docs/adr/` for domain-scoped ones.

If any of these files don't exist, proceed silently. Don't flag their absence and don't propose creating them upfront. `/domain-modeling` creates them lazily when terms or decisions get resolved.

## File structure

Multi-context: one holistic platform context spanning the shared packages, plus a subcontext per market domain.

```text
/
├── CONTEXT-MAP.md
├── CONTEXT.md                  ← platform context: core/, kit/, provisioning/
├── docs/adr/                   ← system-wide decisions
├── core/
├── kit/
└── domains/
    ├── apicredits/
    │   ├── CONTEXT.md
    │   └── docs/adr/           ← domain-scoped decisions
    ├── bare_metal/
    │   ├── CONTEXT.md
    │   └── docs/adr/
    └── vms/
        ├── CONTEXT.md
        └── docs/adr/
```

A package is not a context. The 30-odd distributions under `core/`, `kit/`, and `provisioning/` share one vocabulary and one glossary; only the three market domains get their own. Code that serves a single domain belongs to that domain's subcontext wherever it sits on disk.

## ADRs are not OpenSpec specs

`openspec/specs/<subsystem>/spec.md` and its companion `architecture.md` describe the current system: what it does, and why it is shaped that way now. `openspec/README.md` is explicit that neither preserves the chronology of how a decision was reached.

An ADR records a decision: its date, the context as it stood at the time, the alternatives rejected, and its status once a later ADR supersedes it. It stays true about a moment after the system has moved on. Nothing in OpenSpec holds that, so ADRs live in `docs/adr/`.

Two corollaries:

- Don't restate current behavior in an ADR, and don't put dated decision history in `architecture.md`.
- A deliberate absence — something the system intentionally does not do — is an ADR, not a normative requirement in `spec.md`.

## Use the glossary's vocabulary

When output names a domain concept, use the term defined in the relevant `CONTEXT.md`. Where a domain subcontext and the platform context define the same term differently, the subcontext wins inside that domain. Don't drift to synonyms the glossary explicitly avoids.

If a required concept isn't in the glossary, reconsider the term or note the gap for `/domain-modeling`.

## Flag ADR conflicts

If output contradicts an existing ADR, surface it explicitly instead of silently overriding it.
