/**
 * In-process scripted tokens service for the conformance harness.
 *
 * Mirrors the Python reference's `_ScriptedService`: replays ordered
 * verify/consume responses from a `session.json` `service` block,
 * repeating the last entry once exhausted, and counts calls per key.
 * Standing up a real `http.Server` (rather than monkeypatching fetch)
 * keeps the harness honest about request shaping and response parsing —
 * the same intent as Python's `httpx.MockTransport`.
 */

import { createServer, type IncomingMessage, type Server, type ServerResponse } from "node:http";
import { type AddressInfo } from "node:net";

interface ConsumeEntry {
  status?: number;
  body?: Record<string, unknown>;
}
interface ServiceScript {
  verify?: Record<string, Record<string, unknown>[]>;
  consume?: Record<string, ConsumeEntry[]>;
}

export class ScriptedService {
  readonly verifyCalls = new Map<string, number>();
  readonly consumeCalls = new Map<string, number>();
  private readonly cursor = new Map<string, number>();
  private readonly verify: Record<string, Record<string, unknown>[]>;
  private readonly consume: Record<string, ConsumeEntry[]>;
  private server: Server | null = null;

  constructor(service: ServiceScript) {
    this.verify = service.verify ?? {};
    this.consume = service.consume ?? {};
  }

  private next<T>(kind: string, keyId: string, script: Record<string, T[]>): T {
    const entries = script[keyId] ?? ([{}] as T[]);
    const cursorKey = `${kind}:${keyId}`;
    const idx = Math.min(this.cursor.get(cursorKey) ?? 0, entries.length - 1);
    this.cursor.set(cursorKey, (this.cursor.get(cursorKey) ?? 0) + 1);
    return entries[idx];
  }

  private bump(counter: Map<string, number>, keyId: string): void {
    counter.set(keyId, (counter.get(keyId) ?? 0) + 1);
  }

  totalVerifyCalls(): number {
    return [...this.verifyCalls.values()].reduce((a, b) => a + b, 0);
  }
  totalConsumeCalls(): number {
    return [...this.consumeCalls.values()].reduce((a, b) => a + b, 0);
  }

  private handle(req: IncomingMessage, res: ServerResponse): void {
    // Drain the body (validates that the client sends well-formed JSON).
    let raw = "";
    req.on("data", (chunk) => {
      raw += chunk;
    });
    req.on("end", () => {
      const path = (req.url ?? "").split("?", 1)[0];
      const parts = path.replace(/^\/+|\/+$/g, "").split("/");
      const send = (status: number, body: unknown): void => {
        const payload = JSON.stringify(body);
        res.writeHead(status, { "content-type": "application/json" });
        res.end(payload);
      };
      if (path.endsWith("/verify")) {
        const keyId = parts[parts.length - 2];
        this.bump(this.verifyCalls, keyId);
        send(200, this.next("verify", keyId, this.verify));
        return;
      }
      if (path.endsWith("/consume")) {
        const keyId = parts[parts.length - 2];
        this.bump(this.consumeCalls, keyId);
        const entry = this.next<ConsumeEntry>("consume", keyId, this.consume);
        send(entry.status ?? 200, entry.body ?? {});
        return;
      }
      send(404, { error: `unexpected request to ${path}` });
    });
  }

  async listen(): Promise<string> {
    this.server = createServer((req, res) => this.handle(req, res));
    await new Promise<void>((resolve) => this.server!.listen(0, "127.0.0.1", resolve));
    const { port } = this.server.address() as AddressInfo;
    return `http://127.0.0.1:${port}`;
  }

  async close(): Promise<void> {
    if (this.server) {
      await new Promise<void>((resolve, reject) =>
        this.server!.close((err) => (err ? reject(err) : resolve())),
      );
      this.server = null;
    }
  }
}
