/**
 * Web framework bindings of the token gate.
 *
 * Per the design, all behavior lives in `TokenGate`; these adapters
 * just lift the `Authorization` header, ask the gate, and either
 * forward to the app or write the deny response. Two bindings ship: a
 * Connect/Express-style middleware and a Web `fetch` handler wrapper.
 * Neither imports a framework — they rely on structural typing so the
 * package stays dependency-free.
 */

import { TokensClient } from "./client.ts";
import { type GateConfig } from "./config.ts";
import { TokenGate, type GateDecision } from "./gate.ts";

/** Build a gate from config, or accept a ready one. */
export function resolveGate(opts: {
  gate?: TokenGate;
  config?: GateConfig;
  client?: TokensClient;
}): TokenGate {
  if (opts.gate) return opts.gate;
  if (!opts.config) {
    throw new Error("token gate adapter needs either a gate or a config");
  }
  const client =
    opts.client ??
    new TokensClient({
      serviceUrl: opts.config.serviceUrl,
      adminKey: opts.config.adminKey,
      timeoutSeconds: opts.config.requestTimeoutSeconds,
    });
  return new TokenGate(opts.config, client);
}

function isExcluded(path: string, exclude: Set<string>): boolean {
  // Compare against the path without its query string.
  const clean = path.split("?", 1)[0];
  return exclude.has(clean);
}

// -- Connect/Express middleware ---------------------------------------

interface ConnectRequest {
  path?: string;
  url?: string;
  headers: Record<string, string | string[] | undefined>;
}
interface ConnectResponse {
  statusCode: number;
  setHeader(name: string, value: string): void;
  end(chunk?: string): void;
}
type ConnectNext = () => void;

function headerValue(
  headers: Record<string, string | string[] | undefined>,
  name: string,
): string | null {
  const v = headers[name] ?? headers[name.toLowerCase()];
  if (Array.isArray(v)) return v[0] ?? null;
  return v ?? null;
}

/**
 * Connect/Express middleware: `app.use(tokenGateMiddleware({ config }))`.
 * `excludePaths` are served without a token (health checks, docs).
 */
export function tokenGateMiddleware(opts: {
  gate?: TokenGate;
  config?: GateConfig;
  client?: TokensClient;
  excludePaths?: Iterable<string>;
}): (req: ConnectRequest, res: ConnectResponse, next: ConnectNext) => void {
  const gate = resolveGate(opts);
  const exclude = new Set(opts.excludePaths ?? ["/health"]);
  return (req, res, next) => {
    const path = req.path ?? req.url ?? "";
    if (isExcluded(path, exclude)) {
      next();
      return;
    }
    const authorization = headerValue(req.headers, "authorization");
    void gate.authorize(authorization).then((decision) => {
      if (decision.allowed) {
        next();
        return;
      }
      writeConnectDeny(res, decision);
    });
  };
}

function writeConnectDeny(res: ConnectResponse, decision: GateDecision): void {
  const payload = JSON.stringify(decision.body ?? {});
  res.statusCode = decision.status;
  res.setHeader("content-type", "application/json");
  res.end(payload);
}

// -- Web fetch handler ------------------------------------------------

type FetchHandler = (request: Request) => Response | Promise<Response>;

/**
 * Wrap a Web `fetch` handler so every request is gated first.
 * `app = withTokenGate({ config }, handler)`.
 */
export function withTokenGate(
  opts: {
    gate?: TokenGate;
    config?: GateConfig;
    client?: TokensClient;
    excludePaths?: Iterable<string>;
  },
  handler: FetchHandler,
): FetchHandler {
  const gate = resolveGate(opts);
  const exclude = new Set(opts.excludePaths ?? ["/health"]);
  return async (request: Request): Promise<Response> => {
    const path = new URL(request.url).pathname;
    if (exclude.has(path)) {
      return handler(request);
    }
    const decision = await gate.authorize(request.headers.get("authorization"));
    if (decision.allowed) {
      return handler(request);
    }
    return Response.json(decision.body ?? {}, { status: decision.status });
  };
}
