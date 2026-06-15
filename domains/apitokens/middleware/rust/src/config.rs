//! Gate configuration.
//!
//! A middleware is a seller-side component: it holds the operator's
//! `admin_key` and talks to the tokens service the same way the
//! storefront does. The `purchase` pointer is the only buyer-facing
//! data — it rides the 402/403 body so a client whose credits ran out
//! knows where to buy more (the re-purchase loop).
//!
//! Mirrors the Python reference (`apitokens_middleware.config`); the
//! behavioral contract is pinned by `../conformance/session.json`.

use std::env;

use serde_json::{Map, Value};

/// Where a client buys more credits, embedded in exhaustion bodies. All
/// fields optional — a seller fills what it wants to expose.
#[derive(Clone, Debug, Default)]
pub struct PurchasePointer {
    pub service_name: Option<String>,
    pub listing_id: Option<String>,
    pub storefront_url: Option<String>,
    pub registry_url: Option<String>,
}

impl PurchasePointer {
    /// Serialize to the on-the-wire body (snake_case, dropping empty
    /// fields), matching the Python `as_body()`.
    pub fn as_body(&self) -> Map<String, Value> {
        let mut out = Map::new();
        let mut put = |k: &str, v: &Option<String>| {
            if let Some(val) = v {
                if !val.is_empty() {
                    out.insert(k.to_string(), Value::String(val.clone()));
                }
            }
        };
        put("service_name", &self.service_name);
        put("listing_id", &self.listing_id);
        put("storefront_url", &self.storefront_url);
        put("registry_url", &self.registry_url);
        out
    }

    pub fn is_empty(&self) -> bool {
        self.as_body().is_empty()
    }
}

/// Everything the gate needs, independent of the web framework.
///
/// `amount_per_request` is charged per gated request (a flat
/// one-token-per-call meter in v1). Batching is opt-in: with
/// `flush_interval_seconds` at 0 (the default) every charge is a
/// synchronous consume, which keeps behavior deterministic and the
/// overdraft window zero. Set it positive to batch charges above
/// `low_balance_threshold` and flush them on the interval; charges that
/// would bring the estimated balance to within the threshold of zero
/// stay synchronous so exhaustion still surfaces immediately.
#[derive(Clone, Debug)]
pub struct GateConfig {
    pub service_url: String,
    pub admin_key: String,
    pub amount_per_request: i64,
    pub verify_ttl_seconds: f64,
    pub low_balance_threshold: i64,
    pub flush_interval_seconds: f64,
    pub flush_max_batch: usize,
    pub request_timeout_seconds: f64,
    pub purchase: PurchasePointer,
}

impl Default for GateConfig {
    fn default() -> Self {
        Self {
            service_url: "http://localhost:8082".to_string(),
            admin_key: String::new(),
            amount_per_request: 1,
            verify_ttl_seconds: 30.0,
            low_balance_threshold: 0,
            flush_interval_seconds: 0.0,
            flush_max_batch: 256,
            request_timeout_seconds: 10.0,
            purchase: PurchasePointer::default(),
        }
    }
}

impl GateConfig {
    /// Build from `<prefix>*` environment variables, recognising the
    /// same names as the Python `GateConfig.from_env` (default prefix
    /// `APITOKENS_MIDDLEWARE_`).
    pub fn from_env(prefix: &str) -> Self {
        let get = |name: &str| env::var(format!("{prefix}{name}")).unwrap_or_default();
        let some = |s: String| if s.is_empty() { None } else { Some(s) };
        let int = |name: &str, default: i64| {
            let raw = get(name);
            if raw.is_empty() {
                default
            } else {
                raw.parse().unwrap_or(default)
            }
        };
        let float = |name: &str, default: f64| {
            let raw = get(name);
            if raw.is_empty() {
                default
            } else {
                raw.parse().unwrap_or(default)
            }
        };

        let service_url = {
            let raw = get("SERVICE_URL");
            let raw = if raw.is_empty() {
                "http://localhost:8082".to_string()
            } else {
                raw
            };
            raw.trim_end_matches('/').to_string()
        };

        GateConfig {
            service_url,
            admin_key: get("ADMIN_KEY"),
            amount_per_request: int("AMOUNT_PER_REQUEST", 1),
            verify_ttl_seconds: float("VERIFY_TTL_SECONDS", 30.0),
            low_balance_threshold: int("LOW_BALANCE_THRESHOLD", 0),
            flush_interval_seconds: float("FLUSH_INTERVAL_SECONDS", 0.0),
            flush_max_batch: int("FLUSH_MAX_BATCH", 256) as usize,
            request_timeout_seconds: float("REQUEST_TIMEOUT_SECONDS", 10.0),
            purchase: PurchasePointer {
                service_name: some(get("PURCHASE_SERVICE_NAME")),
                listing_id: some(get("PURCHASE_LISTING_ID")),
                storefront_url: some(get("PURCHASE_STOREFRONT_URL")),
                registry_url: some(get("PURCHASE_REGISTRY_URL")),
            },
        }
    }
}
