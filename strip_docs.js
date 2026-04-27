const fs = require('fs');
const path = require('path');

const docsDir = path.join(__dirname, 'frontend/web/src/app/(marketing)/docs');

function processFile(filePath) {
  let content = fs.readFileSync(filePath, 'utf8');

  // Remove <nav> ... </nav> block that contains "Pricing" and "Sign in"
  content = content.replace(/<nav className="flex items-center justify-between px-8 py-5 max-w-5xl mx-auto">[\s\S]*?<\/nav>/, '');

  // Remove <footer> ... </footer>
  content = content.replace(/<footer className="border-t border-white\/5 py-8 text-center text-gray-500 text-sm">[\s\S]*?<\/footer>/, '');

  // Replace <main className="min-h-screen bg-gradient..."> with <div className="w-full">
  content = content.replace(/<main className="min-h-screen bg-gradient-to-br from-\[#0f0728\] via-\[#1a1040\] to-\[#0c1e4a\] text-white">/, '<div className="w-full">');
  
  // Also replace </main> with </div>
  content = content.replace(/<\/main>/g, '</div>');

  fs.writeFileSync(filePath, content);
  console.log('Processed', filePath);
}

function walkDir(dir) {
  const files = fs.readdirSync(dir);
  for (const file of files) {
    const fullPath = path.join(dir, file);
    if (fs.statSync(fullPath).isDirectory()) {
      walkDir(fullPath);
    } else if (file === 'page.tsx') {
      if (fullPath !== path.join(docsDir, 'page.tsx')) {
        processFile(fullPath);
      }
    }
  }
}

walkDir(docsDir);
