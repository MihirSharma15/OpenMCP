"use client";

import { useEffect, useState, type ReactNode } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  ArrowUpRight,
  Bot,
  CircleHelp,
  Code2,
  CornerDownLeft,
  Home,
  ReceiptText,
  Search,
  Wallet,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";

export function DashboardFrame({
  children,
  mode,
  userMenu,
  preview = false,
}: {
  children: ReactNode;
  mode?: "test" | "live";
  userMenu?: ReactNode;
  preview?: boolean;
}) {
  const pathname = usePathname();
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const overview = preview ? "/design-system/dashboard" : "/dashboard";
  const NavigationLink = preview ? "a" : Link;
  const links = [
    {
      href: overview,
      title: "Overview",
      icon: Home,
      keywords: "home wallet balance",
    },
    {
      href: preview ? `${overview}#activity` : "/dashboard/transactions",
      title: "Transactions",
      icon: ReceiptText,
      keywords: "purchases deposits refunds history",
    },
    {
      href: preview ? `${overview}#agents` : "/dashboard/agents",
      title: "Agents",
      icon: Bot,
      keywords: "allowances access keys",
    },
  ];
  const tools = [
    {
      href: "/dashboard/agents#connect",
      title: "Connect your agent",
      icon: Code2,
      keywords: "integration mcp setup credentials",
    },
    {
      href: "/providers",
      title: "Provider console",
      icon: ArrowUpRight,
      keywords: "api services earnings",
    },
  ];
  const active = preview
    ? "Overview"
    : (links.find((link) =>
        link.href === "/dashboard"
          ? pathname === link.href
          : pathname.startsWith(link.href),
      )?.title ?? "Overview");
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key.toLowerCase() === "k" && (event.metaKey || event.ctrlKey)) {
        event.preventDefault();
        setOpen((value) => !value);
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);
  return (
    <div className="account-app dashboard-app">
      <a className="skip-link" href="#account-main">
        Skip to content
      </a>
      <aside className="account-sidebar">
        <Link href="/" className="wordmark dashboard-wordmark">
          <span className="account-brand-mark">↗</span>OpenMCP
        </Link>
        <div className="dashboard-workspace">
          <span className="dashboard-workspace-icon">
            <Wallet size={17} />
          </span>
          <div>
            Personal workspace<small>USD wallet</small>
          </div>
        </div>
        <nav aria-label="Account">
          {links.map(({ href, title, icon: Icon }) => (
            <NavigationLink
              key={title}
              href={href}
              className={active === title ? "active" : ""}
              aria-current={active === title ? "page" : undefined}
            >
              <Icon size={18} strokeWidth={1.7} />
              {title}
            </NavigationLink>
          ))}
        </nav>
        <div className="dashboard-nav-label">TOOLS</div>
        <nav aria-label="Workspace tools">
          {tools.map(({ href, title, icon: Icon }) => (
            <Link key={title} href={href}>
              <Icon size={17} strokeWidth={1.7} />
              {title}
            </Link>
          ))}
        </nav>
        <div className="dashboard-sidebar-bottom">
          <Link href="/dashboard/agents#connect">
            <CircleHelp size={16} />
            Connection guide
            <ArrowUpRight size={13} />
          </Link>
          <div className="dashboard-workspace-footer">
            <span className="account-dot" />
            <span>One wallet. Every agent.</span>
          </div>
        </div>
      </aside>
      <div className="account-content">
        <header className="account-topbar">
          <span className="dashboard-breadcrumb">
            Workspace<span>/</span>
            <strong>{active}</strong>
          </span>
          <Button
            variant="ghost"
            className="dashboard-jump"
            onClick={() => setOpen(true)}
            aria-label="Jump to a page"
          >
            <Search size={16} />
            <span>Jump to a page…</span>
            <kbd>⌘ K</kbd>
          </Button>
          <div className="dashboard-topbar-end">
            <Badge variant="outline" className="dashboard-mode">
              {preview
                ? "Preview"
                : mode === "test"
                  ? "Test mode"
                  : mode === "live"
                    ? "Live"
                    : "Connecting"}
            </Badge>
            {userMenu}
          </div>
        </header>
        <main id="account-main" className="account-main">
          {children}
        </main>
        <footer className="account-footer">
          <span>OpenMCP</span>
          <span>USD credits · Your limits, always.</span>
        </footer>
      </div>
      <CommandDialog
        open={open}
        onOpenChange={setOpen}
        title="Jump to a page"
        description="Find a workspace page or tool."
      >
        <CommandInput
          aria-label="Find a page or tool"
          placeholder="Find a page or tool…"
        />
        <CommandList>
          <CommandEmpty>No matching pages.</CommandEmpty>
          <CommandGroup heading="Workspace">
            {[...links, ...tools].map(
              ({ href, title, icon: Icon, keywords }) => (
                <CommandItem
                  key={title}
                  value={`${title} ${keywords}`}
                  onSelect={() => {
                    setOpen(false);
                    router.push(href);
                  }}
                >
                  <Icon size={17} />
                  <span>{title}</span>
                  <CornerDownLeft className="ml-auto size-3 opacity-40" />
                </CommandItem>
              ),
            )}
          </CommandGroup>
        </CommandList>
      </CommandDialog>
    </div>
  );
}
