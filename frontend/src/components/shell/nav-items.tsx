import {
  Inbox,
  KanbanSquare,
  Users,
  Building2,
  Phone,
  BarChart3,
  ListChecks,
  Workflow,
  Settings,
  type LucideIcon,
} from "lucide-react";

export interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
}

export const NAV_ITEMS: NavItem[] = [
  { href: "/inbox", label: "Inbox", icon: Inbox },
  { href: "/pipeline", label: "Pipeline", icon: KanbanSquare },
  { href: "/contacts", label: "Contacts", icon: Users },
  { href: "/companies", label: "Companies", icon: Building2 },
  { href: "/calls", label: "Calls", icon: Phone },
  { href: "/reports", label: "Reports", icon: BarChart3 },
  { href: "/sequences", label: "Sequences", icon: ListChecks },
  { href: "/workflows", label: "Workflows", icon: Workflow },
  { href: "/settings", label: "Settings", icon: Settings },
];

export const MOBILE_NAV_ITEMS: NavItem[] = [
  NAV_ITEMS[0]!,
  NAV_ITEMS[1]!,
  NAV_ITEMS[2]!,
  NAV_ITEMS[5]!,
  NAV_ITEMS[8]!,
];
