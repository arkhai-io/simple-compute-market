/**
 * Framework-neutral token gate.
 *
 * One `TokenGate` instance backs any number of web adapters (the
 * Connect/Express and Web-fetch bindings in `adapter.ts`). It owns the
 * verify cache, the per-key balance estimate, the batched-charge
 * accumulator, and the background flush loop; an adapter only
 * translates a request's `Authorization` header into `authorize(...)`
 * and a `GateDecision` back into an HTTP response.
 *
 * Decision vocabulary (status + machine-readable body) is identical
 * across languages — it is the behavioral contract the conformance
 * fixtures pin (`../conformance`). This is a direct port of the Python
 * `apitokens_middleware.gate`.
 *
 * Concurrency: JavaScript is single-threaded, so a synchronous
 * read-modify-write of the state map is already atomic. The Python lock
 * exists only to make those compound mutations atomic across `await`
 * points; here we keep every state mutation in a synchronous block and
 * never `await` mid-mutation, which gives the same guarantee without an
 * explicit mutex.
 */

import {
  INSUFFICIENT_CREDITS,
  KEY_NOT_FOUND,
  KEY_REVOKED,
  type ConsumeItem,
  type TokensApi,
  type VerifyResult,
} from "./client.ts";
import { purchaseAsBody, type GateConfig } from "./config.ts";

// Error codes in the gate's own deny bodies — clients dispatch on these.
export const MISSING_API_KEY = "missing_api_key";
export const INVALID_API_KEY = "invalid_api_key";

export interface GateDecision {
  allowed: boolean;
  status: number;
  keyId: string | null;
  body: Record<string, unknown> | null;
}

interface KeyState {
  verify: VerifyResult;
  verifyExpires: number; // monotonic ms
  estimatedBalance: number;
  pending: ConsumeItem[];
  exhausted: boolean;
}

/** Monotonic clock in seconds (mirrors Python's `time.monotonic()`). */
function nowSeconds(): number {
  return performance.now() / 1000;
}

function randomIdempotencyKey(): string {
  // Hex, like Python's uuid4().hex — only needs to be unique per charge.
  return (
    Math.trunc(performance.now() * 1000).toString(16) +
    Math.trunc(Math.random() * 0xffffffff).toString(16)
  );
}

/**
 * Extract the bearer secret from an `Authorization` header. Accepts
 * `Bearer <secret>` (case-insensitive scheme) or a bare token, matching
 * the Python `parse_bearer`.
 */
export function parseBearer(authorization: string | null | undefined): string | null {
  if (!authorization) return null;
  const parts = authorization.trim().split(/\s+/, 2);
  if (parts.length === 2 && parts[0].toLowerCase() === "bearer") {
    return parts[1].trim() || null;
  }
  if (parts.length === 1 && parts[0]) {
    return parts[0].trim() || null;
  }
  return null;
}

/** The service issues secrets as `<key_id>.<random>`. */
export function keyIdFromSecret(secret: string): string | null {
  const keyId = secret.split(".", 1)[0];
  return keyId || null;
}

export class TokenGate {
  private readonly cfg: GateConfig;
  private readonly client: TokensApi;
  private readonly states = new Map<string, KeyState>();
  private flushTimer: ReturnType<typeof setInterval> | null = null;

  constructor(cfg: GateConfig, client: TokensApi) {
    this.cfg = cfg;
    this.client = client;
  }

  // -- lifecycle ----------------------------------------------------

  /** Begin the background flush loop (batched mode only). No-op when
   * batching is off; every charge is synchronous then. */
  start(): void {
    if (this.cfg.flushIntervalSeconds > 0 && this.flushTimer === null) {
      this.flushTimer = setInterval(() => {
        void this.flush();
      }, this.cfg.flushIntervalSeconds * 1000);
      // Don't keep the event loop alive just for the flush loop.
      this.flushTimer.unref?.();
    }
  }

  /** Stop the flush loop and drain any pending charges once more. */
  async close(): Promise<void> {
    if (this.flushTimer !== null) {
      clearInterval(this.flushTimer);
      this.flushTimer = null;
    }
    await this.flush();
  }

  // -- request path -------------------------------------------------

  async authorize(
    authorization: string | null | undefined,
    idempotencyKey?: string,
  ): Promise<GateDecision> {
    const secret = parseBearer(authorization);
    if (secret === null) {
      return { allowed: false, status: 401, keyId: null, body: { error: MISSING_API_KEY } };
    }
    const keyId = keyIdFromSecret(secret);
    if (keyId === null) {
      return { allowed: false, status: 401, keyId: null, body: { error: INVALID_API_KEY } };
    }

    const verify = await this.verifiedState(keyId, secret);
    if (!verify.valid) {
      if (verify.status === "revoked") {
        return this.deny(403, KEY_REVOKED, keyId);
      }
      return { allowed: false, status: 401, keyId, body: { error: INVALID_API_KEY } };
    }

    return this.charge(keyId, idempotencyKey);
  }

  private async verifiedState(keyId: string, secret: string): Promise<VerifyResult> {
    const now = nowSeconds();
    const cached = this.states.get(keyId);
    if (cached && cached.verifyExpires > now && cached.verify.valid) {
      return cached.verify;
    }

    const verify = await this.client.verify(keyId, secret);

    const existing = this.states.get(keyId);
    if (existing) {
      // Keep the running estimate (it may be ahead of the verify-reported
      // balance because of un-flushed charges).
      const estimated = existing.pending.length
        ? Math.min(existing.estimatedBalance, verify.balance)
        : verify.balance;
      existing.verify = verify;
      existing.verifyExpires = now + this.cfg.verifyTtlSeconds;
      existing.estimatedBalance = estimated;
      if (verify.valid) existing.exhausted = false;
    } else {
      this.states.set(keyId, {
        verify,
        verifyExpires: now + this.cfg.verifyTtlSeconds,
        estimatedBalance: verify.balance,
        pending: [],
        exhausted: false,
      });
    }
    return verify;
  }

  private async charge(keyId: string, idempotencyKey?: string): Promise<GateDecision> {
    const amount = this.cfg.amountPerRequest;
    const idem = idempotencyKey ?? randomIdempotencyKey();
    const batching = this.cfg.flushIntervalSeconds > 0;

    // Synchronous critical section: decide sync vs batched.
    const state = this.states.get(keyId)!;
    if (state.exhausted) {
      return this.deny(402, INSUFFICIENT_CREDITS, keyId);
    }
    const estimatedAfter = state.estimatedBalance - amount;
    const goSync = !batching || estimatedAfter <= this.cfg.lowBalanceThreshold;
    if (!goSync) {
      // Optimistic batched charge: let the request through now, settle it
      // with the service on the next flush.
      state.pending.push({ key_id: keyId, amount, idempotency_key: idem });
      state.estimatedBalance = estimatedAfter;
      return { allowed: true, status: 200, keyId, body: null };
    }

    // Synchronous charge — the network call, outside any critical section.
    const result = await this.client.consume(keyId, amount, idem);
    const after = this.states.get(keyId);
    if (after) after.estimatedBalance = result.balance;
    if (result.ok) {
      return { allowed: true, status: 200, keyId, body: null };
    }
    if (result.reason === KEY_REVOKED) {
      return this.deny(403, KEY_REVOKED, keyId);
    }
    if (result.reason === KEY_NOT_FOUND) {
      return { allowed: false, status: 401, keyId, body: { error: INVALID_API_KEY } };
    }
    const drained = this.states.get(keyId);
    if (drained) drained.exhausted = true;
    return this.deny(402, INSUFFICIENT_CREDITS, keyId);
  }

  // -- batched flush ------------------------------------------------

  /** Settle all accumulated batched charges with the service. */
  async flush(): Promise<void> {
    const items: ConsumeItem[] = [];
    const owners: string[] = [];
    for (const [keyId, state] of this.states) {
      for (const item of state.pending) {
        items.push({ ...item });
        owners.push(keyId);
      }
      state.pending.length = 0;
      if (items.length >= this.cfg.flushMaxBatch) break;
    }
    if (items.length === 0) return;

    const results = await this.client.consumeBatch(items);
    for (let i = 0; i < owners.length; i++) {
      const state = this.states.get(owners[i]);
      const result = results[i];
      if (!state || !result) continue;
      if (result.ok) {
        state.estimatedBalance = result.balance;
      } else if (result.reason === "batch_unavailable") {
        // Transport hiccup — requeue so the charge isn't lost.
        state.pending.push({
          key_id: owners[i],
          amount: this.cfg.amountPerRequest,
          idempotency_key: randomIdempotencyKey(),
        });
      } else {
        state.estimatedBalance = result.balance;
        state.exhausted = true;
      }
    }
  }

  // -- helpers ------------------------------------------------------

  private deny(status: number, error: string, keyId: string): GateDecision {
    const body: Record<string, unknown> = { error };
    const pointer = purchaseAsBody(this.cfg.purchase);
    if (Object.keys(pointer).length > 0) body.purchase = pointer;
    return { allowed: false, status, keyId, body };
  }
}
