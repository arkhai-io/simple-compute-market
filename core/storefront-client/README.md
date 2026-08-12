# storefront-client

Async and synchronous HTTP clients for the Arkhai storefront REST API.
The immutable public package is `arkhai-core-storefront-client==0.17.0`.

## Identity configuration

Authenticated calls use the marketplace identity v2 contract from
`arkhai-kit-identity==0.2.0`. Inject a scheme-neutral `market_identity.Signer`,
the one caller role used by that client, and the exact storefront publisher
principal trusted to sign responses.

```python
from market_identity import Ed25519Signer, Identity, TrustedIdentitySet
from storefront_client import StorefrontClient

signer = Ed25519Signer(service_seed)
publisher = Identity(scheme="ed25519", identifier=configured_publisher_key)

client = StorefrontClient(
    "http://seller-storefront:8001",
    signer=signer,
    caller_role="service",
    expected_publishers=TrustedIdentitySet(identities=(publisher,)),
)
```

`Ed25519Signer` and `Eip191Signer` use the same client interface. The client
takes the identity scheme and identifier only from `signer.identity`; callers
cannot provide separate identity tags. A configured signer always requires an
explicit `caller_role` and `expected_publishers` pin.

For a `seller` client, the signer principal must belong to the pinned publisher
set; the constructor rejects a mismatch. The set supports one active principal
or two explicitly pinned principals during a credential-rotation overlap.

Create separate clients for different roles. Authenticated methods reject a
client whose configured role does not match the route contract:

- `seller`: listing create, close, refund, and claim.
- `buyer`: negotiation and settlement calls.
- `admin`: operator writes and reads, including events, negotiation inspection,
  inventory, and settlement evaluation.
- `service`: system status and fulfillment lifecycle callbacks.

`get_health`, `list_listings`, and `get_listing` remain public reads and can be
called by a client without identity configuration.

## Async seller example

```python
from market_identity import Ed25519Signer, Identity, TrustedIdentitySet
from storefront_client import StorefrontClient

signer = Ed25519Signer(seller_seed)
publisher = Identity(scheme="ed25519", identifier=configured_publisher_key)

async with StorefrontClient(
    "http://seller-storefront:8001",
    signer=signer,
    caller_role="seller",
    expected_publishers=TrustedIdentitySet(identities=(publisher,)),
) as client:
    created = await client.create_listing(
        offer={...},
        accepted_escrows=[...],
        request_id="publish-20260811-1",
    )
    closed = await client.close_listing(
        created.listing_id,
        request_id="close-20260811-1",
    )
```

## Sync service example

```python
from market_identity import Eip191Signer, Identity, TrustedIdentitySet
from storefront_client import SyncStorefrontClient

signer = Eip191Signer(service_secret)
publisher = Identity(scheme="ed25519", identifier=configured_publisher_key)

with SyncStorefrontClient(
    "http://seller-storefront:8001",
    signer=signer,
    caller_role="service",
    expected_publishers=TrustedIdentitySet(identities=(publisher,)),
) as client:
    status = client.get_system_status(request_id="status-20260811-1")
    client.notify_capacity_released(
        "reservation-1",
        site_id="site-1",
        resource_id="gpu-1",
        request_id="release-20260811-1",
    )
```

## Identity rotation

Admin-role clients expose `admin_initiate_identity_rotation`,
`admin_complete_identity_rotation`, and `admin_get_identity_status`. Initiation
builds the kit-owned `RotationRequest` and binds both current and replacement
possession proofs into the signed request body. Completion accepts that same
`RotationRequest`, retiring its current principal by rotation nonce. For
`storefront.administrator`, initiation must use a client signed by the current
principal and completion a client signed by the replacement principal.
`storefront.service-peer` rotations remain outer-authenticated by an active
administrator. Authority and subject are percent-encoded into the canonical
mutation resource, while status binds the sorted effective query.


## Authentication guarantees

For every authenticated request, the client binds the signer principal, caller
role, HTTP method, operation, semantic resource, request ID, timestamp, and
canonical body hash into an `arkhai.market-request-signature.v2` proof. JSON is
canonicalized once and those same bytes are sent by both the async and sync
clients. Empty request bodies use the protocol's `EMPTY_BODY` value. Multipart
CSV imports sign a canonical descriptor containing the filename, media type,
size, and SHA-256 digest.

Supplying `request_id` enables safe retry. Every attempt gets a fresh timestamp
and proof, including retries from the same client instance, while changed role,
method, operation, resource, or body is rejected locally. A new process likewise
re-signs the same semantic request ID. The storefront replay contract returns
the cached outcome after comparing the principal, role, method, operation,
resource, and canonical body hash.

Every authenticated response must carry an
`arkhai.market-response-signature.v2` proof from `expected_publishers`, with the
seller response role and the exact request method, operation, resource, and
request ID. Missing, legacy, unknown-version, stale, body-mutated, or
principal-mismatched responses fail closed.

## Versioning policy

The client version tracks the released storefront API and identity contract.
When an operation, resource, body, response, or authentication binding changes:

1. Update the sync and async methods and response models together.
2. Update focused behavioral tests for byte parity and verification failures.
3. Publish a new immutable package version; never replace an existing release.
