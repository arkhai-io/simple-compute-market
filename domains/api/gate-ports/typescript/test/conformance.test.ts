/** The TypeScript middleware reproduces the shared conformance session. */

import { test } from "node:test";

import { loadSession, runSession } from "./conformanceRunner.ts";

test("recorded session matches", async () => {
  await runSession(loadSession());
});
