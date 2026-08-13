"""VM storefront executable package.

This package initializer deliberately does nothing. It previously inserted the
monorepo checkout root into ``sys.path`` so that ``domains.vms.*`` modules would
resolve when the storefront ran outside Docker. Listing, settlement, and
storefront-side negotiation code now lives inside this package, and the shared
negotiation policies come from the installed ``arkhai-vms`` distribution, so
nothing here resolves from a repository subtree.

Restoring that path insertion would let an undeclared dependency or an omitted
wheel module work in a checkout and fail once installed, which is the class of
defect this layout exists to prevent.
"""

from __future__ import annotations
