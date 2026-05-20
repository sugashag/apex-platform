import { apiFetch } from "@/lib/api";
import { useAuthStore } from "@/stores/auth-store";
import type { TokenResponse, User } from "@/lib/types";

const TOKEN_COOKIE = "apex_token";
const COOKIE_MAX_AGE_SECONDS = 60 * 60 * 24 * 7;

function setTokenCookie(token: string): void {
  if (typeof document === "undefined") return;
  const isSecure = typeof window !== "undefined" && window.location.protocol === "https:";
  const attrs = [
    `${TOKEN_COOKIE}=${encodeURIComponent(token)}`,
    "Path=/",
    `Max-Age=${COOKIE_MAX_AGE_SECONDS}`,
    "SameSite=Lax",
  ];
  if (isSecure) attrs.push("Secure");
  document.cookie = attrs.join("; ");
}

function clearTokenCookie(): void {
  if (typeof document === "undefined") return;
  document.cookie = `${TOKEN_COOKIE}=; Path=/; Max-Age=0; SameSite=Lax`;
}

export async function login(email: string, password: string): Promise<User> {
  const tokenRes = await apiFetch<TokenResponse>("/auth/login", {
    method: "POST",
    body: { email, password },
    skipAuth: true,
  });

  setTokenCookie(tokenRes.access_token);

  const user = await apiFetch<User>("/auth/me", {
    method: "GET",
    headers: { Authorization: `Bearer ${tokenRes.access_token}` },
    skipAuth: true,
  });

  useAuthStore.getState().setSession(tokenRes.access_token, user);
  return user;
}

export async function register(
  email: string,
  password: string,
  workspaceName: string
): Promise<User> {
  const tokenRes = await apiFetch<TokenResponse>("/auth/register", {
    method: "POST",
    body: { email, password, workspace_name: workspaceName },
    skipAuth: true,
  });

  setTokenCookie(tokenRes.access_token);

  const user = await apiFetch<User>("/auth/me", {
    method: "GET",
    headers: { Authorization: `Bearer ${tokenRes.access_token}` },
    skipAuth: true,
  });

  useAuthStore.getState().setSession(tokenRes.access_token, user);
  return user;
}

export function logout(): void {
  clearTokenCookie();
  useAuthStore.getState().clear();
}

export async function refreshMe(): Promise<User> {
  const user = await apiFetch<User>("/auth/me");
  useAuthStore.getState().setUser(user);
  return user;
}
