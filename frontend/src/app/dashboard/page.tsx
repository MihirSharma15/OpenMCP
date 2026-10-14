"use client";

import { useState } from "react";
import {
  type Agent,
  type Page,
  type Transaction,
  type Wallet,
} from "@/lib/account";
import { useResource } from "@/components/account/common";
import { AddMoney } from "@/components/account/top-up";
import { DashboardOverview } from "@/components/account/dashboard-overview";

export default function Overview() {
  const wallet = useResource<Wallet>(
    "/wallet",
    (data) => data.reserved_cents > 0,
  );
  const history = useResource<Page<Transaction>>(
    "/transactions?limit=100",
    (data) => data.items.some((row) => row.status === "pending"),
  );
  const agents = useResource<Page<Agent>>("/agents?limit=100", (data) =>
    data.items.some((agent) => agent.reserved_cents > 0),
  );
  const [topUp, setTopUp] = useState(false);
  const now = Date.now();
  return (
    <>
      <DashboardOverview
        wallet={wallet}
        history={history}
        agents={agents}
        now={now}
        onAddMoney={() => setTopUp(true)}
        onRefresh={() => {
          wallet.reload();
          history.reload();
          agents.reload();
        }}
      />
      {topUp && <AddMoney onClose={() => setTopUp(false)} />}
    </>
  );
}
