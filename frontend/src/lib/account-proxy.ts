const identifier = "[A-Za-z0-9_-]{1,160}";
const routes: Record<string, RegExp[]> = {
  GET: [ /^me$/, /^wallet$/, /^agents$/, /^transactions$/, new RegExp(`^wallet/top-ups/${identifier}$`), new RegExp(`^transactions/${identifier}$`), new RegExp(`^executions/${identifier}$`) ],
  POST: [ /^me\/bootstrap$/, /^wallet\/top-ups$/, /^agents$/, new RegExp(`^agents/${identifier}/credentials$`), new RegExp(`^agents/${identifier}/credentials/${identifier}/revoke$`) ],
};

export function allowedAccountPath(method: string, segments: string[]): string | null {
  // Reject decoded separators, traversal, and encoded second-pass traversal.
  if (segments.some(segment => !/^[A-Za-z0-9_-]+$/.test(segment))) return null;
  const path = segments.join("/");
  return routes[method]?.some(route => route.test(path)) ? path : null;
}
export function accountQuery(path: string, params: URLSearchParams): string {
  const allowed = path === "transactions" ? ["limit", "cursor", "type", "status"] : path === "agents" ? ["limit", "cursor"] : [];
  const result = new URLSearchParams();
  for (const key of allowed) {
    const value = params.get(key);
    if (value && value.length <= 500) result.set(key, value);
  }
  return result.toString();
}
export function sameOriginMutation(requestOrigin: string | null, expectedOrigin: string): boolean {
  if (!requestOrigin) return false;
  try { return new URL(requestOrigin).origin === new URL(expectedOrigin).origin && requestOrigin === new URL(requestOrigin).origin; }
  catch { return false; }
}
export function apiOrigin(value: string | undefined): string | null {
  try {
    if (!value) return null;
    const url = new URL(value);
    if (url.username || url.password || url.search || url.hash || url.pathname !== "/") return null;
    if (url.protocol !== "https:" && !(url.protocol === "http:" && ["localhost", "127.0.0.1", "[::1]"].includes(url.hostname))) return null;
    return url.origin;
  } catch { return null; }
}
