import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

export function formatCurrency(
  amount: number | null | undefined,
  currency: string = "USD",
  options: { fromCents?: boolean } = { fromCents: true }
): string {
  if (amount == null || Number.isNaN(amount)) return "—";
  const value = options.fromCents === false ? amount : amount / 100;
  try {
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency,
      maximumFractionDigits: value % 1 === 0 ? 0 : 2,
    }).format(value);
  } catch {
    return `$${value.toFixed(2)}`;
  }
}

export function daysBetween(input: string | Date | null | undefined, end: Date = new Date()): number {
  if (!input) return 0;
  const start = typeof input === "string" ? new Date(input) : input;
  if (Number.isNaN(start.getTime())) return 0;
  const diffMs = end.getTime() - start.getTime();
  return Math.max(0, Math.floor(diffMs / (1000 * 60 * 60 * 24)));
}

export function initials(
  first?: string | null,
  last?: string | null,
  email?: string | null
): string {
  const f = (first ?? "").trim();
  const l = (last ?? "").trim();
  if (f || l) {
    return `${f.charAt(0)}${l.charAt(0)}`.toUpperCase() || "?";
  }
  const e = (email ?? "").trim();
  if (e) {
    const local = e.split("@")[0] ?? "";
    const parts = local.split(/[._-]+/).filter(Boolean);
    if (parts.length >= 2) {
      return `${parts[0]!.charAt(0)}${parts[1]!.charAt(0)}`.toUpperCase();
    }
    return (local.slice(0, 2) || "?").toUpperCase();
  }
  return "?";
}

export type LeadScoreBucket = "low" | "med" | "high";

export function leadScoreBucket(score: number | null | undefined): LeadScoreBucket {
  const n = typeof score === "number" ? score : 0;
  if (n >= 70) return "high";
  if (n >= 40) return "med";
  return "low";
}

export function formatDate(input: string | Date | null | undefined): string {
  if (!input) return "—";
  const d = typeof input === "string" ? new Date(input) : input;
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" });
}
