# Domain Docs

Where this repository's vocabulary is defined, and how agents and contributors use it.

## Where terms live

| Terms of | Home |
|---|---|
| the market across subsystems | [`docs/development/ARCHITECTURE.md`, "Shared vocabulary and identities"](../development/ARCHITECTURE.md#shared-vocabulary-and-identities) |
| one subsystem | that capability's `openspec/specs/<capability>/spec.md`, listed in the [capability index](../../openspec/specs/README.md) |
| the change workflow | [`openspec/specs/change-workflow/spec.md`](../../openspec/specs/change-workflow/spec.md), "Terms" |

A subsystem's definition wins inside that subsystem.

## The rule for terms

- Use the established term from its home. Don't drift to a synonym
  `ARCHITECTURE.md`'s "One name per concept" rules out.
- A term new to the reader is defined where it first appears and marked as new.
  One that stays is added to its home in the same change.
- When the owner asks what a mechanism is for or what a word means, answer in
  established terms, then correct the description that prompted the question, or
  propose the term's entry in its home.
