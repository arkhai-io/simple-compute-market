//! API-tokens gating middleware (Rust).
//!
//! A seller-side component that gates a downstream HTTP app on prepaid
//! API credits: it extracts the bearer key, verifies it against the
//! tokens service (short-TTL cache), meters each request by consuming
//! credits (synchronously near exhaustion, optionally batched above a
//! low-balance threshold), and maps a drained key to a 402 whose body
//! points at the listing to buy more (the re-purchase loop). All
//! verification and accounting authority stays in the service.
//!
//! The behavioral contract — status codes and machine-readable bodies —
//! is shared with the Python and TypeScript middlewares and pinned by
//! the conformance fixtures under
//! `domains/apitokens/middleware/conformance`.

pub mod client;
pub mod config;
pub mod gate;
pub mod tower_layer;

pub use client::{
    ConsumeItem, ConsumeResult, TokensApi, TokensClient, VerifyResult, INSUFFICIENT_CREDITS,
    KEY_NOT_FOUND, KEY_REVOKED,
};
pub use config::{GateConfig, PurchasePointer};
pub use gate::{
    key_id_from_secret, parse_bearer, GateDecision, TokenGate, INVALID_API_KEY, MISSING_API_KEY,
};
pub use tower_layer::{TokenGateLayer, TokenGateService};
