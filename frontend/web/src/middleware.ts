import { NextResponse } from 'next/server'
import type { NextRequest } from 'next/server'

export function middleware(request: NextRequest) {
  const url = request.nextUrl
  const hostname = request.headers.get('host') || ''

  // Read domains from environment
  const adminSubdomain =
    process.env.ADMIN_SUBDOMAIN || process.env.NEXT_PUBLIC_ADMIN_SUBDOMAIN || 'admin.lvh.me:3000'
  const appSubdomain =
    process.env.APP_SUBDOMAIN || process.env.NEXT_PUBLIC_APP_SUBDOMAIN || 'app.lvh.me:3000'
  const rootDomain =
    process.env.ROOT_DOMAIN || process.env.NEXT_PUBLIC_ROOT_DOMAIN || 'lvh.me:3000'

  const isAdminSubdomain = hostname === adminSubdomain
  const isAppSubdomain = hostname === appSubdomain

  // Log for debugging
  if (process.env.NODE_ENV === 'development') {
    console.log(`[Middleware] Host: ${hostname}, Admin: ${isAdminSubdomain}, App: ${isAppSubdomain}`)
  }

  // 1. ADMIN SUBDOMAIN: admin.lvh.me:3000
  if (isAdminSubdomain) {
    if (url.pathname === '/') {
      return NextResponse.rewrite(new URL('/admin/settings', request.url))
    }
    const commonPaths = ['/login', '/register', '/onboarding', '/forgot-password', '/reset-password', '/api/auth']
    if (commonPaths.some(p => url.pathname === p || url.pathname.startsWith(p + '/'))) {
      return NextResponse.next()
    }
    if (!url.pathname.startsWith('/admin')) {
      return NextResponse.rewrite(new URL(`/admin${url.pathname}`, request.url))
    }
  }

  // 2. APP SUBDOMAIN: app.lvh.me:3000
  if (isAppSubdomain) {
    // If root path on app subdomain → rewrite to /dashboard
    if (url.pathname === '/') {
      return NextResponse.rewrite(new URL('/dashboard', request.url))
    }

    // EXCLUDE common paths
    const commonPaths = ['/login', '/register', '/onboarding', '/forgot-password', '/reset-password', '/api/auth', '/console', '/pricing', '/docs']
    if (commonPaths.some(p => url.pathname === p || url.pathname.startsWith(p + '/'))) {
      return NextResponse.next()
    }

    // TRANSPARENT REWRITE: /agents -> /dashboard/agents
    if (!url.pathname.startsWith('/dashboard')) {
      return NextResponse.rewrite(new URL(`/dashboard${url.pathname}`, request.url))
    }
  }

  // 3. SECURITY: Block cross-access
  // Block direct /admin/* access from main domain or app subdomain
  if (url.pathname.startsWith('/admin') && !isAdminSubdomain) {
    return NextResponse.redirect(new URL(`http://${adminSubdomain}/admin/settings`))
  }
  // Block direct /dashboard/* access from main domain or admin subdomain
  if (url.pathname.startsWith('/dashboard') && !isAppSubdomain) {
    return NextResponse.redirect(new URL(`http://${appSubdomain}/`))
  }

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
