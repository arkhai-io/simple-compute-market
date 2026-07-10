"""Compatibility import for shared site resource/allocation service.

The implementation now lives in ``core_storefront.site_resources`` so other
storefront/provisioning stacks can share the same resource/allocation seam while
this VM provisioning package keeps its existing import path.
"""

from core_storefront.site_resources import SiteResourceLedger, SiteResourcesService

__all__ = ["SiteResourceLedger", "SiteResourcesService"]
