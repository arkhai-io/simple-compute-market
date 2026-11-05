# Accept the authority's advertised mediation window

## Why

The vendored mediation Description schema fixes its minimum dispute window to one
hosted policy value. An authority advertising an explicitly supported shorter
non-live policy cannot be validated through this consumer publication. Lifecycle
validation already checks accepted terms against the authority's advertised minimum;
the publication should preserve that authority boundary.

## Scope

Refresh the generated schema publication after its minimum-window field accepts a
nonnegative safe integer. Preserve transport models, default descriptions, signatures,
existing vectors and authority pinning. Add consumer coverage for short and default
advertisements and malformed minima. This implements no mock authority, hosting,
clock override, automatic policy selection or LIVE configuration change.

## Permanent documentation impact

Promote the advertisement-policy boundary to `openspec/specs/deal-lifecycle/spec.md`
and its architecture companion. Update `kit/arkhai-mediation/schema/SOURCE.md` only
if the publication procedure needs clarification. No repository-wide architecture
change is needed: the existing dependency and authority boundaries are retained.
