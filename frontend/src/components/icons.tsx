import {
  ArrowRight,
  ArrowLeftRight,
  Bot,
  Check,
  Code2,
  Copy,
  Download,
  ExternalLink,
  History,
  LayoutGrid,
  Plus,
  RefreshCw,
  Search,
  Wallet,
  X,
} from "lucide-react";

const icons = {
  wallet: Wallet,
  wallets: Wallet,
  history: History,
  agent: Bot,
  arrow: ArrowRight,
  plus: Plus,
  close: X,
  check: Check,
  overview: LayoutGrid,
  payments: ArrowLeftRight,
  services: Code2,
  download: Download,
  refresh: RefreshCw,
  search: Search,
  external: ExternalLink,
  copy: Copy,
};

export type IconName = keyof typeof icons;

export function Icon({ name, size = 20 }: { name: IconName; size?: number }) {
  const Component = icons[name];
  return <Component size={size} strokeWidth={1.6} aria-hidden="true" />;
}
