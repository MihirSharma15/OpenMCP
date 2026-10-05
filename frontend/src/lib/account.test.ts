import { afterEach, describe, expect, it, vi } from "vitest";
import { AccountApiError, accountRequest, checkoutIntent, clearCheckoutIntent, parseAllowance, readCheckoutIntent, returnedCheckoutMatches, safeExternalUrl, topUpPending, type TopUp } from "./account";
import { accountQuery, allowedAccountPath, apiOrigin, sameOriginMutation } from "./account-proxy";

afterEach(() => vi.unstubAllGlobals());

describe("account proxy boundary", () => {
  it("permits human account operations and rejects arbitrary upstream paths", () => {
    expect(allowedAccountPath("POST", ["agents", "agt_example", "credentials", "cred_example", "revoke"])).toBe("agents/agt_example/credentials/cred_example/revoke");
    expect(allowedAccountPath("GET", ["wallet", "top-ups", "top_example"])).toBe("wallet/top-ups/top_example");
    for (const path of [["webhooks", "stripe"], ["execute"], ["discover"], ["wallet", "credit"], ["..", "admin"], ["agents", "a/credentials"], ["agents", "%2e%2e"], ["agents", "a?token=secret"]]) {
      expect(allowedAccountPath("POST", path)).toBeNull();
    }
    expect(allowedAccountPath("DELETE", ["agents"])).toBeNull();
  });
  it("rejects missing, malformed, and cross-site mutation origins", () => {
    expect(sameOriginMutation("https://wallet.example", "https://wallet.example/")).toBe(true);
    for (const value of [null, "null", "https://wallet.example.attacker.test", "https://attacker.test", "https://wallet.example/path", "https://wallet.example:444"]) {
      expect(sameOriginMutation(value, "https://wallet.example")).toBe(false);
    }
  });
  it("only forwards cursor/filter fields, never account identity or destination", () => {
    const params = new URLSearchParams("limit=20&cursor=next&type=refund&status=completed&account_id=other&url=https://attacker.test&token=secret");
    expect(accountQuery("transactions", params)).toBe("limit=20&cursor=next&type=refund&status=completed");
    expect(accountQuery("wallet", params)).toBe("");
  });
  it("accepts trusted HTTPS or local HTTP origins without embedded credentials", () => {
    expect(apiOrigin("https://api.example/")).toBe("https://api.example");
    expect(apiOrigin("http://127.0.0.1:8000")).toBe("http://127.0.0.1:8000");
    for (const value of [undefined, "http://remote.example", "https://user:secret@api.example", "https://api.example/v1", "https://api.example?secret=x", "javascript:alert(1)"]) expect(apiOrigin(value)).toBeNull();
  });
});

describe("wallet UI money and navigation safety", () => {
  it("preserves exact cents and enforces the backend grant range", () => {
    expect(parseAllowance("2.40")).toBe(240); expect(parseAllowance("0.01")).toBe(1); expect(parseAllowance("10000")).toBe(1_000_000);
    for (const value of ["0", "-1", "1.001", "1e2", "Infinity", "10000.01", "", "999999999999999999999"]) expect(parseAllowance(value)).toBeNull();
  });
  it("retries a checkout under one key but creates a fresh same-amount intent after credited return", () => {
    const uuid = vi.fn().mockReturnValueOnce("first").mockReturnValueOnce("second");
    let intent: { amount: number; key: string } | null = checkoutIntent(null, 1000, uuid);
    expect(checkoutIntent(intent, 1000, uuid)).toBe(intent);
    for (const status of ["creating", "awaiting_payment", "processing"] as TopUp["status"][]) {
      expect(clearCheckoutIntent(status)).toBe(false); expect(topUpPending(status)).toBe(true);
    }
    // A canceled return is only navigation: pending server state retains the key.
    expect(checkoutIntent(intent, 1000, uuid).key).toBe("first");
    if (clearCheckoutIntent("credited")) intent = null;
    expect(checkoutIntent(intent, 1000, uuid).key).toBe("second");
    expect(uuid).toHaveBeenCalledTimes(2);
  });
  it("a changed amount starts another intended checkout, and terminal failures permit retry", () => {
    expect(checkoutIntent({ amount: 500, key: "old" }, 1000, () => "new")).toEqual({ amount: 1000, key: "new" });
    expect(clearCheckoutIntent("failed")).toBe(true); expect(clearCheckoutIntent("expired")).toBe(true);
  });
  it("an old credited return cannot discard a newer pending checkout's retry key", () => {
    const intent = { amount: 1000, key: "retry-key", topUpId: "top_current" };
    expect(returnedCheckoutMatches(intent, { id: "top_old", status: "credited" })).toBe(false);
    expect(returnedCheckoutMatches(intent, { id: "top_current", status: "processing" })).toBe(false);
    expect(returnedCheckoutMatches(intent, { id: "top_current", status: "awaiting_payment" })).toBe(false);
    expect(returnedCheckoutMatches(intent, { id: "top_current", status: "credited" })).toBe(true);
    expect(returnedCheckoutMatches(intent, { id: "top_current", status: "expired" })).toBe(true);
    expect(readCheckoutIntent(JSON.stringify(intent))).toEqual(intent);
    expect(readCheckoutIntent("broken JSON")).toBeNull();
    expect(readCheckoutIntent('{"amount":1000,"key":"invalid key"}')).toBeNull();
  });
  it("blocks script URLs and impersonated Stripe checkout origins", () => {
    expect(safeExternalUrl("https://checkout.stripe.com/c/pay/test", true)).toBe("https://checkout.stripe.com/c/pay/test");
    for (const value of ["javascript:alert(1)", "data:text/html,test", "http://checkout.stripe.com", "https://checkout.stripe.com.attacker.test", "https://user:secret@checkout.stripe.com/c/pay/test"]) expect(safeExternalUrl(value, true)).toBeNull();
    expect(safeExternalUrl("https://explore.tempo.xyz/tx/reference")).toBeTruthy();
  });
});

describe("browser API client", () => {
  it("uses same-origin sessions and no-store, carries idempotency, and never attaches machine or demo tokens", async () => {
    const fetcher = vi.fn().mockResolvedValue(Response.json({ id: "top_test" })); vi.stubGlobal("fetch", fetcher);
    await accountRequest("/wallet/top-ups", { method: "POST", body: { amount_cents: 1000 }, key: "intended-payment" });
    expect(fetcher).toHaveBeenCalledWith("/api/openmcp/wallet/top-ups", expect.objectContaining({ method: "POST", cache: "no-store", credentials: "same-origin", body: '{"amount_cents":1000}' }));
    expect(fetcher.mock.calls[0][1].headers).toEqual({ "Content-Type": "application/json", "Idempotency-Key": "intended-payment" });
  });
  it("retains actionable unauthorized and restricted-account errors rather than returning zero balances", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({ error: { code: "unauthorized", message: "Please sign in again.", retryable: false }, request_id: "req_1" }, { status: 401 })));
    await expect(accountRequest("/wallet")).rejects.toMatchObject({ name: "AccountApiError", code: "unauthorized", status: 401, retryable: false, requestId: "req_1" });
  });
  it("network failures and unreadable successful responses remain errors", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("network failure")));
    await expect(accountRequest("/wallet")).rejects.toBeInstanceOf(AccountApiError);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("invalid")));
    await expect(accountRequest("/wallet")).rejects.toMatchObject({ code: "invalid_response" });
  });
});
