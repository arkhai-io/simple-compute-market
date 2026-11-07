"""The stable reason codes a refusal carries, each with its short text.

A refusal answers frps with `<code>: <text>`, which frps passes to frpc, so a host's
operator diagnoses a refused proxy from frpc's log and admin status without the
relay's log. The codes are part of the published specification and never change
meaning; the texts may be reworded.
"""

from __future__ import annotations

from enum import Enum


class Reason(Enum):
    """Why a proxy was refused."""

    MALFORMED_REQUEST = ("malformed_request", "the request is not a well-formed frps plugin request")
    OPERATION_NOT_SUPPORTED = ("operation_not_supported", "the plugin decides NewProxy only")
    PROXY_TYPE_NOT_ALLOWED = ("proxy_type_not_allowed", "only tcp proxies are admitted")
    GROUP_NOT_ALLOWED = ("group_not_allowed", "a proxy in a load-balancer group is not admitted")
    PORT_INVALID = ("port_invalid", "the remote port must be a port from 1 to 65535")
    GRANT_MISSING = ("grant_missing", "the proxy's own metadata carries no grant (metadatas.grant)")
    GRANT_MALFORMED = ("grant_malformed", "the grant is not a well-formed frp-grant+jwt")
    GRANT_TYPE_UNSUPPORTED = ("grant_type_unsupported", "the grant's typ is not frp-grant+jwt")
    KEY_UNKNOWN = ("key_unknown", "the grant's kid names no key this relay trusts")
    SIGNATURE_INVALID = (
        "signature_invalid",
        "the grant's signature does not verify under the key its kid names",
    )
    CLAIM_MISSING = ("claim_missing", "the grant lacks a required claim (aud, exp, or port)")
    AUDIENCE_MISMATCH = ("audience_mismatch", "the grant's aud is not its issuer's audience")
    GRANT_EXPIRED = ("grant_expired", "the grant's exp has been reached on the relay's clock")
    GRANT_NOT_YET_VALID = (
        "grant_not_yet_valid",
        "the grant's nbf or iat is later than the relay's clock",
    )
    PORT_MISMATCH = ("port_mismatch", "the grant's port is not the proxy's remote port")
    PORT_OUTSIDE_RANGE = ("port_outside_range", "the grant's port lies outside its issuer's range")

    def __init__(self, code: str, text: str) -> None:
        self.code = code
        self.text = text

    @property
    def reply(self) -> str:
        """The `reject_reason` frps passes to frpc."""
        return f"{self.code}: {self.text}"
