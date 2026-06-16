/**
 * Gate configuration.
 *
 * A middleware is a seller-side component: it holds the operator's
 * `adminKey` and talks to the tokens service the same way the storefront
 * does. The `purchase` pointer is the only buyer-facing data — it rides
 * the 402/403 body so a client whose credits ran out knows where to buy
 * more (the re-purchase loop).
 *
 * This mirrors the Python reference (`apitokens_middleware.config`); the
 * behavioral contract is pinned by `../conformance/session.json`.
 */

/** Where a client buys more credits, embedded in exhaustion bodies. */
export interface PurchasePointer {
  serviceName?: string;
  listingId?: string;
  storefrontUrl?: string;
  registryUrl?: string;
}

/** Serialize a purchase pointer to its on-the-wire body (snake_case,
 * dropping empty fields), matching the Python `as_body()`. */
export function purchaseAsBody(p: PurchasePointer): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  if (p.serviceName) out.service_name = p.serviceName;
  if (p.listingId) out.listing_id = p.listingId;
  if (p.storefrontUrl) out.storefront_url = p.storefrontUrl;
  if (p.registryUrl) out.registry_url = p.registryUrl;
  return out;
}

/**
 * Everything the gate needs, independent of the web framework.
 *
 * `amountPerRequest` is charged per gated request (a flat
 * one-token-per-call meter in v1). Batching is opt-in: with
 * `flushIntervalSeconds` at 0 (the default) every charge is a
 * synchronous consume, which keeps behavior deterministic and the
 * overdraft window zero. Set it positive to batch charges above
 * `lowBalanceThreshold` and flush them on the interval; charges that
 * would bring the estimated balance to within the threshold of zero
 * stay synchronous so exhaustion still surfaces immediately.
 */
export interface GateConfig {
  serviceUrl: string;
  adminKey: string;
  amountPerRequest: number;
  verifyTtlSeconds: number;
  lowBalanceThreshold: number;
  flushIntervalSeconds: number;
  flushMaxBatch: number;
  requestTimeoutSeconds: number;
  purchase: PurchasePointer;
}

const DEFAULTS: Omit<GateConfig, "serviceUrl"> = {
  adminKey: "",
  amountPerRequest: 1,
  verifyTtlSeconds: 30,
  lowBalanceThreshold: 0,
  flushIntervalSeconds: 0,
  flushMaxBatch: 256,
  requestTimeoutSeconds: 10,
  purchase: {},
};

/** Fill a partial config with the same defaults as the Python dataclass. */
export function gateConfig(
  partial: Partial<GateConfig> & { serviceUrl: string },
): GateConfig {
  return {
    ...DEFAULTS,
    ...partial,
    serviceUrl: partial.serviceUrl.replace(/\/+$/, ""),
    purchase: { ...DEFAULTS.purchase, ...(partial.purchase ?? {}) },
  };
}

/**
 * Build a config from `<prefix>*` environment variables (default prefix
 * `APITOKENS_MIDDLEWARE_`), recognising the same names as the Python
 * `GateConfig.from_env`.
 */
export function gateConfigFromEnv(
  env: NodeJS.ProcessEnv = process.env,
  prefix = "APITOKENS_MIDDLEWARE_",
): GateConfig {
  const get = (name: string, fallback = ""): string =>
    env[prefix + name] ?? fallback;
  const int = (name: string, fallback: number): number => {
    const raw = get(name);
    if (!raw) return fallback;
    const n = Number.parseInt(raw, 10);
    return Number.isNaN(n) ? fallback : n;
  };
  const float = (name: string, fallback: number): number => {
    const raw = get(name);
    if (!raw) return fallback;
    const n = Number.parseFloat(raw);
    return Number.isNaN(n) ? fallback : n;
  };

  return gateConfig({
    serviceUrl: get("SERVICE_URL", "http://localhost:8082"),
    adminKey: get("ADMIN_KEY"),
    amountPerRequest: int("AMOUNT_PER_REQUEST", 1),
    verifyTtlSeconds: float("VERIFY_TTL_SECONDS", 30),
    lowBalanceThreshold: int("LOW_BALANCE_THRESHOLD", 0),
    flushIntervalSeconds: float("FLUSH_INTERVAL_SECONDS", 0),
    flushMaxBatch: int("FLUSH_MAX_BATCH", 256),
    requestTimeoutSeconds: float("REQUEST_TIMEOUT_SECONDS", 10),
    purchase: {
      serviceName: get("PURCHASE_SERVICE_NAME") || undefined,
      listingId: get("PURCHASE_LISTING_ID") || undefined,
      storefrontUrl: get("PURCHASE_STOREFRONT_URL") || undefined,
      registryUrl: get("PURCHASE_REGISTRY_URL") || undefined,
    },
  });
}
