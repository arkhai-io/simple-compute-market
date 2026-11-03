# Design: layer engineering guidance

Status: design phase. Not planned. The direction under "Starting direction" came
from the owner's discussion that opened the lesser goal, and design confirms or
revises it. The inventory itself is the design session's main work and has not
started. Everything under "Open questions" is undecided.

## Context

- **The documents and their size.**

  | Document | Lines | Headings |
  |---|---|---|
  | `AGENTS.md` | 224 | 24 |
  | `docs/development/ARCHITECTURE.md` | 1,121 | 51 |
  | `docs/development/TESTING.md` | 1,215 | 24 |
  | `docs/development/DEPLOYMENT_AND_CONFIG.md` | 1,703 | 27 |
  | `docs/development/BUILD_AND_PACKAGING.md` | 188 | 8 |
  | `docs/development/VALIDATION_RUNBOOK.md` | 1,112 | 33 |
  | `docs/development/RELEASING.md` | 242 | 9 |
  | `openspec/README.md` | 138 | 12 |
  | `docs/agents/` (four files) | 707 | 21 |
  | `docs/prompts/` (five files) | 172 | 12 |

- **Examples of mixing.**
  - `TESTING.md` opens with "Four-Level Hierarchy" and "Coverage Contract Between
    Levels", which would hold anywhere, then turns to "Pool Offering-Mode
    Enforcement", "Payment Receipts in Tests", and "Chart Render Tests".
  - `AGENTS.md` holds the working model, documentation ownership, Python comment
    rules, package discipline, tests, public repository discipline, and agent
    skills in one file.
  - `openspec/README.md` holds both the planning rules and the closeout parts.
- **Checks that enforce guidance.**
  - `scripts/check_comment_hygiene.py` enforces the comment rules on `.py`,
    `.toml`, `.yml`, and `.yaml` files.
  - `scripts/check_doc_citations.py` enforces "Cross-references must resolve".
  - The architecture checks enforce the package layers in `ARCHITECTURE.md` and
    `docs/development/ARCHITECTURE.toml`.

## Starting direction

- **Three layers.**
  - **Engineering:** code, testing, documentation, configuration, and language
    conventions that would hold in any repository.
  - **Workflow:** how a change moves.
  - **Repository:** this repository's architecture and examples.
- **Reclassifications the owner has already made.**
  - **The working model belongs to the workflow layer.** Discuss, plan, and
    implement is not an engineering concern.
  - **Several closeout parts are engineering concerns, not repository ones:**
    comment hygiene, import placement, documentation compliance, and
    documentation citations.
  - **Workflow concerns:** promotion, archival, and campaign index currency.
  - **Repository concerns:** packaging and end-to-end pipeline evidence.

  Design confirms the split of the remaining parts.
- **Guidance is tagged for loading.** A repository will select packs statically;
  a step will declare topics it always loads; an agent will add sections by task.
  The vocabulary is controlled, and a tag a repository or a skill names must
  exist. Assigning tags here avoids retagging when the loader comes.
- **Organize first.** Where the shared layers eventually live, and the citation
  scheme for guidance outside the repository, come later.
- **The working method.** A proposed inventory, one row per section with its
  layer, tags, and reason, which the owner goes through correcting and moving
  rows, rather than starting from blank pages.

## Open questions

- **The inventory itself.** Every section's layer and tags. This is the bulk of
  the design and is done with the owner.
- **The tag vocabulary.** Its granularity, whether by topic (testing,
  documentation, configuration, comments), by language or framework (python,
  helm, typescript), or both. How a tag is attached to a section: frontmatter, a
  marker beside the heading, or the section's place in a file named for its tag.
- **Where the layers live in this repository for now.** For example,
  `docs/guidance/engineering/` and `docs/guidance/repository/`, with workflow
  guidance beside the workflow's specification. Or keep the current document
  names and split each into layered parts. The choice bears on how cheaply the
  engineering layer can later be lifted out whole.
- **"Public repository discipline".** Part of it is engineering guidance for any
  repository: no credentials, obviously-fake fixtures. Part of it holds because
  this repository is public: no private names, no pairing with private work.
  Where each part goes depends on whether the engineering layer assumes a public
  or a private repository.
- **Python-specific rules.** The comment and import rules name Python. Whether the
  engineering layer has language-neutral principles plus a Python pack, or keeps
  Python rules as engineering guidance tagged `python`, is open.
- **Large runbooks.** `VALIDATION_RUNBOOK.md` and `DEPLOYMENT_AND_CONFIG.md` are
  mostly repository material with some general method inside. Whether to extract
  the method or leave those documents whole in the repository layer is decided
  per section.
- **The precedence rule's form.** Whether a repository's deviations live in one
  section of `AGENTS.md`, beside each affected rule, or in the workflow's
  configuration.
- **The closeout parts' new home.** With engineering parts moving to the
  engineering layer and repository parts to addenda, whether `openspec/README.md`
  keeps the list as an index of where each part lives, or whether the list itself
  is dissolved.
