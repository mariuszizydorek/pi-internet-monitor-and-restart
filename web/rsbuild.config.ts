import { defineConfig } from "@rsbuild/core";
import { pluginReact } from "@rsbuild/plugin-react";

export default defineConfig({
  plugins: [pluginReact()],
  source: {
    entry: {
      index: "./src/index.tsx",
    },
  },
  html: {
    title: "Netwatch",
  },
  server: {
    port: 16083,
    strictPort: true,
    proxy: {
      "/api": "http://127.0.0.1:16081",
    },
  },
});
