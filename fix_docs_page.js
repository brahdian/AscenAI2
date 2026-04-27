const fs = require('fs');
const path = require('path');

const p = path.join(__dirname, 'frontend/web/src/app/(marketing)/docs/page.tsx');
let c = fs.readFileSync(p, 'utf8');

c = c.replace(/<nav className="border-b border-gray-200 dark:border-gray-800 bg-white\/80 dark:bg-gray-900\/80 backdrop-blur-md sticky top-0 z-20">[\s\S]*?<\/nav>/, '');
c = c.replace(/<footer className="border-t border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-950 py-12">[\s\S]*?<\/footer>/, '');
c = c.replace(/<main className="min-h-screen bg-gray-50 dark:bg-gray-950 text-gray-900 dark:text-white">/, '<div className="w-full">');
c = c.replace(/<\/main>/g, '</div>');

// Update Hero Background
c = c.replace(/className="relative overflow-hidden bg-white dark:bg-gray-950 border-b border-gray-200 dark:border-gray-800"/, 'className="relative overflow-hidden border-b border-white/10"');
c = c.replace(/className="absolute inset-0 bg-grid-slate-100 \[mask-image:linear-gradient\(0deg,white,rgba\(255,255,255,0\.6\)\)\] dark:bg-grid-slate-900\/50 dark:\[mask-image:linear-gradient\(0deg,rgba\(0,0,0,0\.1\),rgba\(0,0,0,0\.5\)\)\]"><\/div>/, 'className="absolute inset-0 bg-grid-white/[0.02] [mask-image:linear-gradient(0deg,transparent,black)]"></div>');

// Text Colors
c = c.replace(/text-gray-900 dark:text-white/g, 'text-white');
c = c.replace(/text-gray-500 dark:text-gray-400/g, 'text-gray-400');
c = c.replace(/text-gray-600 dark:text-gray-400/g, 'text-gray-400');
c = c.replace(/text-gray-400 dark:text-gray-500/g, 'text-gray-500');

// Search Bar
c = c.replace(/bg-gray-50 dark:bg-gray-900 border border-gray-200 dark:border-gray-800/g, 'bg-white/5 border border-white/10 text-white placeholder-gray-500');
c = c.replace(/text-gray-300 dark:text-gray-600/g, 'text-gray-500');

// Grid Cards
c = c.replace(/bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800/g, 'bg-white/[0.03] border border-white/10');
c = c.replace(/hover:border-violet-300 dark:hover:border-violet-700/g, 'hover:border-violet-500/50');
c = c.replace(/hover:bg-gray-100 dark:hover:bg-gray-800/g, 'hover:bg-white/10');

// Empty State
c = c.replace(/bg-gray-50 dark:bg-gray-900 rounded-3xl border-2 border-dashed border-gray-200 dark:border-gray-800/g, 'bg-white/5 rounded-3xl border-2 border-dashed border-white/10');

fs.writeFileSync(p, c);
