//! Client for the tokens service's middleware-facing surface.
//!
//! Thin wrapper over `verify` / `consume` / `consume-batch`. All
//! verification and accounting authority lives in the service; this only
//! shapes requests and classifies responses into the small result vocab
//! the gate dispatches on. The gate depends on the [`TokensApi`] trait,
//! so the conformance harness can drive the real [`TokensClient`]
//! against an in-process server (mirroring Python's `httpx.MockTransport`).

use std::future::Future;
use std::time::Duration;

use serde_json::{json, Value};

// Service reason vocabulary (mirrors services.keys_service constants).
pub const KEY_NOT_FOUND: &str = "key_not_found";
pub const KEY_REVOKED: &str = "key_revoked";
pub const INSUFFICIENT_CREDITS: &str = "insufficient_credits";

#[derive(Clone, Debug)]
pub struct VerifyResult {
    pub valid: bool,
    pub status: Option<String>,
    pub balance: i64,
}

#[derive(Clone, Debug)]
pub struct ConsumeResult {
    pub ok: bool,
    pub balance: i64,
    pub consumed: i64,
    pub duplicate: bool,
    /// Set when `ok` is false.
    pub reason: Option<String>,
}

#[derive(Clone, Debug)]
pub struct ConsumeItem {
    pub key_id: String,
    pub amount: i64,
    pub idempotency_key: String,
}

/// The slice of the tokens service the gate depends on. [`TokensClient`]
/// implements it over HTTP; tests provide a fake. Methods return
/// `impl Future + Send` so the gate's futures stay `Send` for the tower
/// adapter.
pub trait TokensApi: Send + Sync {
    fn verify(&self, key_id: &str, secret: &str) -> impl Future<Output = VerifyResult> + Send;
    fn consume(
        &self,
        key_id: &str,
        amount: i64,
        idempotency_key: Option<&str>,
    ) -> impl Future<Output = ConsumeResult> + Send;
    fn consume_batch(
        &self,
        items: &[ConsumeItem],
    ) -> impl Future<Output = Vec<ConsumeResult>> + Send;
}

fn as_i64(value: Option<&Value>) -> i64 {
    match value {
        Some(v) => v
            .as_i64()
            .or_else(|| v.as_f64().map(|f| f as i64))
            .unwrap_or(0),
        None => 0,
    }
}

fn as_string(value: Option<&Value>) -> Option<String> {
    value.and_then(|v| v.as_str()).map(str::to_string)
}

/// Calls the tokens service for one gated app over a pooled
/// `reqwest::Client`.
pub struct TokensClient {
    base: String,
    admin_key: String,
    http: reqwest::Client,
}

impl TokensClient {
    pub fn new(service_url: &str, admin_key: &str, timeout_seconds: f64) -> Self {
        let http = reqwest::Client::builder()
            .timeout(Duration::from_secs_f64(timeout_seconds.max(0.001)))
            .build()
            .expect("reqwest client");
        Self {
            base: service_url.trim_end_matches('/').to_string(),
            admin_key: admin_key.to_string(),
            http,
        }
    }

    /// POST and return `(status, json_body)`; `None` on a transport
    /// error. A missing/invalid body parses to `Null`, which the
    /// callers treat as an empty object.
    async fn post(&self, path: &str, body: Value) -> Option<(u16, Value)> {
        let url = format!("{}{}", self.base, path);
        let mut req = self.http.post(&url).json(&body);
        if !self.admin_key.is_empty() {
            req = req.header("X-Admin-Key", &self.admin_key);
        }
        match req.send().await {
            Ok(resp) => {
                let status = resp.status().as_u16();
                let value = resp.json::<Value>().await.unwrap_or(Value::Null);
                Some((status, value))
            }
            Err(_) => None,
        }
    }
}

impl TokensApi for TokensClient {
    async fn verify(&self, key_id: &str, secret: &str) -> VerifyResult {
        match self
            .post(&format!("/api/v1/keys/{key_id}/verify"), json!({ "secret": secret }))
            .await
        {
            Some((200, data)) => VerifyResult {
                valid: data.get("valid").and_then(Value::as_bool).unwrap_or(false),
                status: as_string(data.get("status")),
                balance: as_i64(data.get("balance")),
            },
            // Auth/transport problems are treated as "not valid" — the
            // gate denies rather than failing open.
            _ => VerifyResult {
                valid: false,
                status: None,
                balance: 0,
            },
        }
    }

    async fn consume(
        &self,
        key_id: &str,
        amount: i64,
        idempotency_key: Option<&str>,
    ) -> ConsumeResult {
        let mut body = json!({ "amount": amount });
        if let Some(idem) = idempotency_key {
            body["idempotency_key"] = json!(idem);
        }
        let (status, data) = self
            .post(&format!("/api/v1/keys/{key_id}/consume"), body)
            .await
            .unwrap_or((0, Value::Null));
        let ok = status == 200 && data.get("ok").and_then(Value::as_bool).unwrap_or(false);
        if ok {
            ConsumeResult {
                ok: true,
                balance: as_i64(data.get("balance")),
                consumed: as_i64(data.get("consumed")),
                duplicate: data.get("duplicate").and_then(Value::as_bool).unwrap_or(false),
                reason: None,
            }
        } else {
            // Refusals carry {error: reason, balance: B}; an unexpected
            // status with no error maps to insufficient_credits so the
            // gate fails closed.
            let reason = as_string(data.get("error"))
                .or_else(|| as_string(data.get("reason")))
                .unwrap_or_else(|| INSUFFICIENT_CREDITS.to_string());
            ConsumeResult {
                ok: false,
                balance: as_i64(data.get("balance")),
                consumed: 0,
                duplicate: false,
                reason: Some(reason),
            }
        }
    }

    async fn consume_batch(&self, items: &[ConsumeItem]) -> Vec<ConsumeResult> {
        let payload: Vec<Value> = items
            .iter()
            .map(|i| {
                json!({
                    "key_id": i.key_id,
                    "amount": i.amount,
                    "idempotency_key": i.idempotency_key,
                })
            })
            .collect();
        match self
            .post("/api/v1/keys/consume-batch", json!({ "items": payload }))
            .await
        {
            Some((200, data)) => {
                let results = data
                    .get("results")
                    .and_then(Value::as_array)
                    .cloned()
                    .unwrap_or_default();
                results
                    .iter()
                    .map(|r| {
                        if r.get("ok").and_then(Value::as_bool).unwrap_or(false) {
                            ConsumeResult {
                                ok: true,
                                balance: as_i64(r.get("balance")),
                                consumed: as_i64(r.get("consumed")),
                                duplicate: r
                                    .get("duplicate")
                                    .and_then(Value::as_bool)
                                    .unwrap_or(false),
                                reason: None,
                            }
                        } else {
                            ConsumeResult {
                                ok: false,
                                balance: as_i64(r.get("balance")),
                                consumed: 0,
                                duplicate: false,
                                reason: as_string(r.get("reason"))
                                    .or_else(|| as_string(r.get("error")))
                                    .or_else(|| Some(INSUFFICIENT_CREDITS.to_string())),
                            }
                        }
                    })
                    .collect()
            }
            // The whole flush failed at the transport/auth layer; report
            // every item as a soft failure so the caller can retry.
            _ => items
                .iter()
                .map(|_| ConsumeResult {
                    ok: false,
                    balance: 0,
                    consumed: 0,
                    duplicate: false,
                    reason: Some("batch_unavailable".to_string()),
                })
                .collect(),
        }
    }
}
