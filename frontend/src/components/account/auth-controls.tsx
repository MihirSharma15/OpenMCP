"use client";
import { Button } from "@/components/ui/button";

import { Show, UserButton } from "@clerk/nextjs";
import Link from "next/link";

export function AuthControls({ enabled }: { enabled: boolean }) {
  if (!enabled)
    return (
      <>
        <Link href="/sign-in">Sign in</Link>
        <Button asChild variant="default" size="sm">
          <Link href="/dashboard" className="button button-small">
            Get started
          </Link>
        </Button>
      </>
    );
  return (
    <>
      <Show when="signed-out">
        <Link href="/sign-in">Sign in</Link>
        <Button asChild variant="default" size="sm">
          <Link href="/sign-up" className="button button-small">
            Get started
          </Link>
        </Button>
      </Show>
      <Show when="signed-in">
        <Button asChild variant="default" size="sm">
          <Link href="/dashboard" className="button button-small">
            Dashboard
          </Link>
        </Button>
        <UserButton />
      </Show>
    </>
  );
}
