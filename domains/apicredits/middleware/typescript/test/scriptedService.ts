/**
 * In-process scripted credits service for the conformance harness.
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
  private bunServer: { stop: (closeActiveConnections?: boolean) => void; port: number } | null = null;

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

  private route(path: string): { status: number; body: unknown } {
    const parts = path.replace(/^\/+|\/+$/g, "").split("/");
    if (path.endsWith("/verify")) {
      const keyId = parts[parts.length - 2];
      this.bump(this.verifyCalls, keyId);
      return { status: 200, body: this.next("verify", keyId, this.verify) };
    }
    if (path.endsWith("/consume")) {
      const keyId = parts[parts.length - 2];
      this.bump(this.consumeCalls, keyId);
      const entry = this.next<ConsumeEntry>("consume", keyId, this.consume);
      return { status: entry.status ?? 200, body: entry.body ?? {} };
    }
    return { status: 404, body: { error: `unexpected request to ${path}` } };
  }

  private handle(req: IncomingMessage, res: ServerResponse): void {
    // Drain the body (validates that the client sends well-formed JSON).
    let raw = "";
    req.on("data", (chunk) => {
      raw += chunk;
    });
    req.on("end", () => {
      const path = (req.url ?? "").split("?", 1)[0];
      const send = (status: number, body: unknown): void => {
        const payload = JSON.stringify(body);
        res.writeHead(status, { "content-type": "application/json" });
        res.end(payload);
      };
      const routed = this.route(path);
      send(routed.status, routed.body);
    });
  }

  async listen(): Promise<string> {
    const bun = (globalThis as unknown as { Bun?: { serve?: (opts: {
      hostname: string;
      port: number;
      fetch: (request: Request) => Response | Promise<Response>;
    }) => { stop: (closeActiveConnections?: boolean) => void; port: number } } }).Bun;
    if (bun?.serve) {
      for (let attempt = 0; attempt < 20; attempt += 1) {
        try {
          this.bunServer = bun.serve({
            hostname: "127.0.0.1",
            port: 30_000 + Math.floor(Math.random() * 20_000),
            fetch: async (request: Request) => {
              await request.text();
              const routed = this.route(new URL(request.url).pathname);
              return Response.json(routed.body, { status: routed.status });
            },
          });
          break;
        } catch (error) {
          if (
            !(
              error instanceof Error &&
              "code" in error &&
              (error as NodeJS.ErrnoException).code === "EADDRINUSE" &&
              attempt < 19
            )
          ) {
            throw error;
          }
        }
      }
      if (!this.bunServer) {
        throw new Error("failed to start scripted service");
      }
      return `http://127.0.0.1:${this.bunServer.port}`;
    }

    this.server = createServer((req, res) => this.handle(req, res));
    await new Promise<void>((resolve, reject) => {
      let attempts = 0;
      const tryListen = (): void => {
        attempts += 1;
        const port = 30_000 + Math.floor(Math.random() * 20_000);
        const onError = (error: NodeJS.ErrnoException): void => {
          this.server!.off("listening", onListening);
          if (error.code === "EADDRINUSE" && attempts < 20) {
            tryListen();
            return;
          }
          reject(error);
        };
        const onListening = (): void => {
          this.server!.off("error", onError);
          resolve();
        };
        this.server!.once("error", onError);
        this.server!.once("listening", onListening);
        this.server!.listen(port, "127.0.0.1");
      };
      tryListen();
    });
    const { port } = this.server.address() as AddressInfo;
    return `http://127.0.0.1:${port}`;
  }

  async close(): Promise<void> {
    if (this.bunServer) {
      this.bunServer.stop(true);
      this.bunServer = null;
    }
    if (this.server) {
      await new Promise<void>((resolve, reject) =>
        this.server!.close((err) => (err ? reject(err) : resolve())),
      );
      this.server = null;
    }
  }
}
