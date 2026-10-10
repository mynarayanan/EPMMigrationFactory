import { emptyEnv, toPayload, validateEnv, validateProject } from "./validation";
import type { EnvInput, ProjectInput } from "./types";

const SUF = [".oraclecloud.com"];
const live = (o: Partial<EnvInput> = {}): EnvInput => ({ ...emptyEnv(""), connector: "live", url: "https://acme.epm.us-phoenix-1.ocs.oraclecloud.com",
  user: "svc.migration", password_file_env: "EPM_SOURCE_PWF", ...o });

test("a valid live environment has no errors", () => expect(validateEnv(live(), SUF)).toEqual({}));
test("simulated environments only need a profile", () => {
  expect(validateEnv(emptyEnv("clean"), SUF)).toEqual({}); expect(validateEnv({ ...emptyEnv(""), connector: "mock" }, SUF)).toHaveProperty("profile");
});

test.each([
  ["http://acme.oraclecloud.com", "https"], ["https://10.0.0.5", "IP"], ["https://169.254.169.254", "IP"], ["https://localhost", "IP"],
  ["https://evil.example.com", "must end with"], ["https://u:p@acme.oraclecloud.com", "credentials"], ["https://acme.oraclecloud.com:8443", "port"],
  ["not a url", "full environment URL"], ["", "full environment URL"], ["https://acme.oraclecloud.com.evil.com", "must end with"],
])("rejects URL %s", (url, msg) => expect(validateEnv(live({ url }), SUF).url).toContain(msg));

test.each(["DATABASE_URL", "JWT_SECRET", "epm_lower", "EPM_", "EPM_A B", ""])("rejects credential variable name %j", (n) =>
  expect(validateEnv(live({ password_file_env: n }), SUF)).toHaveProperty("password_file_env"));

test("rejects bad service account names", () => {
  expect(validateEnv(live({ user: "" }), SUF)).toHaveProperty("user"); expect(validateEnv(live({ user: "a b;rm" }), SUF)).toHaveProperty("user");
});

const proj = (o: Partial<ProjectInput> = {}): ProjectInput => ({ name: "P", client: "", owner: "", planned_date: "", pattern: "cloud_to_cloud",
  source: emptyEnv("clean"), target: emptyEnv("empty_target"), settings: {}, ...o });

test("project errors are keyed by side.field", () => {
  const e = validateProject(proj({ name: " ", source: live({ url: "http://x" }) }), SUF);
  expect(Object.keys(e).sort()).toEqual(["name", "source.url"]);
});

test("payload drops fields irrelevant to the chosen connector", () => {
  const out = toPayload(proj({ source: live({ profile: "clean", url: "  https://a.oraclecloud.com " }), target: { ...emptyEnv("empty_target"), url: "https://leftover", user: "x" } }));
  expect(out.source.profile).toBe(""); expect(out.source.url).toBe("https://a.oraclecloud.com");
  expect(out.target).toMatchObject({ connector: "mock", profile: "empty_target", url: "", user: "", password_file_env: "" });
});
