import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App from "../App";
import { setToken } from "../api";

const PW = "int-test-pw"; const T = { timeout: 30_000 };
beforeEach(() => { setToken(null); sessionStorage.clear(); window.history.pushState({}, "", "/"); });

async function signIn(user: string) {
  const ux = userEvent.setup();
  await ux.type(await screen.findByLabelText("Username"), user);
  await ux.type(screen.getByLabelText("Password"), PW);
  await ux.click(screen.getByRole("button", { name: "Sign in" }));
  await screen.findByRole("button", { name: "Sign out" }, T);
  return ux;
}

test("operator creates a simulated project through the form and lands on it", async () => {
  render(<App />); const ux = await signIn("olivia");
  await ux.click(await screen.findByRole("link", { name: "New project" }));
  await ux.type(await screen.findByLabelText("Project name"), "Acme Planning migration");
  await ux.type(screen.getByLabelText("Client / business unit"), "Acme");
  await ux.click(screen.getByRole("button", { name: "Create project" }));
  expect(await screen.findByRole("heading", { name: "Acme Planning migration" }, T)).toBeInTheDocument();
  await ux.click(screen.getByRole("tab", { name: /environments/i }));
  const cfg = await screen.findByRole("table", { name: "Environment configuration" }, T);
  expect(within(cfg).getAllByText("Simulated")).toHaveLength(2);
});

test("client-side validation blocks a bad live environment before any request is sent", async () => {
  render(<App />); const ux = await signIn("olivia");
  await ux.click(await screen.findByRole("link", { name: "New project" }));
  await ux.type(await screen.findByLabelText("Project name"), "Bad live");
  await ux.selectOptions(screen.getByLabelText("Connection type", { selector: "#source-connector" }), "live");
  await ux.type(screen.getByLabelText("Environment URL"), "http://169.254.169.254");
  await ux.type(screen.getByLabelText("Service account"), "svc");
  await ux.type(screen.getByLabelText("Password-file variable name"), "DATABASE_URL");
  await ux.click(screen.getByRole("button", { name: "Create project" }));
  const alerts = (await screen.findAllByRole("alert")).map((a) => a.textContent);
  expect(alerts.join(" | ")).toMatch(/https/); expect(alerts.join(" | ")).toMatch(/EPM_ prefix/);
  expect(screen.getByRole("form", { name: "Create migration project" })).toBeInTheDocument();   // still on the form
  expect(screen.getByText(/Live connections are not proven yet/)).toBeInTheDocument();
});

test("a valid live environment is stored as a credential REFERENCE, never a secret", async () => {
  render(<App />); const ux = await signIn("olivia");
  await ux.click(await screen.findByRole("link", { name: "New project" }));
  await ux.type(await screen.findByLabelText("Project name"), "Live pilot");
  await ux.selectOptions(screen.getByLabelText("Connection type", { selector: "#source-connector" }), "live");
  await ux.type(screen.getByLabelText("Environment URL"), "https://acme-dev.epm.us-phoenix-1.ocs.oraclecloud.com");
  await ux.type(screen.getByLabelText("Service account"), "svc.migration");
  await ux.type(screen.getByLabelText("Password-file variable name"), "EPM_SOURCE_PWF");
  await ux.click(screen.getByRole("button", { name: "Create project" }));
  await screen.findByRole("heading", { name: "Live pilot" }, T);
  await ux.click(screen.getByRole("tab", { name: /environments/i }));
  const cfg = await screen.findByRole("table", { name: "Environment configuration" }, T);
  expect(within(cfg).getByText("Oracle Cloud EPM (live)")).toBeInTheDocument();
  expect(within(cfg).getByText("env: EPM_SOURCE_PWF")).toBeInTheDocument();
  expect(within(cfg).getByText("https://acme-dev.epm.us-phoenix-1.ocs.oraclecloud.com")).toBeInTheDocument();
});

test("the server re-checks independently of the form: crafted requests that bypass the UI are refused", async () => {
  render(<App />); await signIn("olivia");
  const { api, ApiError } = await import("../api");
  const base = { name: "crafted", client: "", owner: "", planned_date: "", pattern: "cloud_to_cloud", settings: {},
    target: { connector: "mock", url: "", version: "", profile: "empty_target", user: "", identity_domain: "", password_file_env: "" } } as const;
  const src = { connector: "live", url: "https://acme.oraclecloud.com", version: "", profile: "", user: "svc", identity_domain: "", password_file_env: "EPM_X" } as const;
  const tries = [{ ...src, url: "https://169.254.169.254" }, { ...src, url: "https://evil.example.com" }, { ...src, password_file_env: "JWT_SECRET" }];
  for (const s of tries) {
    const err = await api.createProject({ ...base, source: { ...s } } as never).catch((e) => e);
    expect(err).toBeInstanceOf(ApiError); expect((err as InstanceType<typeof ApiError>).status).toBe(422);
  }
  const ok = await api.createProject({ ...base, name: "crafted-ok", source: { ...src } } as never);
  expect(ok.source).toMatchObject({ connector: "live", password_file_env: "EPM_X" });
});

test("approvers get no New project button, and the route itself refuses them", async () => {
  window.history.pushState({}, "", "/projects/new");        // deep link, as if bookmarked
  render(<App />); await signIn("alan");
  expect(await screen.findByText("Your role cannot create projects.", {}, T)).toBeInTheDocument();
  expect(screen.queryByRole("form", { name: "Create migration project" })).toBeNull();
  window.history.pushState({}, "", "/");
});
