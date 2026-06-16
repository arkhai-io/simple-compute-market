/**
 * Batched-flush behavior and the framework adapters.
 *
 * The synchronous decision table is pinned by the conformance session;
 * these cover what is outside it: the optimistic batched charge path
 * (timing-dependent, so impl-local) and the two adapters end to end.
 * Mirrors the Python `test_gate.py`.
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  type ConsumeItem,
  type ConsumeResult,
  type TokensApi,
  type VerifyResult,
} from "../src/client.ts";
import { gateConfig, type GateConfig } from "../src/config.ts";
import { TokenGate } from "../src/gate.ts";
import { tokenGateMiddleware, withTokenGate } from "../src/adapter.ts";

class FakeClient implements TokensApi {
  verifyCalls = 0;
  consumeCalls: { keyId: string; amount: number }[] = [];
  batchCalls: ConsumeItem[][] = [];
  private balance: number;
  constructor(balance: number) {
    this.balance = balance;
  }

  async verify(_keyId: string, _secret: string): Promise<VerifyResult> {
    this.verifyCalls += 1;
    return { valid: true, status: "active", balance: this.balance };
  }
  async consume(keyId: string, amount: number): Promise<ConsumeResult> {
    this.consumeCalls.push({ keyId, amount });
    this.balance = Math.max(0, this.balance - amount);
    return { ok: true, balance: this.balance, consumed: amount, duplicate: false, reason: null };
  }
  async consumeBatch(items: ConsumeItem[]): Promise<ConsumeResult[]> {
    this.batchCalls.push([...items]);
    return items.map((item) => {
      this.balance = Math.max(0, this.balance - item.amount);
      return { ok: true, balance: this.balance, consumed: item.amount, duplicate: false, reason: null };
    });
  }
}

function cfg(partial: Partial<GateConfig> = {}): GateConfig {
  return gateConfig({
    serviceUrl: "http://svc",
    amountPerRequest: 1,
    flushIntervalSeconds: 0,
    lowBalanceThreshold: 0,
    purchase: { listingId: "lst-1" },
    ...partial,
  });
}

test("batched charges accumulate then flush once", async () => {
  const client = new FakeClient(10);
  const gate = new TokenGate(cfg({ flushIntervalSeconds: 60, lowBalanceThreshold: 1 }), client);

  for (let i = 0; i < 3; i++) {
    const d = await gate.authorize("Bearer ak_live.s");
    assert.ok(d.allowed);
  }
  // Comfortably above threshold → no synchronous consume yet.
  assert.deepEqual(client.consumeCalls, []);
  assert.equal(client.verifyCalls, 1); // verify cached after the first

  await gate.flush();
  assert.equal(client.batchCalls.length, 1);
  assert.equal(client.batchCalls[0].length, 3);
});

test("charge goes synchronous near exhaustion", async () => {
  const client = new FakeClient(3);
  // threshold 2: a charge that would leave <= 2 estimated is synchronous.
  const gate = new TokenGate(cfg({ flushIntervalSeconds: 60, lowBalanceThreshold: 2 }), client);

  const d = await gate.authorize("Bearer ak_live.s"); // 3 -> est 2 <= 2 => sync
  assert.ok(d.allowed);
  assert.equal(client.consumeCalls.length, 1);
  assert.deepEqual(client.batchCalls, []);
});

test("connect middleware allows valid and 402s exhausted", async () => {
  let balance = 1;
  const client: TokensApi = {
    async verify() {
      return { valid: true, status: "active", balance };
    },
    async consume() {
      if (balance >= 1) {
        balance -= 1;
        return { ok: true, balance, consumed: 1, duplicate: false, reason: null };
      }
      return { ok: false, balance: 0, consumed: 0, duplicate: false, reason: "insufficient_credits" };
    },
    async consumeBatch() {
      return [];
    },
  };
  const gate = new TokenGate(
    cfg({ purchase: { listingId: "lst-1", storefrontUrl: "http://sf" } }),
    client,
  );
  const mw = tokenGateMiddleware({ gate });

  // Drive the middleware with a fake req/res, capturing the deny write.
  const run = (
    path: string,
    authorization?: string,
  ): Promise<{ nexted: boolean; status: number; body: string }> =>
    new Promise((resolve) => {
      let status = 0;
      let body = "";
      const res = {
        statusCode: 200,
        setHeader() {},
        end(chunk?: string) {
          status = this.statusCode;
          body = chunk ?? "";
          resolve({ nexted: false, status, body });
        },
      };
      const req = {
        path,
        headers: authorization ? { authorization } : {},
      };
      mw(req, res as never, () => resolve({ nexted: true, status: 200, body: "" }));
    });

  const r1 = await run("/api/forecast", "Bearer ak_live.s");
  assert.ok(r1.nexted, "first request forwarded to the app");

  const r2 = await run("/api/forecast", "Bearer ak_live.s");
  assert.equal(r2.status, 402);
  const parsed = JSON.parse(r2.body);
  assert.equal(parsed.error, "insufficient_credits");
  assert.equal(parsed.purchase.listing_id, "lst-1");

  // Health is excluded — forwarded without a token.
  const r3 = await run("/health");
  assert.ok(r3.nexted);
});

test("fetch adapter returns 401 on a missing key", async () => {
  const client: TokensApi = {
    async verify() {
      return { valid: true, status: "active", balance: 5 };
    },
    async consume() {
      return { ok: true, balance: 4, consumed: 1, duplicate: false, reason: null };
    },
    async consumeBatch() {
      return [];
    },
  };
  const gate = new TokenGate(cfg(), client);
  const app = withTokenGate({ gate }, () => Response.json({ ok: true }));

  const denied = await app(new Request("http://app/api/forecast"));
  assert.equal(denied.status, 401);
  assert.equal(((await denied.json()) as { error: string }).error, "missing_api_key");

  const ok = await app(
    new Request("http://app/api/forecast", { headers: { authorization: "Bearer ak_live.s" } }),
  );
  assert.equal(ok.status, 200);
});
