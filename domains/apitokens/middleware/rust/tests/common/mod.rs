//! In-process scripted tokens service for the conformance + adapter tests.
//!
//! Mirrors the Python reference's `_ScriptedService`: replays ordered
//! verify/consume responses from a `session.json` `service` block,
//! repeating the last entry once exhausted, and counts calls per key.
//! Standing up a real `axum` server (rather than mocking the client)
//! keeps the harness honest about request shaping and response parsing —
//! the same intent as Python's `httpx.MockTransport`.
//!
//! Shared by both integration tests; each compiles this module
//! separately, so helpers only one test uses look "dead" to the other.
#![allow(dead_code)]

use std::collections::HashMap;
use std::sync::{Arc, Mutex};

use axum::extract::{Path, State};
use axum::http::StatusCode;
use axum::routing::post;
use axum::{Json, Router};
use serde_json::{json, Value};

pub struct ScriptState {
    verify: Value,
    consume: Value,
    cursor: HashMap<(String, String), usize>,
    pub verify_calls: HashMap<String, usize>,
    pub consume_calls: HashMap<String, usize>,
}

impl ScriptState {
    fn next(&mut self, kind: &str, key_id: &str, script: &Value) -> Value {
        let entries = script
            .get(key_id)
            .and_then(Value::as_array)
            .cloned()
            .unwrap_or_else(|| vec![json!({})]);
        let key = (kind.to_string(), key_id.to_string());
        let pos = *self.cursor.get(&key).unwrap_or(&0);
        let idx = pos.min(entries.len() - 1);
        *self.cursor.entry(key).or_insert(0) += 1;
        entries[idx].clone()
    }

    pub fn total_verify_calls(&self) -> usize {
        self.verify_calls.values().sum()
    }
    pub fn total_consume_calls(&self) -> usize {
        self.consume_calls.values().sum()
    }
}

type Shared = Arc<Mutex<ScriptState>>;

async fn verify_handler(
    State(state): State<Shared>,
    Path(key_id): Path<String>,
    Json(_body): Json<Value>,
) -> (StatusCode, Json<Value>) {
    let mut s = state.lock().unwrap();
    *s.verify_calls.entry(key_id.clone()).or_insert(0) += 1;
    let script = s.verify.clone();
    let body = s.next("verify", &key_id, &script);
    (StatusCode::OK, Json(body))
}

async fn consume_handler(
    State(state): State<Shared>,
    Path(key_id): Path<String>,
    Json(_body): Json<Value>,
) -> (StatusCode, Json<Value>) {
    let mut s = state.lock().unwrap();
    *s.consume_calls.entry(key_id.clone()).or_insert(0) += 1;
    let script = s.consume.clone();
    let entry = s.next("consume", &key_id, &script);
    let status = entry.get("status").and_then(Value::as_u64).unwrap_or(200) as u16;
    let body = entry.get("body").cloned().unwrap_or_else(|| json!({}));
    (
        StatusCode::from_u16(status).unwrap_or(StatusCode::INTERNAL_SERVER_ERROR),
        Json(body),
    )
}

/// Start the scripted service on an ephemeral port. Returns its base URL
/// and the shared state (for reading the per-key call counters).
pub async fn spawn_scripted_service(service: &Value) -> (String, Shared) {
    let state = Arc::new(Mutex::new(ScriptState {
        verify: service.get("verify").cloned().unwrap_or_else(|| json!({})),
        consume: service.get("consume").cloned().unwrap_or_else(|| json!({})),
        cursor: HashMap::new(),
        verify_calls: HashMap::new(),
        consume_calls: HashMap::new(),
    }));

    let app = Router::new()
        .route("/api/v1/keys/{key_id}/verify", post(verify_handler))
        .route("/api/v1/keys/{key_id}/consume", post(consume_handler))
        .with_state(state.clone());

    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    tokio::spawn(async move {
        axum::serve(listener, app).await.unwrap();
    });
    (format!("http://{addr}"), state)
}
