import Link from 'next/link'

export default function MarketingLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-gradient-to-br from-[#0f0728] via-[#1a1040] to-[#0c1e4a] text-white flex flex-col">
      {/* Navbar */}
      <nav className="flex items-center justify-between px-8 py-5 max-w-7xl mx-auto w-full">
        <Link href="/" className="flex items-center gap-2 group">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-violet-500 to-blue-500 flex items-center justify-center text-white font-bold text-sm group-hover:shadow-[0_0_15px_rgba(124,58,237,0.5)] transition-shadow">
            A
          </div>
          <span className="text-xl font-bold text-white tracking-tight">AscenAI</span>
        </Link>
        <div className="hidden md:flex items-center gap-6">
          <Link href="/pricing" className="text-sm font-medium text-gray-300 hover:text-white transition-colors">Pricing</Link>
          <Link href="/faq" className="text-sm font-medium text-gray-300 hover:text-white transition-colors">FAQ</Link>
          <Link href="/docs" className="text-sm font-medium text-gray-300 hover:text-white transition-colors">Docs</Link>
          <Link href="/contact" className="text-sm font-medium text-gray-300 hover:text-white transition-colors">Contact</Link>
        </div>
        <div className="flex items-center gap-4">
          <Link href="/login" className="text-sm font-medium text-gray-300 hover:text-white transition-colors">
            Sign in
          </Link>
          <Link
            href="/register"
            className="px-4 py-2 rounded-lg bg-gradient-to-r from-violet-600 to-blue-600 text-white text-sm font-semibold hover:opacity-90 transition-all hover:shadow-[0_0_15px_rgba(124,58,237,0.4)]"
          >
            Get Started
          </Link>
        </div>
      </nav>

      {/* Main Content */}
      <main className="flex-1 w-full">
        {children}
      </main>

      {/* Footer */}
      <footer className="border-t border-white/5 py-12 mt-auto">
        <div className="max-w-7xl mx-auto px-8 grid grid-cols-1 md:grid-cols-4 gap-8 mb-8">
          <div className="col-span-1 md:col-span-2">
            <Link href="/" className="flex items-center gap-2 mb-4">
              <div className="w-6 h-6 rounded-md bg-gradient-to-br from-violet-500 to-blue-500 flex items-center justify-center text-white font-bold text-xs">
                A
              </div>
              <span className="text-lg font-bold text-white">AscenAI</span>
            </Link>
            <p className="text-gray-400 text-sm max-w-sm leading-relaxed mb-4">
              Deploy intelligent voice and chat agents for your business. Handle bookings, orders, and customer queries automatically — 24/7.
            </p>
            <div className="text-gray-500 text-sm">
              <a href="mailto:support@ascenai.com" className="hover:text-gray-300 transition-colors">support@ascenai.com</a>
              <span className="mx-2">·</span>
              <a href="mailto:sales@ascenai.com" className="hover:text-gray-300 transition-colors">sales@ascenai.com</a>
            </div>
          </div>
          <div>
            <h4 className="font-semibold text-white mb-4">Product</h4>
            <ul className="space-y-2 text-sm text-gray-400">
              <li><Link href="/pricing" className="hover:text-violet-400 transition-colors">Pricing</Link></li>
              <li><Link href="/docs" className="hover:text-violet-400 transition-colors">Documentation</Link></li>
              <li><Link href="/register" className="hover:text-violet-400 transition-colors">Get Started</Link></li>
            </ul>
          </div>
          <div>
            <h4 className="font-semibold text-white mb-4">Company</h4>
            <ul className="space-y-2 text-sm text-gray-400">
              <li><Link href="/contact" className="hover:text-violet-400 transition-colors">Contact Us</Link></li>
              <li><Link href="/careers" className="hover:text-violet-400 transition-colors">Careers</Link></li>
              <li><Link href="/faq" className="hover:text-violet-400 transition-colors">FAQ</Link></li>
            </ul>
          </div>
        </div>
        <div className="max-w-7xl mx-auto px-8 pt-8 border-t border-white/5 flex flex-col md:flex-row items-center justify-between gap-4 text-xs text-gray-500">
          <p>© {new Date().getFullYear()} AscenAI. Built with FastAPI, Next.js, and Gemini.</p>
          <div className="flex items-center gap-4">
            <span className="hover:text-gray-300 transition-colors cursor-pointer">Privacy Policy</span>
            <span className="hover:text-gray-300 transition-colors cursor-pointer">Terms of Service</span>
          </div>
        </div>
      </footer>
    </div>
  )
}
