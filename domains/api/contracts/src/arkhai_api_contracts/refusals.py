"""The machine-readable reasons the authority refuses a consumption with."""

KEY_NOT_FOUND = "key_not_found"
KEY_REVOKED = "key_revoked"
INSUFFICIENT_CREDITS = "insufficient_credits"

CONSUME_REFUSALS = (KEY_NOT_FOUND, KEY_REVOKED, INSUFFICIENT_CREDITS)
