//! tower/axum binding of the token gate.
//!
//! Per the design, all behavior lives in [`TokenGate`]; this layer just
//! lifts the `Authorization` header, asks the gate, and either forwards
//! to the inner service or writes the deny response. It operates on
//! `axum::body::Body`, which unifies the inner and deny body types, so
//! it drops into any axum `Router` via `.layer(TokenGateLayer::new(..))`
//! and composes with any tower `Service` over that body.

use std::collections::HashSet;
use std::future::Future;
use std::pin::Pin;
use std::sync::Arc;
use std::task::{Context, Poll};

use axum::body::Body;
use axum::http::{header, Request, Response, StatusCode};
use tower::{Layer, Service};

use crate::client::TokensApi;
use crate::gate::{GateDecision, TokenGate};

/// Gate every request through a shared [`TokenGate`]. `exclude_paths`
/// are served without a token (health checks, docs).
pub struct TokenGateLayer<C> {
    gate: Arc<TokenGate<C>>,
    exclude: Arc<HashSet<String>>,
}

// Hand-written so the `C: Clone` bound the derive would add is dropped —
// both fields are `Arc`, so cloning never touches `C`.
impl<C> Clone for TokenGateLayer<C> {
    fn clone(&self) -> Self {
        Self {
            gate: self.gate.clone(),
            exclude: self.exclude.clone(),
        }
    }
}

impl<C> TokenGateLayer<C> {
    /// Excludes `/health` by default.
    pub fn new(gate: Arc<TokenGate<C>>) -> Self {
        Self::with_excludes(gate, ["/health"])
    }

    pub fn with_excludes<I, S>(gate: Arc<TokenGate<C>>, excludes: I) -> Self
    where
        I: IntoIterator<Item = S>,
        S: Into<String>,
    {
        Self {
            gate,
            exclude: Arc::new(excludes.into_iter().map(Into::into).collect()),
        }
    }
}

impl<S, C> Layer<S> for TokenGateLayer<C> {
    type Service = TokenGateService<S, C>;

    fn layer(&self, inner: S) -> Self::Service {
        TokenGateService {
            inner,
            gate: self.gate.clone(),
            exclude: self.exclude.clone(),
        }
    }
}

pub struct TokenGateService<S, C> {
    inner: S,
    gate: Arc<TokenGate<C>>,
    exclude: Arc<HashSet<String>>,
}

// Clone only the inner service and the `Arc`s — never `C`.
impl<S: Clone, C> Clone for TokenGateService<S, C> {
    fn clone(&self) -> Self {
        Self {
            inner: self.inner.clone(),
            gate: self.gate.clone(),
            exclude: self.exclude.clone(),
        }
    }
}

impl<S, C> Service<Request<Body>> for TokenGateService<S, C>
where
    S: Service<Request<Body>, Response = Response<Body>> + Clone + Send + 'static,
    S::Future: Send + 'static,
    C: TokensApi + 'static,
{
    type Response = Response<Body>;
    type Error = S::Error;
    type Future = Pin<Box<dyn Future<Output = Result<Self::Response, Self::Error>> + Send>>;

    fn poll_ready(&mut self, cx: &mut Context<'_>) -> Poll<Result<(), Self::Error>> {
        self.inner.poll_ready(cx)
    }

    fn call(&mut self, req: Request<Body>) -> Self::Future {
        let gate = self.gate.clone();
        let exclude = self.exclude.clone();
        // Clone-and-replace so the future drives the instance we polled
        // ready, not a fresh clone (the standard tower middleware dance).
        let clone = self.inner.clone();
        let mut inner = std::mem::replace(&mut self.inner, clone);

        Box::pin(async move {
            let path = req.uri().path().to_string();
            if exclude.contains(&path) {
                return inner.call(req).await;
            }
            let authorization = req
                .headers()
                .get(header::AUTHORIZATION)
                .and_then(|v| v.to_str().ok())
                .map(str::to_string);
            let decision = gate.authorize(authorization.as_deref(), None).await;
            if decision.allowed {
                inner.call(req).await
            } else {
                Ok(deny_response(decision))
            }
        })
    }
}

fn deny_response(decision: GateDecision) -> Response<Body> {
    let body = decision.body.unwrap_or_else(|| serde_json::json!({}));
    let payload = serde_json::to_vec(&body).unwrap_or_default();
    Response::builder()
        .status(StatusCode::from_u16(decision.status).unwrap_or(StatusCode::INTERNAL_SERVER_ERROR))
        .header(header::CONTENT_TYPE, "application/json")
        .body(Body::from(payload))
        .expect("deny response")
}
