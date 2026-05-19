import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

const PUBLIC_PATHS = ["/login", "/register"];
const STATIC_PREFIXES = ["/_next", "/favicon.ico", "/api"];

export function middleware(req: NextRequest) {
  const { pathname } = req.nextUrl;

  if (STATIC_PREFIXES.some((p) => pathname.startsWith(p))) {
    return NextResponse.next();
  }
  if (PUBLIC_PATHS.includes(pathname)) {
    return NextResponse.next();
  }

  // The JWT lives in localStorage (client-side). We also mirror it into a
  // non-HttpOnly cookie on login so middleware can do a cheap presence check.
  // Real authz still happens server-side at the API.
  const hasToken = req.cookies.get("apex_token")?.value;
  if (!hasToken) {
    const url = req.nextUrl.clone();
    url.pathname = "/login";
    url.searchParams.set("next", pathname);
    return NextResponse.redirect(url);
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
