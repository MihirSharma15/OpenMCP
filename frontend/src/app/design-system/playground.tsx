"use client";

import Link from "next/link";
import { useState } from "react";
import {
  ArrowRight,
  ArrowUpRight,
  Bot,
  Check,
  Plus,
  Sparkles,
  Wallet,
} from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Slider } from "@/components/ui/slider";
import { Progress } from "@/components/ui/progress";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import {
  Tooltip,
  TooltipTrigger,
  TooltipContent,
} from "@/components/ui/tooltip";
import { Separator } from "@/components/ui/separator";
import { SelectField } from "@/components/select-field";
import { AddMoneyDialog } from "@/components/account/top-up";
import { TransactionTable, Empty } from "@/components/account/common";
import { NumberTicker } from "@/components/ui/number-ticker";
import { EarningsChart } from "@/components/earnings-chart";
import type { ProviderTransaction } from "@/lib/openmcp";

const previewNow = Date.UTC(2026, 9, 13, 18);
const previewEarnings: ProviderTransaction[] = [
  48, 126, 90, 216, 144, 306, 252,
].map((cents, index) => ({
  execution_id: `preview-${index}`,
  session_id: "design-preview",
  status: "completed",
  endpoint_id: "preview",
  provider: "Preview",
  currency: "USD",
  price_cents: cents,
  platform_fee_cents: 0,
  provider_amount_cents: cents,
  agent_to_openmcp: null,
  openmcp_to_provider: {
    status: "success",
    reference: `preview-receipt-${index}`,
  },
  error: null,
  created_at: previewNow / 1000 - (6 - index) * 86400,
  paid_at: previewNow / 1000 - (6 - index) * 86400,
}));

export default function DesignSystem() {
  const [amount, setAmount] = useState(25);
  const [name, setName] = useState("Research assistant");
  const [period, setPeriod] = useState("7");
  const [dialog, setDialog] = useState(false);
  return (
    <main className="component-lab container">
      <nav className="lab-nav" aria-label="Design preview">
        <Link className="wordmark" href="/">
          OpenMCP
        </Link>
        <Badge variant="secondary">Design playground · local only</Badge>
        <Button asChild variant="ghost" size="sm">
          <Link href="/">
            Back to the site <ArrowUpRight />
          </Link>
        </Button>
      </nav>
      <header className="lab-heading">
        <span className="eyebrow accent">
          FAMILIAR FEELING. A SHARED FOUNDATION.
        </span>
        <h1>
          A little lavender.
          <br />A lot of possibility.
        </h1>
        <p>
          The OpenMCP design language, made with shadcn. Try the controls, move
          the allowance, and open the actual top-up dialog.
        </p>
      </header>
      <div className="lab-palette" aria-label="Design palette">
        {[
          ["Paper", "#FAFAF8"],
          ["Ink", "#161514"],
          ["Lavender", "#B8B5EC"],
          ["Violet", "#6259A6"],
          ["Mist", "#EFEEFB"],
        ].map(([label, color]) => (
          <div key={label}>
            <span style={{ background: color }} />
            <span>
              {label}
              <small>{color}</small>
            </span>
          </div>
        ))}
      </div>
      <div className="lab-grid">
        <Card className="lab-wallet">
          <CardHeader>
            <div className="lab-card-eyebrow">
              <span>THE WALLET</span>
              <Wallet size={20} strokeWidth={1.5} />
            </div>
            <CardTitle>Room for good work.</CardTitle>
            <CardDescription>
              A preview of your agent’s allowance.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="lab-money">
              $<NumberTicker value={amount} decimalPlaces={2} />
              <span>USD</span>
            </div>
            <Slider
              aria-label="Preview allowance in dollars"
              min={1}
              max={100}
              step={1}
              value={[amount]}
              onValueChange={([value]) => setAmount(value)}
            />
            <div className="lab-range">
              <span>$1</span>
              <span>$100</span>
            </div>
            <Separator />
            <div className="lab-wallet-bottom">
              <span>
                <Check size={15} />
                You set the limit.
              </span>
              <Button onClick={() => setDialog(true)}>
                <Plus />
                Add money
              </Button>
            </div>
          </CardContent>
        </Card>
        <Card className="lab-agent">
          <CardHeader>
            <div className="lab-card-eyebrow">
              <span>THE AGENT</span>
              <Bot size={20} strokeWidth={1.5} />
            </div>
            <CardTitle>Useful agents. Clear boundaries.</CardTitle>
            <CardDescription>
              Same soft surfaces. Better building blocks.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="lab-form">
              <Label htmlFor="preview-agent">Agent name</Label>
              <Input
                id="preview-agent"
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder="Research assistant"
              />
              <Label htmlFor="preview-expiry">Allowance expires in</Label>
              <SelectField
                id="preview-expiry"
                value={period}
                onValueChange={setPeriod}
                label="Preview allowance expiry"
                className="w-full"
                options={[
                  { value: "1", label: "1 day" },
                  { value: "7", label: "7 days" },
                  { value: "30", label: "30 days" },
                ]}
              />
            </div>
            <div className="lab-agent-foot">
              <Avatar>
                <AvatarFallback>
                  <Bot size={18} />
                </AvatarFallback>
              </Avatar>
              <span>
                {name || "Your agent"}
                <small>
                  ${amount.toFixed(2)} available · {period} days
                </small>
              </span>
              <Badge variant="success">Active</Badge>
            </div>
            <Progress value={amount} aria-label="Preview allowance" />
          </CardContent>
        </Card>
        <Card className="lab-controls">
          <CardHeader>
            <div className="lab-card-eyebrow">
              <span>THE DETAILS</span>
              <Sparkles size={18} strokeWidth={1.5} />
            </div>
            <CardTitle>Small things, considered.</CardTitle>
            <CardDescription>
              Buttons, states, and feedback that speak the same language.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="lab-button-row">
              <Button onClick={() => setDialog(true)}>
                Open dialog <ArrowRight />
              </Button>
              <Button
                variant="outline"
                onClick={() =>
                  toast.success("All caught up", {
                    description:
                      "This is a preview notification. No account data changed.",
                  })
                }
              >
                Try a notification
              </Button>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    variant="ghost"
                    size="icon"
                    aria-label="Learn about allowances"
                  >
                    <Bot />
                  </Button>
                </TooltipTrigger>
                <TooltipContent>
                  Your agent can spend within its allowance.
                </TooltipContent>
              </Tooltip>
            </div>
            <div className="lab-badges">
              <Badge variant="success">Completed</Badge>
              <Badge variant="warning">Pending</Badge>
              <Badge variant="secondary">Refunded</Badge>
              <Badge>Expired</Badge>
              <Button variant="outline" size="sm" disabled>
                Unavailable
              </Button>
            </div>
          </CardContent>
        </Card>
        <Card className="lab-activity">
          <CardHeader>
            <div className="lab-card-eyebrow">
              <span>THE FULL PICTURE</span>
              <span>UI specimens</span>
            </div>
            <CardTitle>Every detail has a home.</CardTitle>
          </CardHeader>
          <CardContent>
            <Tabs defaultValue="empty">
              <TabsList aria-label="Preview activity states">
                <TabsTrigger value="empty">Empty state</TabsTrigger>
                <TabsTrigger value="table">Table structure</TabsTrigger>
              </TabsList>
              <TabsContent value="empty">
                <Empty icon="history" title="Ready for your first useful thing">
                  <p>
                    Purchases, deposits, and refunds will feel right at home
                    here.
                  </p>
                </Empty>
              </TabsContent>
              <TabsContent value="table">
                <TransactionTable rows={[]} />
                <p className="lab-note">
                  An empty table specimen. Live transactions stay in your
                  account.
                </p>
              </TabsContent>
            </Tabs>
          </CardContent>
        </Card>
      </div>
      <Card className="lab-chart">
        <CardHeader>
          <div className="lab-card-eyebrow">
            <span>THE RHYTHM</span>
            <Badge variant="outline">Illustrative data</Badge>
          </div>
          <CardTitle>Earnings, in a little more detail.</CardTitle>
          <CardDescription>
            The same chart used in the provider workspace. Focus it and use the
            arrow keys to explore.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <EarningsChart
            transactions={previewEarnings}
            period="7"
            now={previewNow}
            loaded
          />
        </CardContent>
      </Card>
      <footer className="lab-footer">
        <span>Figtree + Geist Mono. Paper + ink + lavender.</span>
        <div>
          <Link href="/providers">Provider workspace ↗</Link>
          <Link href="/demo">Wallet observer ↗</Link>
        </div>
      </footer>
      {dialog && (
        <AddMoneyDialog
          presets={[500, 1000, 2500, 5000]}
          mode="test"
          onClose={() => setDialog(false)}
          onCheckout={(cents) => {
            setDialog(false);
            toast.success(`$${(cents / 100).toFixed(2)} selected`, {
              description:
                "Preview only. No checkout was created and no payment was made.",
            });
          }}
        />
      )}
    </main>
  );
}
