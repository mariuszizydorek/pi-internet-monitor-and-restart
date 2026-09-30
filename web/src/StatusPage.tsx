import { useEffect, useState, type ReactNode } from "react";
import Box from "@mui/material/Box";
import Chip from "@mui/material/Chip";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import {
  connectionRows,
  formatChecked,
  formatMbps,
  type LiveStatus,
  type Overall,
} from "./status";

const POLL_MS = 5000;

export function StatusPage() {
  const [status, setStatus] = useState<LiveStatus | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const response = await fetch("/api/status", { cache: "no-store" });
        if (!response.ok) {
          throw new Error(`status ${response.status}`);
        }
        const body = (await response.json()) as LiveStatus;
        if (!cancelled) {
          setStatus(body);
          setError("");
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "status unavailable");
        }
      }
    };
    void load();
    const timer = window.setInterval(() => void load(), POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, []);

  return (
    <Box sx={{ minHeight: "100vh", px: { xs: 2, md: 4 }, py: 3 }}>
      <Stack direction={{ xs: "column", sm: "row" }} spacing={2} sx={{ alignItems: { sm: "flex-end" }, mb: 3 }}>
        <Box sx={{ flex: 1 }}>
          <Typography variant="overline" sx={{ letterSpacing: "0.18em", color: "text.secondary" }}>
            Live status
          </Typography>
          <Typography variant="h4" component="h1">
            {status?.site_id ?? "Netwatch"}
          </Typography>
        </Box>
        <OverallChip overall={status?.overall ?? "unknown"} />
        <Typography variant="body2" sx={{ fontFamily: "IBM Plex Mono, ui-monospace, monospace" }}>
          Last check {formatChecked(status?.checked_at ?? null)}
        </Typography>
      </Stack>
      {error ? (
        <Typography color="warning.main" sx={{ mb: 2 }}>
          {error}
        </Typography>
      ) : null}
      <Box
        sx={{
          display: "grid",
          gap: 2,
          gridTemplateColumns: { xs: "1fr", md: "1.4fr 1fr" },
        }}
      >
        <Stack spacing={2}>
          {(status?.interfaces ?? []).map((iface) => (
            <Panel key={iface.iface} title={linkTitle(iface)} meta={formatChecked(iface.recorded_at)}>
              <Stack direction="row" spacing={1} sx={{ flexWrap: "wrap", mb: 1.5 }}>
                <Flag label="Internet" ok={iface.internet_ok} />
                <Flag label="DNS" ok={iface.dns_ok} />
                <Flag label="Ping" ok={iface.ping_ok} />
                <Flag label="Fetch" ok={iface.fetch_ok} />
                <Flag label="Link" ok={iface.carrier === null ? null : iface.carrier === 1} />
              </Stack>
              <Typography variant="body2" color="text.secondary">
                {[
                  iface.standby,
                  iface.operstate,
                  iface.ipv4,
                  iface.wifi_ssid,
                  iface.wifi_signal_dbm == null ? "" : `${iface.wifi_signal_dbm} dBm`,
                ]
                  .filter(Boolean)
                  .join(" · ") || "No link details yet"}
              </Typography>
              <Stack spacing={0.5} sx={{ mt: 1.5 }}>
                {connectionRows(iface.probes).map((row) => (
                  <Stack key={`${row.layer}-${row.name}`} direction="row" spacing={1} sx={{ alignItems: "baseline" }}>
                    <Typography variant="caption" sx={{ width: 52, color: "text.secondary" }}>
                      {row.layer}
                    </Typography>
                    <Typography variant="body2" sx={{ flex: 1, fontFamily: "IBM Plex Mono, ui-monospace, monospace" }}>
                      {row.name}
                    </Typography>
                    <Typography variant="body2" color={row.ok ? "success.main" : "error.main"}>
                      {row.ok ? "ok" : "down"}
                      {row.detail ? ` ${row.detail}` : ""}
                    </Typography>
                  </Stack>
                ))}
              </Stack>
            </Panel>
          ))}
        </Stack>
        <Stack spacing={2}>
          {status?.speedtest?.error ? <ErrorText text={status.speedtest.error} /> : null}
          <Panel title="Ookla" meta={formatChecked(status?.speeds.ookla?.recorded_at ?? null)}>
            <SpeedLines
              download={status?.speeds.ookla?.download_mbps}
              upload={status?.speeds.ookla?.upload_mbps}
              latency={status?.speeds.ookla?.latency_ms}
              error={status?.speeds.ookla?.error}
            />
          </Panel>
          <Panel title="Deco" meta={formatChecked(status?.router?.recorded_at ?? null)}>
            <Stack direction="row" spacing={1} sx={{ mb: 1 }}>
              <Flag label="Ping" ok={status?.router?.ping_ok ?? null} />
              <Flag label="API" ok={status?.router?.deco_api_ok ?? null} />
            </Stack>
            <Typography variant="body2">
              WAN {status?.router?.wan_status ?? "—"}
              {status?.router?.rtt_ms == null ? "" : ` · ${status.router.rtt_ms} ms`}
              {status?.router?.client_count == null ? "" : ` · ${status.router.client_count} clients`}
            </Typography>
            {status?.router?.error ? <ErrorText text={status.router.error} /> : null}
            <Typography variant="body2" color="text.secondary">
              {[status?.router?.model, status?.router?.firmware].filter(Boolean).join(" · ") ||
                (status?.router?.error ? "" : "No router snapshot yet")}
            </Typography>
          </Panel>
          <Panel title="Restart" meta={formatChecked(status?.restart.last_event?.recorded_at ?? null)}>
            <Typography variant="body2">
              {status?.restart.pulse_in_progress ? "Pulse in progress" : "Idle"}
              {status?.restart.last_pulse_at ? ` · last pulse ${formatChecked(status.restart.last_pulse_at)}` : ""}
            </Typography>
            <Typography variant="body2" color="text.secondary">
              {status?.restart.last_event
                ? `${status.restart.last_event.action}: ${status.restart.last_event.detail}`
                : "No restart events yet"}
            </Typography>
          </Panel>
        </Stack>
      </Box>
    </Box>
  );
}

function Panel({ title, meta, children }: { title: string; meta: string; children: ReactNode }) {
  return (
    <Box
      sx={{
        p: 2,
        border: "1px solid",
        borderColor: "divider",
        borderRadius: 2,
        bgcolor: "background.paper",
      }}
    >
      <Stack direction="row" sx={{ justifyContent: "space-between", mb: 1.5, gap: 2 }}>
        <Typography variant="h6" component="h2">
          {title}
        </Typography>
        <Typography variant="caption" color="text.secondary" sx={{ fontFamily: "IBM Plex Mono, ui-monospace, monospace" }}>
          {meta}
        </Typography>
      </Stack>
      {children}
    </Box>
  );
}

function OverallChip({ overall }: { overall: Overall }) {
  const color = overall === "online" ? "success" : overall === "offline" ? "error" : "warning";
  return <Chip label={overall} color={color} sx={{ textTransform: "uppercase", fontWeight: 600 }} />;
}

function linkTitle(iface: { iface: string; kind?: string }): string {
  if (iface.kind === "wifi") {
    return `Wi-Fi ${iface.iface}`;
  }
  if (iface.kind === "ethernet") {
    return `Ethernet ${iface.iface}`;
  }
  return iface.iface;
}

function Flag({ label, ok }: { label: string; ok: boolean | null }) {
  const color = ok === null ? "default" : ok ? "success" : "error";
  const text = ok === null ? "—" : ok ? "up" : "down";
  return <Chip size="small" label={`${label} ${text}`} color={color} variant={ok === null ? "outlined" : "filled"} />;
}

function ErrorText({ text }: { text: string }) {
  return (
    <Typography variant="body2" color="error.main" sx={{ mt: 1, whiteSpace: "pre-wrap" }}>
      {text}
    </Typography>
  );
}

function SpeedLines({
  download,
  upload,
  latency,
  error,
}: {
  download: number | null | undefined;
  upload: number | null | undefined;
  latency: number | null | undefined;
  error?: string | null;
}) {
  return (
    <>
      <Typography variant="body1" sx={{ fontFamily: "IBM Plex Mono, ui-monospace, monospace" }}>
        down {formatMbps(download ?? null)} · up {formatMbps(upload ?? null)}
        {latency == null ? "" : ` · ${latency} ms`}
      </Typography>
      {error ? <ErrorText text={error} /> : null}
    </>
  );
}
