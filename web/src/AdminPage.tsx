import { useEffect, useState } from "react";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Chip from "@mui/material/Chip";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";

type Check = {
  name: string;
  ok: boolean;
  url?: string;
  status?: number;
  detail: string;
};

type Report = {
  checks: Check[];
  error?: string;
};

type ActionNote = {
  title: string;
  detail: string;
};

export function AdminPage() {
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<ActionNote | null>(null);
  const [minutes, setMinutes] = useState("60");

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const response = await fetch("/api/speedtest/schedule", { cache: "no-store" });
        if (!response.ok) {
          return;
        }
        const body = (await response.json()) as { interval_minutes?: number };
        if (!cancelled && typeof body.interval_minutes === "number") {
          setMinutes(String(body.interval_minutes));
        }
      } catch {
        // The field keeps the one-hour default until the next successful load.
      }
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  const saveSchedule = async () => {
    const intervalMinutes = Number(minutes);
    if (!Number.isInteger(intervalMinutes)) {
      setError("Enter a whole number of minutes");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const response = await fetch("/api/speedtest/schedule", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ interval_minutes: intervalMinutes }),
      });
      const body = (await response.json()) as { error?: string; interval_minutes?: number };
      if (!response.ok) {
        throw new Error(body.error || `status ${response.status}`);
      }
      setMinutes(String(body.interval_minutes ?? intervalMinutes));
      setNote({ title: "Speed test schedule", detail: `every ${body.interval_minutes} minutes` });
    } catch (err) {
      setError(err instanceof Error ? err.message : "could not save the schedule");
    } finally {
      setBusy(false);
    }
  };

  const testConnectivity = async () => {
    setBusy(true);
    setError("");
    try {
      const response = await fetch("/api/connectivity", { cache: "no-store" });
      const body = (await response.json()) as Report;
      if (!response.ok) {
        throw new Error(body.error || `status ${response.status}`);
      }
      setReport(body);
    } catch (err) {
      setError(err instanceof Error ? err.message : "connectivity check failed");
    } finally {
      setBusy(false);
    }
  };

  const runSpeedTest = async () => {
    setBusy(true);
    setError("");
    try {
      const response = await fetch("/api/speedtest", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ source: "ookla" }),
      });
      const body = (await response.json()) as { error?: string; source?: string };
      if (!response.ok) {
        throw new Error(body.error || `status ${response.status}`);
      }
      setNote({ title: "Speed test", detail: `Ookla queued (${body.source ?? "ookla"})` });
    } catch (err) {
      setError(err instanceof Error ? err.message : "speed test request failed");
    } finally {
      setBusy(false);
    }
  };

  const simulateRestart = async () => {
    setBusy(true);
    setError("");
    try {
      const response = await fetch("/api/restart/simulate", { method: "POST" });
      const body = (await response.json()) as { error?: string; policy?: string; detail?: string };
      if (!response.ok) {
        throw new Error(body.error || `status ${response.status}`);
      }
      setNote({
        title: "Simulated restart",
        detail: body.detail || `policy ${body.policy ?? "unknown"}`,
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "restart simulation failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Box sx={{ px: { xs: 2, md: 4 }, py: 3, maxWidth: 820 }}>
      <Typography variant="overline" sx={{ letterSpacing: "0.18em", color: "text.secondary" }}>
        Admin
      </Typography>
      <Typography variant="h4" component="h1" sx={{ mb: 1 }}>
        Connectivity
      </Typography>
      <Typography color="text.secondary" sx={{ mb: 3 }}>
        This checks the local database and whether the Supabase service role key can read
        interface_samples. The Grafana screen error is the Infinity plugin asking for
        react/jsx-runtime, which Grafana 11.3 does not provide. This stack runs Grafana 13.2.2
        at http://localhost:16080.
      </Typography>
      <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} sx={{ mb: 2, alignItems: { sm: "center" } }}>
        <TextField
          label="Speed test every"
          type="number"
          value={minutes}
          onChange={(event) => setMinutes(event.target.value)}
          slotProps={{ htmlInput: { min: 1, max: 1440, step: 1 } }}
          sx={{ width: { xs: "100%", sm: 180 } }}
        />
        <Typography color="text.secondary">minutes</Typography>
        <Button variant="outlined" onClick={() => void saveSchedule()} disabled={busy}>
          Save interval
        </Button>
      </Stack>
      <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} sx={{ mb: 1 }}>
        <Button variant="contained" onClick={() => void testConnectivity()} disabled={busy}>
          {busy ? "Working" : "Test connectivity"}
        </Button>
        <Button variant="outlined" onClick={() => void runSpeedTest()} disabled={busy}>
          Run speed test
        </Button>
        <Button variant="outlined" onClick={() => void simulateRestart()} disabled={busy}>
          Simulate restart
        </Button>
      </Stack>
      {note ? (
        <Typography sx={{ mt: 2 }}>
          {note.title}: {note.detail}
        </Typography>
      ) : null}
      {error ? (
        <Typography color="warning.main" sx={{ mt: 2 }}>
          {error}
        </Typography>
      ) : null}
      <Stack spacing={2} sx={{ mt: 3 }}>
        {(report?.checks ?? []).map((check) => (
          <Box
            key={check.name}
            sx={{ p: 2, border: "1px solid", borderColor: "divider", borderRadius: 2, bgcolor: "background.paper" }}
          >
            <Stack direction="row" spacing={1} sx={{ alignItems: "center", mb: 1 }}>
              <Typography variant="h6" component="h2" sx={{ flex: 1 }}>
                {check.name}
              </Typography>
              <Chip size="small" label={check.ok ? "ok" : "failed"} color={check.ok ? "success" : "error"} />
            </Stack>
            {check.url ? (
              <Typography variant="body2" sx={{ fontFamily: "IBM Plex Mono, ui-monospace, monospace", mb: 0.5 }}>
                {check.url}
                {check.status == null ? "" : ` · HTTP ${check.status}`}
              </Typography>
            ) : null}
            <Typography variant="body2" color="text.secondary">
              {check.detail}
            </Typography>
          </Box>
        ))}
      </Stack>
    </Box>
  );
}
