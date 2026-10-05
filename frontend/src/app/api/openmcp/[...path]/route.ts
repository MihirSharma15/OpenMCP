import { auth } from "@clerk/nextjs/server";
import { NextRequest } from "next/server";
import { clerkConfigured } from "@/lib/account-config";
import { accountQuery, allowedAccountPath, apiOrigin, sameOriginMutation } from "@/lib/account-proxy";

export const dynamic = "force-dynamic";
type Context = { params: Promise<{ path: string[] }> };
const privateHeaders = { "Cache-Control": "private, no-store, max-age=0", "Vary": "Cookie", "X-Content-Type-Options": "nosniff" };
function failure(status: number, code: string, message: string, retryable = false) {
  return Response.json({ error: { code, message, retryable } }, { status, headers: privateHeaders });
}
async function proxy(request: NextRequest, context: Context) {
  const path = allowedAccountPath(request.method, (await context.params).path);
  if (!path) return failure(404, "not_found", "This account operation is not available.");
  if (request.method === "POST" && !sameOriginMutation(request.headers.get("origin"), process.env.OPENMCP_APP_ORIGIN ?? request.nextUrl.origin)) {
    return failure(403, "invalid_origin", "This request must come from the OpenMCP website.");
  }
  if (!clerkConfigured()) return failure(503, "auth_unavailable", "Sign-in is not configured on this deployment.");
  const origin = apiOrigin(process.env.OPENMCP_API_URL);
  if (!origin) return failure(503, "backend_unavailable", "The account service is not configured on this deployment.");
  let token: string | null;
  try {
    const session = await auth();
    if (!session.userId) return failure(401, "unauthorized", "Your session has ended. Please sign in again.");
    token = await session.getToken();
  } catch {
    return failure(503, "auth_unavailable", "Sign-in is temporarily unavailable. Please retry.", true);
  }
  if (!token) return failure(401, "unauthorized", "Please sign in again to continue.");
  const headers: Record<string, string> = { "Authorization": `Bearer ${token}`, "Content-Type": "application/json", "Accept": "application/json" };
  const key = request.headers.get("idempotency-key");
  if (key && /^[A-Za-z0-9_-]{1,128}$/.test(key)) headers["Idempotency-Key"] = key;
  let body: string | undefined;
  if (request.method === "POST") {
    if (!request.headers.get("content-type")?.startsWith("application/json")) return failure(415, "invalid_content_type", "JSON is required.");
    if (Number(request.headers.get("content-length")) > 65536) return failure(413, "request_too_large", "This request is too large.");
    try { body = await request.text(); } catch { return failure(400, "invalid_body", "The request body could not be read."); }
    if (body.length > 65536) return failure(413, "request_too_large", "This request is too large.");
    try { JSON.parse(body); } catch { return failure(400, "invalid_json", "The request body is not valid JSON."); }
  }
  const query = accountQuery(path, request.nextUrl.searchParams);
  try {
    const response = await fetch(`${origin}/v1/${path}${query ? `?${query}` : ""}`, {
      method: request.method, headers, body, cache: "no-store", redirect: "error", signal: AbortSignal.timeout(25_000),
    });
    if (!response.headers.get("content-type")?.includes("application/json")) return failure(502, "invalid_response", "The account service returned an unreadable response.", true);
    return new Response(await response.text(), { status: response.status, headers: { ...privateHeaders, "Content-Type": "application/json" } });
  } catch {
    return failure(503, "backend_unavailable", "The account service is temporarily unavailable. Retry this request.", true);
  }
}
export const GET = proxy;
export const POST = proxy;
