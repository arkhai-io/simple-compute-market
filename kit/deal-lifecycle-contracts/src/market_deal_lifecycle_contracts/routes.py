"""Signed lifecycle route declarations shared by clients and HTTP bindings."""

_ID = r"(?P<negotiation_id>[^/]+)"
_BASE = r"/api/v1/negotiations/" + _ID + "/lifecycle"
_ADMIN = r"/api/v1/admin/lifecycle"

LIFECYCLE_ROUTES = (
    {"method": "GET", "path": _ADMIN, "operation": "lifecycle_list", "roles": ("admin",)},
    {"method": "POST", "path": _ADMIN + "/" + _ID, "operation": "lifecycle_submit",
     "roles": ("admin",), "path_resource": "negotiation_id"},
    {"method": "GET", "path": _ADMIN + "/" + _ID, "operation": "lifecycle_seller_read",
     "roles": ("admin",), "path_resource": "negotiation_id"},
    {"method": "POST", "path": _BASE, "operation": "lifecycle_peer",
     "roles": ("buyer",), "path_resource": "negotiation_id"},
    {"method": "GET", "path": _BASE, "operation": "lifecycle_buyer_read",
     "roles": ("buyer",), "path_resource": "negotiation_id"},
)


def lifecycle_route(operation: str) -> dict:
    for declaration in LIFECYCLE_ROUTES:
        if declaration["operation"] == operation:
            return declaration
    raise KeyError(operation)
