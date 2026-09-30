export type Freshness = "fresh" | "stale" | "unknown";
export type Overall = "online" | "offline" | "stale" | "unknown";

export type Probes = {
  dns?: Record<string, boolean>;
  ping?: Record<string, { ok?: boolean; rtt_ms?: number | null }>;
  fetch?: Record<string, { ok?: boolean; status?: number | null; ms?: number | null }>;
};

export type InterfaceStatus = {
  iface: string;
  kind?: "ethernet" | "wifi" | string;
  standby?: string | null;
  recorded_at: string | null;
  freshness: Freshness;
  carrier: number | null;
  operstate: string | null;
  wifi_ssid: string | null;
  wifi_signal_dbm: number | null;
  ipv4: string | null;
  dns_ok: boolean | null;
  ping_ok: boolean | null;
  fetch_ok: boolean | null;
  internet_ok: boolean | null;
  probes: Probes;
};

export type SpeedStatus = {
  source: string;
  recorded_at: string;
  download_mbps: number | null;
  upload_mbps: number | null;
  latency_ms: number | null;
  error?: string | null;
};

export type LiveStatus = {
  site_id: string;
  overall: Overall;
  checked_at: string | null;
  interfaces: InterfaceStatus[];
  router: {
    recorded_at: string;
    freshness: Freshness;
    gateway_ip: string | null;
    ping_ok: boolean | null;
    rtt_ms: number | null;
    deco_api_ok: boolean | null;
    wan_status: string | null;
    client_count: number | null;
    cpu_usage: number | null;
    mem_usage: number | null;
    model: string | null;
    firmware: string | null;
    error?: string | null;
  } | null;
  speedtest?: {
    running: string | null;
    requested: string | null;
    error: string | null;
  };
  speeds: {
    ookla: SpeedStatus | null;
  };
  restart: {
    last_pulse_at: string | null;
    pulse_in_progress: boolean;
    last_event: { recorded_at: string; action: string; detail: string } | null;
  };
};

export type ConnectionRow = {
  layer: string;
  name: string;
  ok: boolean;
  detail: string;
};

export function connectionRows(probes: Probes): ConnectionRow[] {
  const rows: ConnectionRow[] = [];
  for (const [name, ok] of Object.entries(probes.dns ?? {})) {
    rows.push({ layer: "DNS", name, ok: Boolean(ok), detail: ok ? "resolved" : "failed" });
  }
  for (const [name, hit] of Object.entries(probes.ping ?? {})) {
    rows.push({
      layer: "Ping",
      name,
      ok: Boolean(hit.ok),
      detail: hit.rtt_ms == null ? "" : `${hit.rtt_ms} ms`,
    });
  }
  for (const [name, hit] of Object.entries(probes.fetch ?? {})) {
    const bits = [hit.status == null ? "" : String(hit.status), hit.ms == null ? "" : `${hit.ms} ms`].filter(Boolean);
    rows.push({ layer: "Fetch", name, ok: Boolean(hit.ok), detail: bits.join(" · ") });
  }
  return rows;
}

export function formatMbps(value: number | null | undefined): string {
  if (value == null) {
    return "—";
  }
  return `${value.toFixed(1)} Mbps`;
}

export function formatChecked(value: string | null): string {
  if (!value) {
    return "not checked yet";
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return parsed.toLocaleString();
}
