/**
 * Reference harness that replays `conformance/session.json`.
 *
 * Drives the real `TokenGate` + `TokensClient` against the in-process
 * `ScriptedService` over real HTTP, so the test exercises request
 * shaping and response parsing — not a stub. Mirrors the Python
 * reference runner (`python/tests/conformance_runner.py`) step for step.
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { TokensClient } from "../src/client.ts";
import { gateConfig, type GateConfig } from "../src/config.ts";
import { TokenGate } from "../src/gate.ts";
import { ScriptedService } from "./scriptedService.ts";

const HERE = dirname(fileURLToPath(import.meta.url));
const CONFORMANCE_DIR = join(HERE, "..", "..", "conformance");

interface Session {
  config: Record<string, unknown> & { purchase?: Record<string, string> };
  service: Record<string, unknown>;
  steps: SessionStep[];
}
interface SessionStep {
  name: string;
  authorization: string | null;
  expect: {
    allowed: boolean;
    status: number;
    error?: string;
    purchase?: boolean;
  };
  verify_calls: number;
  consume_calls: number;
}

export function loadSession(name = "session.json"): Session {
  const text = readFileSync(join(CONFORMANCE_DIR, name), "utf-8");
  return JSON.parse(text) as Session;
}

function configFrom(session: Session, serviceUrl: string): GateConfig {
  const c = session.config;
  const p = session.config.purchase ?? {};
  return gateConfig({
    serviceUrl,
    adminKey: "conformance-admin-key",
    amountPerRequest: (c.amount_per_request as number) ?? 1,
    verifyTtlSeconds: (c.verify_ttl_seconds as number) ?? 30,
    lowBalanceThreshold: (c.low_balance_threshold as number) ?? 0,
    flushIntervalSeconds: (c.flush_interval_seconds as number) ?? 0,
    purchase: {
      serviceName: p.service_name,
      listingId: p.listing_id,
      storefrontUrl: p.storefront_url,
      registryUrl: p.registry_url,
    },
  });
}

export async function runSession(session: Session): Promise<void> {
  const service = new ScriptedService(session.service);
  const baseUrl = await service.listen();
  try {
    const config = configFrom(session, baseUrl);
    const client = new TokensClient({
      serviceUrl: config.serviceUrl,
      adminKey: config.adminKey,
    });
    const gate = new TokenGate(config, client);

    for (const step of session.steps) {
      const beforeV = service.totalVerifyCalls();
      const beforeC = service.totalConsumeCalls();
      const decision = await gate.authorize(step.authorization);
      const madeV = service.totalVerifyCalls() - beforeV;
      const madeC = service.totalConsumeCalls() - beforeC;

      const exp = step.expect;
      assert.equal(decision.allowed, exp.allowed, `[${step.name}] allowed`);
      assert.equal(decision.status, exp.status, `[${step.name}] status`);
      if (exp.error !== undefined) {
        assert.equal((decision.body ?? {}).error, exp.error, `[${step.name}] error`);
      }
      if (exp.purchase !== undefined) {
        const hasPurchase = Boolean(decision.body && "purchase" in decision.body);
        assert.equal(hasPurchase, exp.purchase, `[${step.name}] purchase pointer`);
      }
      assert.equal(madeV, step.verify_calls, `[${step.name}] verify calls`);
      assert.equal(madeC, step.consume_calls, `[${step.name}] consume calls`);
    }
  } finally {
    await service.close();
  }
}
