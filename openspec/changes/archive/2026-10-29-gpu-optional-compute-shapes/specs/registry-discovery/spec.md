## ADDED Requirements

### Requirement: The compute listing shape does not require GPU fields

The compute filter specification's `listing_resource` MUST require `region` and MUST NOT
require `gpu_model` or `gpu_count`, so a listing whose shape states no GPUs is valid. Its
GPU filters MUST keep failing on a missing value, so a listing stating no GPU is excluded
from every query bounding a GPU field and appears in queries that bound none. Removing a
required field of the listing shape is backwards-incompatible and MUST bump the
specification version; the schema identity and its version are unchanged.

#### Scenario: A listing without GPUs is validated

- **WHEN** a publisher dry-runs a compute listing whose `listing_resource` carries `region`,
  `vcpu_count`, and `ram_gb` and no GPU field
- **THEN** the response reports it valid

#### Scenario: A buyer bounds a GPU field

- **WHEN** a buyer queries with `gpu_count>=1` or `gpu_model=H100`
- **THEN** a listing stating no GPU is not returned

#### Scenario: A buyer bounds only CPU and memory

- **WHEN** a buyer queries with `vcpu_count>=16`
- **THEN** a listing stating no GPU and sixteen or more vCPUs is returned, beside GPU
  listings that state as many vCPUs
