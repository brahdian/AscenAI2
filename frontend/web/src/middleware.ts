import { NextResponse } from 'next/server'
import type { NextRequest } from 'next/server'

export function middleware(request: NextRequest) {
  const url = request.nextUrl
  const hostname = request.headers.get('host') || ''

  // Read domains from environment
  // Next.js replaces NEXT_PUBLIC_* variables at build time. For middleware (Edge runtime),
  // it's safer to read a non-public server-only variable if we want to change it at runtime without a rebuild.
  const adminSubdomain =
    process.env.ADMIN_SUBDOMAIN || process.env.NEXT_PUBLIC_ADMIN_SUBDOMAIN || 'admin.lvh.me:3000'

  // Detect admin subdomain: exact match
  const isAdminSubdomain = hostname === adminSubdomain

  // Log for debugging (only in development if needed)
  if (process.env.NODE_ENV === 'development') {
    console.log(`[Middleware] Host: ${hostname}, AdminSub: ${adminSubdomain}, Match: ${isAdminSubdomain}`)
  }

  if (isAdminSubdomain) {
    // 1. Root path on admin subdomain → rewrite to /admin/settings
    if (url.pathname === '/') {
      return NextResponse.rewrite(new URL('/admin/settings', request.url))
    }

    // 2. EXCLUDE global paths (auth, etc.) from /admin rewrite
    // These paths exist in the root but should be accessible from the admin subdomain
    const commonPaths = ['/login', '/register', '/onboarding', '/api/auth']
    const isCommon = commonPaths.some(p => url.pathname === p || url.pathname.startsWith(p + '/'))

    if (isCommon) {
      return NextResponse.next()
    }

    // 3. Rewrite all other paths to the /admin/ folder
    if (!url.pathname.startsWith('/admin')) {
      return NextResponse.rewrite(new URL(`/admin${url.pathname}`, request.url))
    }
  }

  // Block direct /admin/* access from the main domain
  if (url.pathname.startsWith('/admin')) {
    return NextResponse.redirect(new URL('/', request.url))
  }

  // ── AUTH: Client-side handles auth via syncAuth + Zustand persist ──────────
  // Cookie-based auth check removed — cookies from localhost:8000 are not
  // available on localhost:3000 (cross-origin). Client-side auth store handles
  // authentication state and redirects after hydration.

  return NextResponse.next()
}

export const config = {
  matcher: [
    /*
     * Match all request paths except for the ones starting with:
     * - api (API routes — authenticated separately by the backend)
     * - _next/static (static files)
     * - _next/image (image optimization files)
     * - favicon.ico (favicon file)
     * - public assets (png, jpg, svg, etc.)
     */
    '/((?!api|_next/static|_next/image|favicon.ico|.*\.(?:svg|png|jpg|jpeg|gif|webp)$).*)',
  ],
}
