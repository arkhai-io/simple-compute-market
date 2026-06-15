/**
 * API-tokens gating middleware (TypeScript).
 *
 * A seller-side component that gates a downstream HTTP app on prepaid
 * API credits: it extracts the bearer key, verifies it against the
 * tokens service (short-TTL cache), meters each request by consuming
 * credits (synchronously near exhaustion, optionally batched above a
 * low-balance threshold), and maps a drained key to a 402 whose body
 * points at the listing to buy more (the re-purchase loop). All
 * verification and accounting authority stays in the service.
 *
 * The behavioral contract — status codes and machine-readable bodies —
 * is shared with the Python and Rust middlewares and pinned by the
 * conformance fixtures under
 * `domains/apitokens/middleware/conformance`.
 */

export {
  type GateConfig,
  type PurchasePointer,
  gateConfig,
  gateConfigFromEnv,
  purchaseAsBody,
} from "./config.ts";
export {
  type ConsumeItem,
  type ConsumeResult,
  type FetchFn,
  type TokensApi,
  type VerifyResult,
  INSUFFICIENT_CREDITS,
  KEY_NOT_FOUND,
  KEY_REVOKED,
  TokensClient,
} from "./client.ts";
export {
  type GateDecision,
  INVALID_API_KEY,
  MISSING_API_KEY,
  TokenGate,
  keyIdFromSecret,
  parseBearer,
} from "./gate.ts";
export {
  resolveGate,
  tokenGateMiddleware,
  withTokenGate,
} from "./adapter.ts";
