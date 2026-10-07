import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// Integration: the real React app in jsdom talking over HTTP to a real uvicorn + FastAPI + SQLite backend.
export default defineConfig({
  plugins: [react()],
  define: { "import.meta.env.VITE_API_BASE": JSON.stringify("http://127.0.0.1:8765") },
  test: {
    environment: "jsdom", globals: true, css: false, setupFiles: ["./src/setupTests.ts"],
    include: ["src/**/*.int.test.tsx"], globalSetup: ["./src/integration/globalSetup.ts"],
    testTimeout: 60_000, hookTimeout: 60_000, fileParallelism: false,
  },
});
