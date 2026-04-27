export default function ContactPage() {
  return (
    <div className="max-w-4xl mx-auto px-8 pt-24 pb-32">
      <div className="text-center mb-16">
        <h1 className="text-4xl sm:text-5xl font-bold mb-6">Contact Us</h1>
        <p className="text-gray-400 text-lg max-w-2xl mx-auto">
          We&apos;re here to help. Reach out to our team for sales, support, or general inquiries.
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
        <div className="p-8 rounded-2xl border border-white/10 bg-white/[0.02] backdrop-blur-sm">
          <div className="text-3xl mb-4">💬</div>
          <h2 className="text-xl font-bold mb-2">Sales</h2>
          <p className="text-gray-400 text-sm mb-6">
            Looking for a custom plan or have questions about our enterprise offerings?
          </p>
          <a
            href="mailto:sales@ascenai.com"
            className="inline-block px-5 py-2.5 rounded-xl bg-violet-600 hover:bg-violet-700 text-white text-sm font-semibold transition-colors shadow-lg shadow-violet-500/20"
          >
            Email Sales
          </a>
        </div>

        <div className="p-8 rounded-2xl border border-white/10 bg-white/[0.02] backdrop-blur-sm">
          <div className="text-3xl mb-4">🛠️</div>
          <h2 className="text-xl font-bold mb-2">Support</h2>
          <p className="text-gray-400 text-sm mb-6">
            Need technical help with your agents or have an account issue?
          </p>
          <a
            href="mailto:support@ascenai.com"
            className="inline-block px-5 py-2.5 rounded-xl border border-white/20 hover:bg-white/5 text-white text-sm font-semibold transition-colors"
          >
            Email Support
          </a>
        </div>
      </div>

      <div className="mt-16 p-8 rounded-2xl border border-white/10 bg-white/[0.02] backdrop-blur-sm max-w-2xl mx-auto">
        <h2 className="text-2xl font-bold mb-6 text-center">Send us a message</h2>
        <form className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-400 mb-1.5">First Name</label>
              <input type="text" className="w-full px-4 py-2.5 rounded-xl bg-gray-900 border border-gray-800 focus:border-violet-500 focus:ring-1 focus:ring-violet-500 outline-none text-white text-sm" placeholder="John" />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-400 mb-1.5">Last Name</label>
              <input type="text" className="w-full px-4 py-2.5 rounded-xl bg-gray-900 border border-gray-800 focus:border-violet-500 focus:ring-1 focus:ring-violet-500 outline-none text-white text-sm" placeholder="Doe" />
            </div>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-400 mb-1.5">Email</label>
            <input type="email" className="w-full px-4 py-2.5 rounded-xl bg-gray-900 border border-gray-800 focus:border-violet-500 focus:ring-1 focus:ring-violet-500 outline-none text-white text-sm" placeholder="john@company.com" />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-400 mb-1.5">Message</label>
            <textarea rows={4} className="w-full px-4 py-2.5 rounded-xl bg-gray-900 border border-gray-800 focus:border-violet-500 focus:ring-1 focus:ring-violet-500 outline-none text-white text-sm resize-none" placeholder="How can we help?" />
          </div>
          <button type="button" className="w-full py-3 rounded-xl bg-gradient-to-r from-violet-600 to-blue-600 text-white font-semibold hover:opacity-90 transition-opacity">
            Send Message
          </button>
        </form>
      </div>
    </div>
  )
}
