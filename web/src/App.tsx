import Box from "@mui/material/Box";
import CssBaseline from "@mui/material/CssBaseline";
import Link from "@mui/material/Link";
import Stack from "@mui/material/Stack";
import { ThemeProvider, createTheme } from "@mui/material/styles";
import { BrowserRouter, Link as RouterLink, Outlet, Route, Routes } from "react-router";
import { AdminPage } from "./AdminPage";
import { StatusPage } from "./StatusPage";

const theme = createTheme({
  palette: {
    mode: "dark",
    background: { default: "#101513", paper: "#1a2420" },
    primary: { main: "#9ddec0" },
    success: { main: "#3ddc97" },
    error: { main: "#ff6b6b" },
    warning: { main: "#e6b35a" },
    divider: "#2c3a34",
    text: { primary: "#e7f2ec", secondary: "#9aada3" },
  },
  typography: {
    fontFamily: '"IBM Plex Sans", "Segoe UI", sans-serif',
    h4: { fontFamily: '"IBM Plex Mono", ui-monospace, monospace', fontWeight: 500 },
    h6: { fontFamily: '"IBM Plex Mono", ui-monospace, monospace', fontWeight: 500 },
  },
  shape: { borderRadius: 12 },
});

function Shell() {
  return (
    <>
      <Stack direction="row" spacing={2} sx={{ px: { xs: 2, md: 4 }, pt: 2 }}>
        <Link component={RouterLink} to="/" underline="hover" color="inherit">
          Live
        </Link>
        <Link component={RouterLink} to="/admin" underline="hover" color="inherit">
          Admin
        </Link>
      </Stack>
      <Box>
        <Outlet />
      </Box>
    </>
  );
}

export function App() {
  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <BrowserRouter>
        <Routes>
          <Route element={<Shell />}>
            <Route path="/" element={<StatusPage />} />
            <Route path="/admin" element={<AdminPage />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </ThemeProvider>
  );
}
