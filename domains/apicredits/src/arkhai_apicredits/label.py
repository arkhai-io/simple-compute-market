"""The API-credits issuance label, under which its digests, identities, and evidence are spelled."""

from arkhai_api.labels import IssuanceLabel

# Recorded grants carry the singular identity prefix, which no rule derives
# from the label's name.
API_CREDITS_LABEL = IssuanceLabel("api-credits", "api-credit-fulfillment.v1")
