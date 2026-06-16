//! Framework-neutral token gate.
//!
//! One [`TokenGate`] instance backs any number of web adapters (the
//! tower layer in `tower_layer.rs` is the first). It owns the verify
//! cache, the per-key balance estimate, the batched-charge accumulator,
//! and the background flush loop; an adapter only translates a request's
//! `Authorization` header into [`TokenGate::authorize`] and a
//! [`GateDecision`] back into an HTTP response.
//!
//! Decision vocabulary (status + machine-readable body) is identical
//! across languages — it is the behavioral contract the conformance
//! fixtures pin (`../conformance`). Direct port of the Python
//! `apitokens_middleware.gate`.

use std::collections::HashMap;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use serde_json::{json, Map, Value};
use tokio::task::JoinHandle;

use crate::client::{ConsumeItem, TokensApi, VerifyResult, INSUFFICIENT_CREDITS, KEY_NOT_FOUND, KEY_REVOKED};
use crate::config::GateConfig;

// Error codes in the gate's own deny bodies — clients dispatch on these.
pub const MISSING_API_KEY: &str = "missing_api_key";
pub const INVALID_API_KEY: &str = "invalid_api_key";

/// Outcome of authorizing one request. `allowed` requests pass through
/// to the gated app. Denials carry a status (401/402/403) and a
/// machine-readable `body` — exhaustion and revocation bodies include
/// the `purchase` pointer so a client can re-enter the buy loop.
#[derive(Clone, Debug)]
pub struct GateDecision {
    pub allowed: bool,
    pub status: u16,
    pub key_id: Option<String>,
    pub body: Option<Value>,
}

impl GateDecision {
    fn allow(key_id: &str) -> Self {
        Self {
            allowed: true,
            status: 200,
            key_id: Some(key_id.to_string()),
            body: None,
        }
    }

    fn invalid(key_id: Option<&str>) -> Self {
        Self {
            allowed: false,
            status: 401,
            key_id: key_id.map(str::to_string),
            body: Some(json!({ "error": INVALID_API_KEY })),
        }
    }
}

struct KeyState {
    verify: VerifyResult,
    verify_expires: Instant,
    estimated_balance: i64,
    pending: Vec<ConsumeItem>,
    exhausted: bool,
}

/// Extract the bearer secret from an `Authorization` header. Accepts
/// `Bearer <secret>` (case-insensitive scheme) or a bare token, matching
/// the Python `parse_bearer`.
pub fn parse_bearer(authorization: Option<&str>) -> Option<String> {
    let trimmed = authorization?.trim();
    if trimmed.is_empty() {
        return None;
    }
    match trimmed.split_once(char::is_whitespace) {
        Some((scheme, rest)) => {
            if scheme.eq_ignore_ascii_case("bearer") {
                let secret = rest.trim();
                (!secret.is_empty()).then(|| secret.to_string())
            } else {
                // Two parts but not a bearer scheme: no usable secret.
                None
            }
        }
        // A bare token with no scheme is accepted as the secret.
        None => Some(trimmed.to_string()),
    }
}

/// The service issues secrets as `<key_id>.<random>`.
pub fn key_id_from_secret(secret: &str) -> Option<String> {
    let key_id = secret.split('.').next().unwrap_or("");
    (!key_id.is_empty()).then(|| key_id.to_string())
}

pub struct TokenGate<C> {
    cfg: GateConfig,
    client: C,
    states: Mutex<HashMap<String, KeyState>>,
    idem_counter: AtomicU64,
    flush_handle: Mutex<Option<JoinHandle<()>>>,
}

impl<C: TokensApi + 'static> TokenGate<C> {
    pub fn new(cfg: GateConfig, client: C) -> Self {
        Self {
            cfg,
            client,
            states: Mutex::new(HashMap::new()),
            idem_counter: AtomicU64::new(0),
            flush_handle: Mutex::new(None),
        }
    }

    fn next_idem(&self) -> String {
        format!("idem-{}", self.idem_counter.fetch_add(1, Ordering::Relaxed))
    }

    // -- lifecycle ----------------------------------------------------

    /// Begin the background flush loop (batched mode only). No-op when
    /// batching is off; every charge is synchronous then. Takes an
    /// `Arc<Self>` because the loop outlives the call.
    pub fn start(self: &Arc<Self>) {
        if self.cfg.flush_interval_seconds <= 0.0 {
            return;
        }
        let mut guard = self.flush_handle.lock().unwrap();
        if guard.is_some() {
            return;
        }
        let me = Arc::clone(self);
        let interval = Duration::from_secs_f64(self.cfg.flush_interval_seconds);
        *guard = Some(tokio::spawn(async move {
            loop {
                tokio::time::sleep(interval).await;
                me.flush().await;
            }
        }));
    }

    /// Stop the flush loop and drain any pending charges once more.
    pub async fn close(&self) {
        let handle = self.flush_handle.lock().unwrap().take();
        if let Some(handle) = handle {
            handle.abort();
        }
        self.flush().await;
    }

    // -- request path -------------------------------------------------

    pub async fn authorize(
        &self,
        authorization: Option<&str>,
        idempotency_key: Option<String>,
    ) -> GateDecision {
        let secret = match parse_bearer(authorization) {
            Some(secret) => secret,
            None => {
                return GateDecision {
                    allowed: false,
                    status: 401,
                    key_id: None,
                    body: Some(json!({ "error": MISSING_API_KEY })),
                }
            }
        };
        let key_id = match key_id_from_secret(&secret) {
            Some(key_id) => key_id,
            None => return GateDecision::invalid(None),
        };

        let verify = self.verified_state(&key_id, &secret).await;
        if !verify.valid {
            if verify.status.as_deref() == Some("revoked") {
                return self.deny(403, KEY_REVOKED, &key_id);
            }
            return GateDecision::invalid(Some(&key_id));
        }

        self.charge(&key_id, idempotency_key).await
    }

    async fn verified_state(&self, key_id: &str, secret: &str) -> VerifyResult {
        let now = Instant::now();
        {
            let states = self.states.lock().unwrap();
            if let Some(state) = states.get(key_id) {
                if state.verify_expires > now && state.verify.valid {
                    return state.verify.clone();
                }
            }
        }

        let verify = self.client.verify(key_id, secret).await;

        let ttl = Duration::from_secs_f64(self.cfg.verify_ttl_seconds);
        let mut states = self.states.lock().unwrap();
        match states.get_mut(key_id) {
            Some(existing) => {
                // Keep the running estimate (it may be ahead of the
                // verify-reported balance because of un-flushed charges).
                let estimated = if existing.pending.is_empty() {
                    verify.balance
                } else {
                    existing.estimated_balance.min(verify.balance)
                };
                existing.verify = verify.clone();
                existing.verify_expires = now + ttl;
                existing.estimated_balance = estimated;
                if verify.valid {
                    existing.exhausted = false;
                }
            }
            None => {
                states.insert(
                    key_id.to_string(),
                    KeyState {
                        verify: verify.clone(),
                        verify_expires: now + ttl,
                        estimated_balance: verify.balance,
                        pending: Vec::new(),
                        exhausted: false,
                    },
                );
            }
        }
        verify
    }

    async fn charge(&self, key_id: &str, idempotency_key: Option<String>) -> GateDecision {
        let amount = self.cfg.amount_per_request;
        let idem = idempotency_key.unwrap_or_else(|| self.next_idem());
        let batching = self.cfg.flush_interval_seconds > 0.0;

        {
            let mut states = self.states.lock().unwrap();
            let state = states
                .get_mut(key_id)
                .expect("state present after verified_state");
            if state.exhausted {
                drop(states);
                return self.deny(402, INSUFFICIENT_CREDITS, key_id);
            }
            let estimated_after = state.estimated_balance - amount;
            let go_sync = !batching || estimated_after <= self.cfg.low_balance_threshold;
            if !go_sync {
                // Optimistic batched charge: let the request through now,
                // settle it with the service on the next flush.
                state.pending.push(ConsumeItem {
                    key_id: key_id.to_string(),
                    amount,
                    idempotency_key: idem,
                });
                state.estimated_balance = estimated_after;
                return GateDecision::allow(key_id);
            }
        }

        // Synchronous charge — the network call, outside the lock.
        let result = self.client.consume(key_id, amount, Some(&idem)).await;
        {
            let mut states = self.states.lock().unwrap();
            if let Some(state) = states.get_mut(key_id) {
                state.estimated_balance = result.balance;
            }
        }
        if result.ok {
            return GateDecision::allow(key_id);
        }
        match result.reason.as_deref() {
            Some(KEY_REVOKED) => self.deny(403, KEY_REVOKED, key_id),
            Some(KEY_NOT_FOUND) => GateDecision::invalid(Some(key_id)),
            _ => {
                let mut states = self.states.lock().unwrap();
                if let Some(state) = states.get_mut(key_id) {
                    state.exhausted = true;
                }
                drop(states);
                self.deny(402, INSUFFICIENT_CREDITS, key_id)
            }
        }
    }

    // -- batched flush ------------------------------------------------

    /// Settle all accumulated batched charges with the service.
    pub async fn flush(&self) {
        let (items, owners) = {
            let mut states = self.states.lock().unwrap();
            let mut items: Vec<ConsumeItem> = Vec::new();
            let mut owners: Vec<String> = Vec::new();
            for (key_id, state) in states.iter_mut() {
                for item in state.pending.drain(..) {
                    owners.push(key_id.clone());
                    items.push(item);
                }
                if items.len() >= self.cfg.flush_max_batch {
                    break;
                }
            }
            (items, owners)
        };
        if items.is_empty() {
            return;
        }

        let results = self.client.consume_batch(&items).await;
        let mut states = self.states.lock().unwrap();
        for (owner, result) in owners.iter().zip(results.iter()) {
            let Some(state) = states.get_mut(owner) else {
                continue;
            };
            if result.ok {
                state.estimated_balance = result.balance;
            } else if result.reason.as_deref() == Some("batch_unavailable") {
                // Transport hiccup — requeue so the charge isn't lost.
                state.pending.push(ConsumeItem {
                    key_id: owner.clone(),
                    amount: self.cfg.amount_per_request,
                    idempotency_key: format!(
                        "idem-{}",
                        self.idem_counter.fetch_add(1, Ordering::Relaxed)
                    ),
                });
            } else {
                state.estimated_balance = result.balance;
                state.exhausted = true;
            }
        }
    }

    // -- helpers ------------------------------------------------------

    fn deny(&self, status: u16, error: &str, key_id: &str) -> GateDecision {
        let mut body: Map<String, Value> = Map::new();
        body.insert("error".to_string(), Value::String(error.to_string()));
        let pointer = self.cfg.purchase.as_body();
        if !pointer.is_empty() {
            body.insert("purchase".to_string(), Value::Object(pointer));
        }
        GateDecision {
            allowed: false,
            status,
            key_id: Some(key_id.to_string()),
            body: Some(Value::Object(body)),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::client::{ConsumeResult, VerifyResult};
    use crate::config::PurchasePointer;
    use std::sync::Mutex as StdMutex;

    /// Records calls and returns canned results — for batch-vs-sync
    /// asserts (mirrors the Python `FakeClient`).
    struct FakeClient {
        balance: StdMutex<i64>,
        verify_calls: StdMutex<usize>,
        consume_calls: StdMutex<Vec<(String, i64)>>,
        batch_calls: StdMutex<Vec<Vec<ConsumeItem>>>,
    }

    impl FakeClient {
        fn new(balance: i64) -> Self {
            Self {
                balance: StdMutex::new(balance),
                verify_calls: StdMutex::new(0),
                consume_calls: StdMutex::new(Vec::new()),
                batch_calls: StdMutex::new(Vec::new()),
            }
        }
    }

    impl TokensApi for FakeClient {
        async fn verify(&self, _key_id: &str, _secret: &str) -> VerifyResult {
            *self.verify_calls.lock().unwrap() += 1;
            VerifyResult {
                valid: true,
                status: Some("active".to_string()),
                balance: *self.balance.lock().unwrap(),
            }
        }

        async fn consume(
            &self,
            key_id: &str,
            amount: i64,
            _idempotency_key: Option<&str>,
        ) -> ConsumeResult {
            self.consume_calls
                .lock()
                .unwrap()
                .push((key_id.to_string(), amount));
            let mut bal = self.balance.lock().unwrap();
            *bal = (*bal - amount).max(0);
            ConsumeResult {
                ok: true,
                balance: *bal,
                consumed: amount,
                duplicate: false,
                reason: None,
            }
        }

        async fn consume_batch(&self, items: &[ConsumeItem]) -> Vec<ConsumeResult> {
            self.batch_calls.lock().unwrap().push(items.to_vec());
            let mut out = Vec::new();
            let mut bal = self.balance.lock().unwrap();
            for item in items {
                *bal = (*bal - item.amount).max(0);
                out.push(ConsumeResult {
                    ok: true,
                    balance: *bal,
                    consumed: item.amount,
                    duplicate: false,
                    reason: None,
                });
            }
            out
        }
    }

    fn cfg(flush_interval_seconds: f64, low_balance_threshold: i64) -> GateConfig {
        GateConfig {
            service_url: "http://svc".to_string(),
            amount_per_request: 1,
            flush_interval_seconds,
            low_balance_threshold,
            purchase: PurchasePointer {
                listing_id: Some("lst-1".to_string()),
                ..Default::default()
            },
            ..Default::default()
        }
    }

    #[test]
    fn parse_bearer_variants() {
        assert_eq!(parse_bearer(Some("Bearer ak.s")).as_deref(), Some("ak.s"));
        assert_eq!(parse_bearer(Some("bearer   ak.s")).as_deref(), Some("ak.s"));
        assert_eq!(parse_bearer(Some("ak.s")).as_deref(), Some("ak.s"));
        // Trailing space trims away, leaving a bare token — same as the
        // Python reference's `strip().split()` (returns the lone word).
        assert_eq!(parse_bearer(Some("Bearer ")).as_deref(), Some("Bearer"));
        assert_eq!(parse_bearer(Some("")), None);
        assert_eq!(parse_bearer(Some("   ")), None);
        assert_eq!(parse_bearer(None), None);
        assert_eq!(key_id_from_secret(".nokey"), None);
        assert_eq!(key_id_from_secret("ak_live.s3").as_deref(), Some("ak_live"));
    }

    #[tokio::test]
    async fn batched_charges_accumulate_then_flush_once() {
        let client = FakeClient::new(10);
        let gate = TokenGate::new(cfg(60.0, 1), client);

        for _ in 0..3 {
            let d = gate.authorize(Some("Bearer ak_live.s"), None).await;
            assert!(d.allowed);
        }
        // Comfortably above threshold → no synchronous consume yet.
        assert!(gate.client.consume_calls.lock().unwrap().is_empty());
        assert_eq!(*gate.client.verify_calls.lock().unwrap(), 1); // cached

        gate.flush().await;
        let batches = gate.client.batch_calls.lock().unwrap();
        assert_eq!(batches.len(), 1);
        assert_eq!(batches[0].len(), 3);
    }

    #[tokio::test]
    async fn charge_goes_synchronous_near_exhaustion() {
        let client = FakeClient::new(3);
        // threshold 2: a charge that would leave <= 2 estimated is sync.
        let gate = TokenGate::new(cfg(60.0, 2), client);

        let d = gate.authorize(Some("Bearer ak_live.s"), None).await; // 3 -> est 2 <= 2
        assert!(d.allowed);
        assert_eq!(gate.client.consume_calls.lock().unwrap().len(), 1);
        assert!(gate.client.batch_calls.lock().unwrap().is_empty());
    }
}
