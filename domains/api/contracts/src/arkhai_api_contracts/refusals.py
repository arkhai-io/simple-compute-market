"""The machine-readable reasons the authority refuses a consumption with."""

KEY_NOT_FOUND = "key_not_found"
KEY_REVOKED = "key_revoked"
INSUFFICIENT_CREDITS = "insufficient_credits"
# Answered only to a caller that names a service or resource the key's first
# grant does not; an unscoped caller never sees it.
KEY_OUT_OF_SCOPE = "key_out_of_scope"

CONSUME_REFUSALS = (KEY_NOT_FOUND, KEY_REVOKED, INSUFFICIENT_CREDITS, KEY_OUT_OF_SCOPE)
