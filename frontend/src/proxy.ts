import { clerkMiddleware } from "@clerk/nextjs/server";
import { NextResponse, type NextRequest, type NextFetchEvent } from "next/server";
import { clerkConfigured } from "./lib/account-config";

const authenticate = clerkMiddleware({ signInUrl: "/sign-in", signUpUrl: "/sign-up" });
export default function proxy(request: NextRequest, event: NextFetchEvent) {
  // Missing configuration shows an honest setup screen, never a mock session.
  if (!clerkConfigured()) return NextResponse.next();
  return authenticate(request, event);
}
export const config = {
  matcher: ["/((?!_next|[^?]*\\.(?:html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|docx?|xlsx?|zip|webmanifest)).*)", "/api/openmcp/(.*)"],
};
