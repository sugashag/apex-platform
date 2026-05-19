"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Sidebar } from "./sidebar";
import { Header } from "./header";
import { MobileNav } from "./mobile-nav";
import { useAuthStore } from "@/stores/auth-store";
import { refreshMe } from "@/lib/auth";
import { Loader2 } from "lucide-react";

export function AppShell({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const token = useAuthStore((s) => s.token);
  const user = useAuthStore((s) => s.user);
  const hydrated = useAuthStore((s) => s.hydrated);
  const [bootstrapped, setBootstrapped] = useState(false);

  useEffect(() => {
    if (!hydrated) return;
    if (!token) {
      router.replace("/login");
      return;
    }
    if (!user) {
      refreshMe()
        .catch(() => router.replace("/login"))
        .finally(() => setBootstrapped(true));
    } else {
      setBootstrapped(true);
    }
  }, [hydrated, token, user, router]);

  if (!hydrated || !bootstrapped) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <Loader2 className="h-5 w-5 animate-spin text-slate-400" aria-hidden />
      </div>
    );
  }

  return (
    <div className="flex min-h-screen bg-background">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <Header />
        <main className="flex-1 overflow-x-hidden pb-16 md:pb-0">{children}</main>
      </div>
      <MobileNav />
    </div>
  );
}
