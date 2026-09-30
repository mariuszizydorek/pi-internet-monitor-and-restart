import { describe, expect, it } from "vitest";
import { connectionRows, formatMbps } from "./status";

describe("connectionRows", () => {
  it("lists dns, ping, and fetch results", () => {
    const rows = connectionRows({
      dns: { "google.com": true, "microsoft.com": false },
      ping: { "1.1.1.1": { ok: true, rtt_ms: 8 } },
      fetch: { google: { ok: true, status: 204, ms: 40 } },
    });
    expect(rows.map((row) => row.layer)).toEqual(["DNS", "DNS", "Ping", "Fetch"]);
    expect(rows.find((row) => row.name === "microsoft.com")?.ok).toBe(false);
    expect(rows.find((row) => row.name === "google")?.detail).toBe("204 · 40 ms");
  });
});

describe("formatMbps", () => {
  it("renders a missing speed as a dash", () => {
    expect(formatMbps(null)).toBe("—");
    expect(formatMbps(90.5)).toBe("90.5 Mbps");
  });
});
