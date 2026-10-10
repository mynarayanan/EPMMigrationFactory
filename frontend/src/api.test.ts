import { api, ApiError, getToken, setToken, setUnauthorizedHandler } from "./api";

const ok = (body: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }));
afterEach(() => { vi.restoreAllMocks(); setToken(null); });

test("sends bearer token and JSON body", async () => {
  setToken("tok");
  const f = vi.spyOn(globalThis, "fetch").mockImplementation(() => ok({ id: 1 }));
  await api.demo("clean");
  const [url, init] = f.mock.calls[0]; const h = new Headers((init as RequestInit).headers);
  expect(String(url)).toBe("/api/projects/demo");
  expect(h.get("Authorization")).toBe("Bearer tok"); expect(h.get("Content-Type")).toBe("application/json");
  expect((init as RequestInit).body).toBe(JSON.stringify({ scenario: "clean" }));
});

test("surfaces server detail (string and validation-list forms) as ApiError", async () => {
  vi.spyOn(globalThis, "fetch").mockImplementationOnce(() => ok({ detail: "Approval required" }, 409))
    .mockImplementationOnce(() => ok({ detail: [{ msg: "field required" }, { msg: "bad url" }] }, 422));
  await expect(api.plan(1)).rejects.toMatchObject({ status: 409, message: "Approval required" });
  await expect(api.plan(1)).rejects.toMatchObject({ status: 422, message: "field required; bad url" });
});

test("401 clears the token and triggers the unauthorized handler", async () => {
  setToken("stale"); const handler = vi.fn(); setUnauthorizedHandler(handler);
  vi.spyOn(globalThis, "fetch").mockImplementation(() => ok({ detail: "expired" }, 401));
  await expect(api.projects()).rejects.toBeInstanceOf(ApiError);
  expect(getToken()).toBeNull(); expect(handler).toHaveBeenCalledOnce();
});

test("network/CORS failure explains where it tried to connect", async () => {
  vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("Failed to fetch"));
  await expect(api.config()).rejects.toMatchObject({ status: 0, message: expect.stringContaining("Cannot reach the API") });
});
