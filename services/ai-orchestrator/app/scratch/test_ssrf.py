import sys
import os

# Add the app directory to sys.path
sys.path.append("/Users/visvasis/Home/Jamvant/AscenAI/services/ai-orchestrator")

# Mock structlog before import
import types
mock_structlog = types.ModuleType("structlog")
mock_structlog.get_logger = lambda x: types.SimpleNamespace(
    warning=lambda *a, **k: None, 
    error=lambda *a, **k: None,
    info=lambda *a, **k: None
)
sys.modules["structlog"] = mock_structlog

from app.utils.security import is_safe_url

test_urls = [
    "https://google.com",           # Safe
    "https://127.0.0.1",            # Unsafe (Loopback)
    "https://192.168.1.1",          # Unsafe (Private)
    "https://169.254.169.254",      # Unsafe (Link-local)
    "http://google.com",            # Unsafe (Non-HTTPS)
    "https://localhost",            # Unsafe (Localhost)
]

for url in test_urls:
    safe = is_safe_url(url)
    print(f"URL: {url:25} Safe: {safe}")
