# Design

The consumer validates the authority's published Description through the vendored
language-neutral schema. The authority owns its policy; lifecycle terms enforce
that advertised minimum and, for compute, require the dispute window to cover the
delivery deadline plus that minimum. A shorter advertisement does not remove either
check. Accepted deals retain their pinned authority and terms.

Refresh schema and vectors together from one authoritative publication, update
content digests and run the model generator. Do not hand-edit generated artifacts
or carry producer source identity into this public repository. Existing default
advertisements and signed vectors retain their meaning. Only refreshed consumers
are expected to accept the new shorter non-live advertisement.

Alternatives: locally masking validation would misrepresent the contract; hardcoding
another duration would repeat the policy coupling. Neither is accepted.

Deployment and policy qualification remain separate from source/schema acceptance.
