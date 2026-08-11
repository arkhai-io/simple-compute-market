# Tasks

## Status: discuss phase only — no implementation tasks yet

The defect is reproduced and its mechanism is traced (see `proposal.md`). What is not
settled is where the freshness constraint belongs, and that decides the plan:

1. Does the storefront already record a latest-observed capacity version per site that
   the reopen pass can compare against, or does this change add one?
2. Should a reopen pass that finds itself behind skip, or re-read availability and
   proceed? Skipping is simpler and converges on the next delta; re-reading closes the
   window sooner at the cost of a synchronous fetch inside a subscriber.
3. Does the same reasoning apply to the bare-metal storefront's reconciliation, or is
   that path structured differently enough to need its own answer?
4. Is a freshness gate on the reopen sufficient, or must the subscriber's reconciliation
   and an inline reserve's close be serialized? The second occurrence shows an inline
   close reported and then not observed, which a freshness gate alone would not explain.

Once those are resolved, this file gets a real plan, ending with the closeout task
defined in `openspec/README.md#plan-closeout-requirements`.
