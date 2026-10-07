import { spawn, type ChildProcess } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

let proc: ChildProcess; let dir: string;
export async function setup() {
  dir = mkdtempSync(path.join(tmpdir(), "epmwb-int-"));
  const backend = path.resolve(__dirname, "../../../backend");
  proc = spawn("python3", ["-m", "uvicorn", "api.main:app_factory", "--factory", "--port", "8765", "--log-level", "warning"], {
    cwd: backend,
    env: { ...process.env, DATABASE_URL: `sqlite:///${dir}/int.db`, EPM_MOCK_STATE_DIR: `${dir}/mock`, DEV_PASSWORD: "int-test-pw",
      CORS_ORIGINS: "http://localhost:3000", AUTH_MODE: "dev", APP_ENV: "development" },
    stdio: "inherit",
  });
  for (let i = 0; i < 100; i++) {
    try { if ((await fetch("http://127.0.0.1:8765/healthz")).ok) return; } catch { /* not up yet */ }
    await new Promise((r) => setTimeout(r, 150));
  }
  throw new Error("backend did not start");
}
export async function teardown() { proc?.kill(); rmSync(dir, { recursive: true, force: true }); }
