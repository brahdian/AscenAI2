export default function CareersPage() {
  const positions = [
    { title: 'Senior Full Stack Engineer', department: 'Engineering', location: 'Remote (US/Canada)', type: 'Full-time' },
    { title: 'AI/ML Engineer', department: 'Engineering', location: 'Remote', type: 'Full-time' },
    { title: 'Product Designer', department: 'Design', location: 'Remote', type: 'Full-time' },
    { title: 'Account Executive', department: 'Sales', location: 'Remote (US)', type: 'Full-time' },
  ]

  return (
    <div className="max-w-5xl mx-auto px-8 pt-24 pb-32">
      <div className="text-center mb-16">
        <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full bg-violet-500/10 border border-violet-500/20 text-violet-300 text-sm mb-6">
          🚀 We&apos;re hiring!
        </div>
        <h1 className="text-4xl sm:text-5xl font-bold mb-6">Join the AscenAI Team</h1>
        <p className="text-gray-400 text-lg max-w-2xl mx-auto">
          Help us build the next generation of voice and chat AI agents that power local businesses around the world.
        </p>
      </div>

      <div className="mb-20 grid grid-cols-1 md:grid-cols-3 gap-6">
        {[
          { icon: '🌍', title: 'Work Anywhere', desc: 'We are a fully remote company. Work from wherever you are happiest and most productive.' },
          { icon: '💡', title: 'Big Impact', desc: 'We ship fast and trust our team. Your work directly impacts thousands of local businesses.' },
          { icon: '🏥', title: 'Great Benefits', desc: 'Competitive salary, equity, top-tier health/dental, and a generous equipment stipend.' },
        ].map((perk) => (
          <div key={perk.title} className="p-6 rounded-2xl border border-white/5 bg-white/[0.02]">
            <div className="text-3xl mb-3">{perk.icon}</div>
            <h3 className="text-lg font-bold mb-2">{perk.title}</h3>
            <p className="text-sm text-gray-400">{perk.desc}</p>
          </div>
        ))}
      </div>

      <div>
        <h2 className="text-2xl font-bold mb-8">Open Positions</h2>
        <div className="space-y-4">
          {positions.map((pos) => (
            <div key={pos.title} className="p-6 rounded-2xl border border-white/10 bg-white/[0.02] hover:border-violet-500/50 transition-colors flex flex-col md:flex-row md:items-center justify-between gap-4 group cursor-pointer">
              <div>
                <h3 className="text-lg font-bold text-white group-hover:text-violet-400 transition-colors">{pos.title}</h3>
                <div className="flex flex-wrap items-center gap-3 mt-2 text-sm text-gray-400">
                  <span className="flex items-center gap-1.5">
                    <span className="w-2 h-2 rounded-full bg-violet-500" />
                    {pos.department}
                  </span>
                  <span>·</span>
                  <span>{pos.location}</span>
                  <span>·</span>
                  <span>{pos.type}</span>
                </div>
              </div>
              <button className="px-4 py-2 rounded-lg border border-white/20 text-sm font-medium hover:bg-white/5 transition-colors shrink-0">
                Apply Now
              </button>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
