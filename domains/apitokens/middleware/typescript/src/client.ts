/**
 * Client for the tokens service's middleware-facing surface.
 *
 * Thin wrapper over `verify` / `consume` / `consume-batch`. All
 * verification and accounting authority lives in the service; this only
 * shapes requests and classifies responses into the small result vocab
 * the gate dispatches on. The `fetch` implementation is injectable so
 * the conformance harness can drive the real client against an
 * in-process server (mirroring Python's `httpx.MockTransport`).
 */

// Service reason vocabulary (mirrors services.keys_service constants).
export const KEY_NOT_FOUND = "key_not_found";
export const KEY_REVOKED = "key_revoked";
export const INSUFFICIENT_CREDITS = "insufficient_credits";

export interface VerifyResult {
  valid: boolean;
  status: string | null;
  balance: number;
}

export interface ConsumeResult {
  ok: boolean;
  balance: number;
  consumed: number;
  duplicate: boolean;
  reason: string | null; // set when ok is false
}

export interface ConsumeItem {
  key_id: string;
  amount: number;
  idempotency_key: string;
}

export type FetchFn = typeof fetch;

/**
 * The slice of the tokens service the gate depends on. `TokensClient`
 * implements it over HTTP; tests provide a fake (mirroring the duck
 * typing the Python gate relies on).
 */
export interface TokensApi {
  verify(keyId: string, secret: string): Promise<VerifyResult>;
  consume(
    keyId: string,
    amount: number,
    idempotencyKey?: string,
  ): Promise<ConsumeResult>;
  consumeBatch(items: ConsumeItem[]): Promise<ConsumeResult[]>;
}

function toInt(value: unknown): number {
  const n = Number(value);
  return Number.isFinite(n) ? Math.trunc(n) : 0;
}

/**
 * Calls the tokens service for one gated app. Pass a custom `fetchFn`
 * to drive a pooled or mocked transport; defaults to the global
 * `fetch`.
 */
export class TokensClient implements TokensApi {
  private readonly base: string;
  private readonly headers: Record<string, string>;
  private readonly timeoutMs: number;
  private readonly fetchFn: FetchFn;

  constructor(opts: {
    serviceUrl: string;
    adminKey?: string;
    timeoutSeconds?: number;
    fetchFn?: FetchFn;
  }) {
    this.base = opts.serviceUrl.replace(/\/+$/, "");
    this.headers = {
      "content-type": "application/json",
      ...(opts.adminKey ? { "X-Admin-Key": opts.adminKey } : {}),
    };
    this.timeoutMs = (opts.timeoutSeconds ?? 10) * 1000;
    this.fetchFn = opts.fetchFn ?? fetch;
  }

  private async post(path: string, body: unknown): Promise<Response> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeoutMs);
    try {
      return await this.fetchFn(this.base + path, {
        method: "POST",
        headers: this.headers,
        body: JSON.stringify(body),
        signal: controller.signal,
      });
    } finally {
      clearTimeout(timer);
    }
  }

  private static async json(resp: Response): Promise<Record<string, unknown>> {
    const text = await resp.text();
    if (!text) return {};
    try {
      return JSON.parse(text) as Record<string, unknown>;
    } catch {
      return {};
    }
  }

  async verify(keyId: string, secret: string): Promise<VerifyResult> {
    const resp = await this.post(`/api/v1/keys/${keyId}/verify`, { secret });
    if (resp.status !== 200) {
      // Auth/transport problems are treated as "not valid" — the gate
      // denies rather than failing open.
      return { valid: false, status: null, balance: 0 };
    }
    const data = await TokensClient.json(resp);
    return {
      valid: Boolean(data.valid),
      status: (data.status as string | null) ?? null,
      balance: toInt(data.balance),
    };
  }

  async consume(
    keyId: string,
    amount: number,
    idempotencyKey?: string,
  ): Promise<ConsumeResult> {
    const body: Record<string, unknown> = { amount: Math.trunc(amount) };
    if (idempotencyKey !== undefined) body.idempotency_key = idempotencyKey;
    const resp = await this.post(`/api/v1/keys/${keyId}/consume`, body);
    const data = await TokensClient.json(resp);
    if (resp.status === 200 && data.ok) {
      return {
        ok: true,
        balance: toInt(data.balance),
        consumed: toInt(data.consumed),
        duplicate: Boolean(data.duplicate),
        reason: null,
      };
    }
    // Refusals carry {error: reason, balance: B}; an unexpected status
    // with no error maps to insufficient_credits so the gate fails closed.
    const reason =
      (data.error as string) ?? (data.reason as string) ?? INSUFFICIENT_CREDITS;
    return {
      ok: false,
      balance: toInt(data.balance),
      consumed: 0,
      duplicate: false,
      reason,
    };
  }

  async consumeBatch(items: ConsumeItem[]): Promise<ConsumeResult[]> {
    const resp = await this.post("/api/v1/keys/consume-batch", { items });
    if (resp.status !== 200) {
      // The whole flush failed at the transport/auth layer; report every
      // item as a soft failure so the caller can retry.
      return items.map(() => ({
        ok: false,
        balance: 0,
        consumed: 0,
        duplicate: false,
        reason: "batch_unavailable",
      }));
    }
    const data = await TokensClient.json(resp);
    const results = (data.results as Record<string, unknown>[]) ?? [];
    return results.map((r) =>
      r.ok
        ? {
            ok: true,
            balance: toInt(r.balance),
            consumed: toInt(r.consumed),
            duplicate: Boolean(r.duplicate),
            reason: null,
          }
        : {
            ok: false,
            balance: toInt(r.balance),
            consumed: 0,
            duplicate: false,
            reason:
              (r.reason as string) ??
              (r.error as string) ??
              INSUFFICIENT_CREDITS,
          },
    );
  }
}
