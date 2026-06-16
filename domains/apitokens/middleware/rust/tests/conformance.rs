//! The Rust middleware reproduces the shared conformance session.
//!
//! Drives the real `TokenGate` + `TokensClient` against the in-process
//! scripted service over real HTTP, replaying
//! `../conformance/session.json` step for step — the Rust analog of the
//! Python reference runner (`python/tests/conformance_runner.py`).

mod common;

use arkhai_apitokens_middleware::config::{GateConfig, PurchasePointer};
use arkhai_apitokens_middleware::{TokenGate, TokensClient};
use serde_json::Value;

use common::spawn_scripted_service;

const SESSION: &str = include_str!(concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/../conformance/session.json"
));

fn config_from(session: &Value, service_url: &str) -> GateConfig {
    let c = &session["config"];
    let p = &c["purchase"];
    let opt = |key: &str| p.get(key).and_then(Value::as_str).map(str::to_string);
    GateConfig {
        service_url: service_url.to_string(),
        admin_key: "conformance-admin-key".to_string(),
        amount_per_request: c["amount_per_request"].as_i64().unwrap_or(1),
        verify_ttl_seconds: c["verify_ttl_seconds"].as_f64().unwrap_or(30.0),
        low_balance_threshold: c["low_balance_threshold"].as_i64().unwrap_or(0),
        flush_interval_seconds: c["flush_interval_seconds"].as_f64().unwrap_or(0.0),
        purchase: PurchasePointer {
            service_name: opt("service_name"),
            listing_id: opt("listing_id"),
            storefront_url: opt("storefront_url"),
            registry_url: opt("registry_url"),
        },
        ..Default::default()
    }
}

#[tokio::test]
async fn recorded_session_matches() {
    let session: Value = serde_json::from_str(SESSION).expect("parse session.json");
    let (base_url, state) = spawn_scripted_service(&session["service"]).await;

    let config = config_from(&session, &base_url);
    let client = TokensClient::new(&config.service_url, &config.admin_key, 10.0);
    let gate = TokenGate::new(config, client);

    for step in session["steps"].as_array().expect("steps") {
        let name = step["name"].as_str().unwrap_or("");
        let authorization = step["authorization"].as_str();

        let (before_v, before_c) = {
            let s = state.lock().unwrap();
            (s.total_verify_calls(), s.total_consume_calls())
        };
        let decision = gate.authorize(authorization, None).await;
        let (made_v, made_c) = {
            let s = state.lock().unwrap();
            (
                s.total_verify_calls() - before_v,
                s.total_consume_calls() - before_c,
            )
        };

        let expect = &step["expect"];
        assert_eq!(
            decision.allowed,
            expect["allowed"].as_bool().unwrap(),
            "[{name}] allowed"
        );
        assert_eq!(
            decision.status as u64,
            expect["status"].as_u64().unwrap(),
            "[{name}] status"
        );
        if let Some(err) = expect.get("error").and_then(Value::as_str) {
            let got = decision
                .body
                .as_ref()
                .and_then(|b| b.get("error"))
                .and_then(Value::as_str);
            assert_eq!(got, Some(err), "[{name}] error");
        }
        if let Some(want_purchase) = expect.get("purchase").and_then(Value::as_bool) {
            let has_purchase = decision
                .body
                .as_ref()
                .map(|b| b.get("purchase").is_some())
                .unwrap_or(false);
            assert_eq!(has_purchase, want_purchase, "[{name}] purchase pointer");
        }
        assert_eq!(
            made_v,
            step["verify_calls"].as_u64().unwrap() as usize,
            "[{name}] verify calls"
        );
        assert_eq!(
            made_c,
            step["consume_calls"].as_u64().unwrap() as usize,
            "[{name}] consume calls"
        );
    }
}
