//! The tower/axum layer end to end: a valid key reaches the app, an
//! exhausted key 402s with the purchase pointer, an excluded path is
//! served without a token, and a missing key 401s. Mirrors the Python
//! `test_asgi_*` cases.

mod common;

use std::sync::Arc;

use arkhai_apitokens_middleware::config::{GateConfig, PurchasePointer};
use arkhai_apitokens_middleware::{TokenGate, TokenGateLayer, TokensClient};
use axum::body::Body;
use axum::http::{Request, StatusCode};
use axum::routing::get;
use axum::{Json, Router};
use serde_json::{json, Value};
use tower::ServiceExt;

use common::spawn_scripted_service;

async fn forecast() -> Json<Value> {
    Json(json!({ "forecast": "sunny" }))
}

async fn read_json(body: Body) -> Value {
    let bytes = axum::body::to_bytes(body, usize::MAX).await.unwrap();
    serde_json::from_slice(&bytes).unwrap_or(Value::Null)
}

#[tokio::test]
async fn layer_allows_valid_then_402s_exhausted_and_excludes_health() {
    // Valid key with one credit, then exhausted.
    let service = json!({
        "verify": { "ak_live": [{ "valid": true, "status": "active", "balance": 1 }] },
        "consume": { "ak_live": [
            { "status": 200, "body": { "ok": true, "consumed": 1, "balance": 0 } },
            { "status": 402, "body": { "error": "insufficient_credits", "balance": 0 } }
        ]}
    });
    let (base_url, _state) = spawn_scripted_service(&service).await;

    let config = GateConfig {
        service_url: base_url.clone(),
        purchase: PurchasePointer {
            listing_id: Some("lst-1".to_string()),
            storefront_url: Some("http://sf".to_string()),
            ..Default::default()
        },
        ..Default::default()
    };
    let client = TokensClient::new(&config.service_url, "", 10.0);
    let gate = Arc::new(TokenGate::new(config, client));

    let app = Router::new()
        .route("/api/forecast", get(forecast))
        .route("/health", get(forecast))
        .layer(TokenGateLayer::new(gate));

    // First request: forwarded, the app answers.
    let r1 = app
        .clone()
        .oneshot(
            Request::builder()
                .uri("/api/forecast")
                .header("authorization", "Bearer ak_live.s")
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(r1.status(), StatusCode::OK);
    assert_eq!(read_json(r1.into_body()).await, json!({ "forecast": "sunny" }));

    // Second request: exhausted → 402 with the purchase pointer.
    let r2 = app
        .clone()
        .oneshot(
            Request::builder()
                .uri("/api/forecast")
                .header("authorization", "Bearer ak_live.s")
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(r2.status(), StatusCode::PAYMENT_REQUIRED);
    let body = read_json(r2.into_body()).await;
    assert_eq!(body["error"], "insufficient_credits");
    assert_eq!(body["purchase"]["listing_id"], "lst-1");

    // Health is excluded — served without a token.
    let r3 = app
        .clone()
        .oneshot(Request::builder().uri("/health").body(Body::empty()).unwrap())
        .await
        .unwrap();
    assert_eq!(r3.status(), StatusCode::OK);
}

#[tokio::test]
async fn layer_missing_key_is_401() {
    let service = json!({
        "verify": { "ak_live": [{ "valid": true, "status": "active", "balance": 5 }] },
        "consume": { "ak_live": [{ "status": 200, "body": { "ok": true, "consumed": 1, "balance": 4 } }] }
    });
    let (base_url, _state) = spawn_scripted_service(&service).await;

    let config = GateConfig {
        service_url: base_url,
        ..Default::default()
    };
    let client = TokensClient::new(&config.service_url, "", 10.0);
    let gate = Arc::new(TokenGate::new(config, client));

    let app = Router::new()
        .route("/api/forecast", get(forecast))
        .layer(TokenGateLayer::new(gate));

    let resp = app
        .oneshot(Request::builder().uri("/api/forecast").body(Body::empty()).unwrap())
        .await
        .unwrap();
    assert_eq!(resp.status(), StatusCode::UNAUTHORIZED);
    assert_eq!(read_json(resp.into_body()).await["error"], "missing_api_key");
}
