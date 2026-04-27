import { NextResponse } from 'next/server'
import type { NextRequest } from 'next/server'

export function middleware(request: NextRequest) {
  const url = request.nextUrl
  const hostname = request.headers.get('host') || ''

  // ── Subdomain configuration ──────────────────────────────────────────────
  const rootDomain = process.env.NEXT_PUBLIC_ROOT_DOMAIN || 'lvh.me:3000'
  const tenantAdminSubdomain = process.env.NEXT_PUBLIC_TENANT_ADMIN_SUBDOMAIN || `admin.${rootDomain}`
  const agentsSubdomain = process.env.NEXT_PUBLIC_AGENTS_SUBDOMAIN || `agents.${rootDomain}`
  const appSubdomain = process.env.NEXT_PUBLIC_APP_SUBDOMAIN || `app.${rootDomain}`
  const adminSubdomain = process.env.NEXT_PUBLIC_ADMIN_SUBDOMAIN || `admin.agent.${rootDomain}`

  const isTenantAdmin = hostname === tenantAdminSubdomain
  const isAgents = hostname === agentsSubdomain
  const isAppLegacy = hostname === appSubdomain  // legacy, treated as agents
  const isPlatformAdmin = hostname === adminSubdomain

  if (process.env.NODE_ENV === 'development') {
    console.log(`[Middleware] Host: ${hostname} → TenantAdmin:${isTenantAdmin} Agents:${isAgents} Legacy:${isAppLegacy} PlatformAdmin:${isPlatformAdmin}`)
  }

  // Common paths that always render normally regardless of subdomain
  const commonPaths = [
    '/login', '/register', '/onboarding', '/forgot-password',
    '/reset-password', '/api/', '/pricing', '/docs',
  ]
  const isCommonPath = commonPaths.some(
    (p) => url.pathname === p || url.pathname.startsWith(p + '/')
  )

  // ── 1. TENANT ADMIN PORTAL: admin.lvh.me ────────────────────────────────
  if (isTenantAdmin) {
    if (isCommonPath) return NextResponse.next()

    // Root → hub
    if (url.pathname === '/') {
      return NextResponse.rewrite(new URL('/tenant-admin', request.url))
    }
    // Already scoped under /tenant-admin → pass through
    if (url.pathname.startsWith('/tenant-admin')) {
      return NextResponse.next()
    }
    // Transparent rewrite: /members → /tenant-admin/members
    return NextResponse.rewrite(new URL(`/tenant-admin${url.pathname}`, request.url))
  }

  // ── 2. AGENTS DASHBOARD: agents.lvh.me (+ legacy app.lvh.me) ───────────
  if (isAgents || isAppLegacy) {
    if (isCommonPath) return NextResponse.next()
    if (url.pathname.startsWith('/console')) return NextResponse.next()

    const hasToken = request.cookies.has('access_token')
    if (url.pathname === '/') {
      return hasToken
        ? NextResponse.rewrite(new URL('/dashboard', request.url))
        : NextResponse.next()
    }
    if (!url.pathname.startsWith('/dashboard')) {
      return NextResponse.rewrite(new URL(`/dashboard${url.pathname}`, request.url))
    }
    return NextResponse.next()
  }

  // ── 3. PLATFORM SUPER ADMIN: admin.agent.lvh.me ─────────────────────────
  if (isPlatformAdmin) {
    if (isCommonPath) return NextResponse.next()
    if (url.pathname === '/') {
      return NextResponse.rewrite(new URL('/admin/settings', request.url))
    }
    if (!url.pathname.startsWith('/admin')) {
      return NextResponse.rewrite(new URL(`/admin${url.pathname}`, request.url))
    }
    return NextResponse.next()
  }

  // ── 4. SECURITY: Block cross-subdomain direct access ────────────────────
  // Block /tenant-admin/* from non-admin subdomains
  if (url.pathname.startsWith('/tenant-admin') && !isTenantAdmin) {
    return NextResponse.redirect(
      new URL(`http://${tenantAdminSubdomain}/`, request.url)
    )
  }
  // Block /admin/* (platform admin) from non-platform-admin subdomains
  if (url.pathname.startsWith('/admin') && !isPlatformAdmin) {
    return NextResponse.redirect(
      new URL(`http://${adminSubdomain}/admin/settings`, request.url)
    )
  }
  // Block /dashboard/* from non-agents subdomains
  if (url.pathname.startsWith('/dashboard') && !isAgents && !isAppLegacy) {
    return NextResponse.redirect(
      new URL(`http://${agentsSubdomain}/`, request.url)
    )
  }

  return NextResponse.next()
}

export const config = {
  matcher: [
    '/((?!api|_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)',
  ],
}
