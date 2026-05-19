"use client";

import { Bell, Search, LogOut } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { useAuthStore } from "@/stores/auth-store";
import { logout } from "@/lib/auth";
import { initials } from "@/lib/utils";
import { useRouter } from "next/navigation";
import { useState, useRef, useEffect } from "react";

export function Header() {
  const router = useRouter();
  const user = useAuthStore((s) => s.user);
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function onDocClick(e: MouseEvent) {
      if (!menuRef.current?.contains(e.target as Node)) setMenuOpen(false);
    }
    if (menuOpen) document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, [menuOpen]);

  function onLogout() {
    logout();
    router.replace("/login");
  }

  return (
    <header className="sticky top-0 z-20 flex h-14 items-center gap-3 border-b border-[#E2E8F0] bg-white px-4">
      <div className="relative max-w-md flex-1">
        <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" aria-hidden />
        <Input
          type="search"
          placeholder="Search contacts, deals, companies…"
          className="pl-9"
          aria-label="Global search"
        />
      </div>
      <div className="ml-auto flex items-center gap-2">
        <Button variant="ghost" size="icon" aria-label="Notifications">
          <Bell className="h-5 w-5" aria-hidden />
        </Button>
        <div className="relative" ref={menuRef}>
          <button
            type="button"
            onClick={() => setMenuOpen((v) => !v)}
            className="flex items-center gap-2 rounded-full p-1 hover:bg-slate-100"
            aria-haspopup="menu"
            aria-expanded={menuOpen}
          >
            <Avatar>
              <AvatarFallback>{initials(user?.first_name, user?.last_name, user?.email)}</AvatarFallback>
            </Avatar>
          </button>
          {menuOpen ? (
            <div
              role="menu"
              className="absolute right-0 mt-2 w-56 rounded-md border border-[#E2E8F0] bg-white p-1 shadow-md"
            >
              <div className="px-3 py-2">
                <div className="truncate text-sm font-medium text-slate-900">
                  {user?.first_name || user?.last_name
                    ? `${user.first_name ?? ""} ${user.last_name ?? ""}`.trim()
                    : user?.email}
                </div>
                <div className="truncate text-xs text-slate-500">{user?.email}</div>
              </div>
              <div className="my-1 border-t border-[#E2E8F0]" />
              <button
                type="button"
                role="menuitem"
                onClick={onLogout}
                className="flex w-full items-center gap-2 rounded-sm px-3 py-2 text-sm text-slate-700 hover:bg-slate-100"
              >
                <LogOut className="h-4 w-4" aria-hidden />
                Sign out
              </button>
            </div>
          ) : null}
        </div>
      </div>
    </header>
  );
}
