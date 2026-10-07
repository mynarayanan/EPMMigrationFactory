import { render, screen, within, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App from "./../App";
import { setToken } from "../api";

const PW = "int-test-pw";
const T = { timeout: 30_000 };

async function signIn(user: string) {
  const ux = userEvent.setup();
  await ux.type(await screen.findByLabelText("Username"), user);
  await ux.type(screen.getByLabelText("Password"), PW);
  await ux.click(screen.getByRole("button", { name: "Sign in" }));
  await screen.findByRole("button", { name: "Sign out" }, T);
  return ux;
}
async function signOut(ux: ReturnType<typeof userEvent.setup>) { await ux.click(screen.getByRole("button", { name: "Sign out" })); await screen.findByLabelText("Username"); }
async function openTab(ux: ReturnType<typeof userEvent.setup>, name: RegExp) { await ux.click(await screen.findByRole("tab", { name })); }
const ledger = () => within(screen.getByRole("list", { name: "Migration steps" }));
const step = (name: string) => ledger().getByText(name).closest("li") as HTMLElement;

/** After re-login the router is still on the project URL (deep link preserved); open it from the list otherwise. */
async function openDemo(ux: ReturnType<typeof userEvent.setup>) {
  // wait until either the project page (deep link kept) or the portfolio list has rendered
  const either = await waitFor(() => {
    const tab = screen.queryByRole("tab", { name: /readiness/i });
    const link = screen.queryByRole("link", { name: /Demo clean/ });
    if (!tab && !link) throw new Error("neither project page nor list yet");
    return { tab, link };
  }, T);
  if (!either.tab) await ux.click(either.link!);
  await screen.findByRole("tab", { name: /readiness/i }, T);
}

beforeEach(() => { setToken(null); sessionStorage.clear(); window.history.pushState({}, "", "/"); });

test("bad credentials are rejected with a visible error", async () => {
  render(<App />);
  const ux = userEvent.setup();
  await ux.type(await screen.findByLabelText("Username"), "olivia");
  await ux.type(screen.getByLabelText("Password"), "wrong");
  await ux.click(screen.getByRole("button", { name: "Sign in" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(/invalid username or password/i);
});

test("full migration through the UI: operator runs, two different approvers approve, project completes", async () => {
  const { unmount } = render(<App />);
  let ux = await signIn("olivia");

  await ux.click(await screen.findByRole("button", { name: "New demo (clean)" }));
  await ux.click(await screen.findByRole("link", { name: /Demo clean/ }, T));
  expect(await screen.findByText((_, el) => el?.className === "score" && !!el.textContent?.startsWith("100"), {}, T)).toBeInTheDocument();
  expect(screen.getByText("Execution gate").nextElementSibling).toHaveTextContent("OPEN");

  await openTab(ux, /plan & execution/i);
  await ux.click(await screen.findByRole("button", { name: "Generate migration plan" }));
  await screen.findByRole("list", { name: "Migration steps" }, T);
  // operator may not approve
  await ux.click(screen.getByRole("button", { name: "Run until blocked" }));
  await screen.findByText(/Stopped: Approval required for step 'import_snapshot'/, {}, T);
  await waitFor(() => expect(within(step("Import snapshot into target")).getByRole("button", { name: "Approve" })).toBeDisabled(), T);
  await signOut(ux);

  // approver #1 approves the import
  ux = await signIn("alan");
  await openDemo(ux);
  await openTab(ux, /plan & execution/i);
  expect(await screen.findByRole("button", { name: "Run until blocked" })).toBeDisabled();   // approver cannot execute
  await waitFor(() => expect(within(step("Import snapshot into target")).getByRole("button", { name: "Approve" })).toBeEnabled(), T);
  await ux.click(within(step("Import snapshot into target")).getByRole("button", { name: "Approve" }));
  await waitFor(() => expect(within(step("Import snapshot into target")).queryByRole("button", { name: "Approve" })).toBeNull(), T);
  await signOut(ux);

  // operator continues: import + validations, then stops at sign-off
  ux = await signIn("olivia");
  await openDemo(ux);
  await openTab(ux, /plan & execution/i);
  await ux.click(await screen.findByRole("button", { name: "Run until blocked" }));
  await waitFor(() => expect(within(step("Business reconciliation (control totals)")).getByText("COMPLETE")).toBeInTheDocument(), T);
  await signOut(ux);

  // approver #2 signs off
  ux = await signIn("amy");
  await openDemo(ux);
  await openTab(ux, /plan & execution/i);
  await screen.findByRole("list", { name: "Migration steps" }, T);
  await waitFor(() => expect(within(step("Business sign-off")).getByRole("button", { name: "Approve" })).toBeEnabled(), T);
  await ux.click(within(step("Business sign-off")).getByRole("button", { name: "Approve" }));
  await signOut(ux);

  ux = await signIn("olivia");
  await openDemo(ux);
  await openTab(ux, /plan & execution/i);
  await ux.click(await screen.findByRole("button", { name: "Run until blocked" }));
  await waitFor(() => expect(within(step("Business sign-off")).getByText("COMPLETE")).toBeInTheDocument(), T);

  // rail fully done, validation green, audit intact
  await waitFor(() => expect(screen.getByRole("list", { name: "Migration lifecycle" }).querySelectorAll("li.DONE")).toHaveLength(7), T);
  await openTab(ux, /validation/i);
  expect(await screen.findByText(/checks passed/, {}, T)).toHaveTextContent(/16 \/ 16/);
  await openTab(ux, /evidence/i);
  expect(await screen.findByText("Audit chain intact", {}, T)).toBeInTheDocument();
  unmount();
});

test("a RED project shows the blocking findings and refuses to plan", async () => {
  render(<App />);
  const ux = await signIn("olivia");
  await ux.click(await screen.findByRole("button", { name: "New demo (with issues)" }));
  await ux.click(await screen.findByRole("link", { name: /Demo issues/ }, T));
  expect((await screen.findAllByText(/Critical gate failed/, {}, T)).length).toBeGreaterThanOrEqual(2);
  expect(screen.getByText("Execution gate").nextElementSibling).toHaveTextContent("BLOCKED");
  await openTab(ux, /compatibility/i);
  expect(await screen.findByText("LegacyERPBridge", {}, T)).toBeInTheDocument();
  await openTab(ux, /plan & execution/i);
  await ux.click(await screen.findByRole("button", { name: "Generate migration plan" }));
  expect(await screen.findAllByText(/blocked by readiness gate/i, {}, T)).not.toHaveLength(0);
});
