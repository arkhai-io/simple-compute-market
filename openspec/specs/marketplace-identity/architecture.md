# Marketplace Identity Architecture

The [normative contract](spec.md) defines principals, proof verification, replay behavior, rotation, and credential separation. This document explains why marketplace identity is a foundation capability rather than a wallet, role, domain, or settlement feature.

## Identity capability layering

Marketplace identity lives below role and domain composition:

```text
composition root
    └── resolves public identity + secret credential
            ↓ constructs and injects Signer
registry / buyer / storefront / service clients
            ↓ scheme-neutral authenticated envelopes
identity verifier registry + replay boundary
```

The identity kit owns principal normalization, signer and verifier protocols, Ed25519 and EIP-191 implementations, canonical authenticated request and response models, replay primitives, and rotation intents. It does not depend on HTTP frameworks, role composition, domains, settlement mechanisms, hosted providers, or chain runtimes. Composition roots select credentials and inject signers; core roles and adapters see only a public principal and a signing operation.

This direction keeps cryptographic dispatch reusable and prevents a generic credential model with a `private_key` field from leaking scheme-specific material into orchestration, serialization, diagnostics, or persistence.

## Scheme-tagged principals and stable subjects

A principal is a cryptographic credential identity, represented and compared as the complete `{scheme, identifier}` pair. The scheme is part of the authorization namespace: equal identifier text under different schemes does not imply equal ownership. Ed25519 identifiers encode the exact public key, while EIP-191 identifiers are normalized EVM addresses; generic callers do not interpret either form.

Publishers, storefronts, listings, negotiations, settlement plans, accounts, and service peers remain stable subjects. An authority resolves an active complete principal to a subject and an explicit role rather than treating a bare address, provider identifier, hosted account reference, or resource identifier as a credential. This separation permits credential rotation without changing commercial or operation identity.

Using one principal across several marketplace roles is a configuration choice, not an authorization shortcut. Authorities still grant roles explicitly, and deployments may use separate principals to reduce credential blast radius without changing the subject model.

## Canonical version 2 proofs

`arkhai.market-request-signature.v2` signs one domain-separated, length-delimited canonical byte sequence containing the protocol version, caller role, complete principal, HTTP method, semantic operation, resource identity, request ID, timestamp, and SHA-256 hash of canonical JSON or the empty body. Ed25519 signs those bytes directly and EIP-191 personal-signs the same bytes; verifier-registry dispatch changes the cryptographic operation, not semantic coverage.

Behavior-affecting query values belong in the signed semantic body. The route supplies the expected operation and resource independently of proxy path spelling. This prevents mutable body fields, role changes, resource substitution, or path rewriting from escaping proof coverage.

The authority reserves `(principal, request_id)` before dispatch. An exact retry can recover the recorded outcome, while reuse with changed canonical input fails before a handler or external effect runs. Configured clock skew limits first use; an old signature cannot be made fresh by changing its timestamp because the timestamp is signed.

Authenticated service responses use the same versioned canonical primitives under a distinct response domain, binding the status, canonical response body hash, originating request identity, authority principal, and timestamp. Callers verify the response against the expected service principal and request before trusting its contents. Request and response models share principal and verifier infrastructure without collapsing their domains or allowing an unsigned acknowledgement path.

## Rotation across authorities

Rotation binds one canonical intent to the current principal, replacement principal, stable subject, authority, nonce, requested overlap, and expiry. Both principals sign the same bytes. Each authority applies the intent idempotently and records primary, bounded active overlap, disabled, and retired history.

There is no cross-service database transaction. A coordinator applies the intent to every required authority, verifies convergence, promotes the replacement, and retires the old principal last. Bounded overlap makes partial progress recoverable: an unavailable authority does not strand the subject, and replaying the same intent does not create a second ownership transition. Administrative disablement can stop a compromised credential, but neither an administrator nor an address-shaped fallback can manufacture replacement ownership without both proofs.

## Wallet and secret boundaries

Marketplace credentials and chain wallets are orthogonal configuration. Ed25519 is the wallet-free default for marketplace proofs. EIP-191 is an explicit supported identity scheme, and an EVM adapter may separately require a wallet, RPC endpoint, chain ID, or contract address when the selected effect needs them. Generic discovery, negotiation, hosted settlement, status, reclaim, and recovery never infer those values from a marketplace principal. An explicitly configured EIP-191 role may reuse underlying key material for a chain wallet, but identity never requires implicit derivation or cross-role reuse.

Ordinary configuration carries only public principals and trust pins. Private credential material enters through an approved secret boundary and is consumed only while constructing a signer. Public carriers and durable state may record the canonical principal, request and operation identity, signature version, and audit history; they never record the signer secret.

## Local buyer profile boundary

The XDG profile repository is public local metadata, not an identity authority or secret store. Its stable UUID groups canonical principal history, exact credential references, lifecycle, selection, and authority-scoped opaque payer bindings. Provider backends alone read or write signing material. Keyring, strict file, and environment references are explicit alternatives with no precedence chain.

Core buyer orchestration resolves a `ResolvedBuyerIdentity` once. Fresh work uses the selected profile's primary principal; recovery uses the profile UUID and canonical principal already reserved in run-log version 3. Rotation therefore changes the signer for new work without mutating accepted operation ownership. Retention blockers are computed across recoverable runs and hosted bindings before retirement or deletion.

Profile-store and run-log migration is one recoverable commit protocol: all candidates are staged and validated, originals are retained behind a durable manifest, and a pre-activation failure restores every replacement. An unresolved manifest blocks runtime rather than admitting mixed legacy/profile identity.

## Protocol ownership

Marketplace and hosted-service protocols may support the same cryptographic schemes, but they have distinct domain separation, canonical bytes, release ownership, and response contracts. The marketplace hosted adapter passes the injected signer through the exact released hosted client interface. It does not copy hosted headers, canonicalization, response verification, account-link behavior, principal models, or provider concepts into this repository.

## Related contracts

- [Market composition](../market-composition/spec.md)
- [Registry discovery](../registry-discovery/spec.md)
- [Negotiation protocol](../negotiation-protocol/spec.md)
- [Storefront publication](../storefront-publication/spec.md)
- [Settlement servicing](../settlement-servicing/spec.md)
- [Deployment and state](../deployment-state/spec.md)
