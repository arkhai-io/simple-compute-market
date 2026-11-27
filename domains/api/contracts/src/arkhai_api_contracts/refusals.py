"""The machine-readable reasons the authority refuses a consumption with."""

KEY_NOT_FOUND = "key_not_found"
KEY_REVOKED = "key_revoked"
INSUFFICIENT_CREDITS = "insufficient_credits"
# Answered only to a caller that names a service or resource the key's first
# grant does not; an unscoped caller never sees it.
KEY_OUT_OF_SCOPE = "key_out_of_scope"
# Answered when a consume's amount differs from the request charge pinned on
# the key's first grant: a refusal of the call, not of the key or its credit.
CHARGE_MISMATCH = "charge_mismatch"

# The refusals of a key or its credit.
CONSUME_REFUSALS = (KEY_NOT_FOUND, KEY_REVOKED, INSUFFICIENT_CREDITS, KEY_OUT_OF_SCOPE)
