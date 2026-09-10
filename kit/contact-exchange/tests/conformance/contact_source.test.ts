import { describe, expect, test } from "bun:test";
import { createHash } from "node:crypto";
import vectors from "../../src/market_contact_exchange/fixtures/contact_source_v1.json";

// Python's existing contact blank predicate, frozen as explicit scalar values.
const blank = /^[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]*$/u;
const surrogate = /[\ud800-\udfff]/u;
function acceptsText(input: unknown): boolean {
  if (typeof input !== "object" || input === null || Array.isArray(input)) return false;
  const value = input as Record<string, unknown>;
  if (Object.keys(value).length !== 1 || typeof value.text !== "string") return false;
  return [...value.text].length <= 512 && !blank.test(value.text) && !surrogate.test(value.text);
}

function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value !== null && typeof value === "object") {
    const record = value as Record<string, unknown>;
    return `{${Object.keys(record).sort().map(key => `${JSON.stringify(key)}:${canonical(record[key])}`).join(",")}}`;
  }
  return JSON.stringify(value);
}

describe("contact source vectors", () => {
  for (const vector of vectors.cases) {
    if (vector.carrier === "contact_text") {
      test(`${vector.id}: scalar and strict-key parity`, () => {
        expect(acceptsText(vector.input)).toBe(vector.accepted);
      });
    }
    if (vector.accepted) {
      test(`${vector.id}: canonical UTF-8 and digest parity`, () => {
        const bytes = Buffer.from(canonical(vector.serialized), "utf8");
        expect(bytes.toString("hex")).toBe(vector.jcs_utf8_hex);
        expect(createHash("sha256").update(bytes).digest("hex")).toBe(vector.sha256);
      });
    }
  }
});
