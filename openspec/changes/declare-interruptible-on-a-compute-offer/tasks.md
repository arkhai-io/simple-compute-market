# Tasks

## Status: discuss phase — no implementation tasks yet

The defect and the shape of the fix are recorded in `proposal.md`. Three questions decide
the plan:

1. Does the offer projection that flattens a listing for publication need to carry the
   field explicitly, or does it pass through with the rest of the resource? The published
   payload observed in run 31499398440 lists every offer field by name, which suggests an
   explicit projection that would silently omit a new one.
2. Should `_deal_is_interruptible` require the field and treat the splitter check as an
   additional allowance, or accept either? The current code accepts either, and that is
   how an ERC20 deal sold as non-interruptible could still be interrupted if its escrow
   happened to be splitter-gated.
3. Does the bare-metal storefront have an equivalent guard? If it does, the same question
   arises there and the answer should be the same one.
