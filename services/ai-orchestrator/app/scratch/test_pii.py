import sys
import os

# Add the app directory to sys.path
sys.path.append("/Users/visvasis/Home/Jamvant/AscenAI/services/ai-orchestrator")

# Mock dependencies that might be missing or slow
import types
mock_structlog = types.ModuleType("structlog")
mock_structlog.get_logger = lambda x: types.SimpleNamespace(
    warning=lambda *a, **k: None, 
    error=lambda *a, **k: None,
    info=lambda *a, **k: None
)
sys.modules["structlog"] = mock_structlog

# Mock pii_service.warmup to avoid loading spacy
import app.services.pii_service as pii_service
pii_service._analyzer = types.SimpleNamespace(
    analyze=lambda text, language: [
        types.SimpleNamespace(start=0, end=len(text), entity_type="TEST_PII")
    ] if "PII" in text else []
)

history = [
    {"role": "user", "content": "My email is test@example.com"},
    {"role": "assistant", "content": "Got it."},
    {"role": "user", "content": "Wait, don't share my PII."}
]

trigger_message = "Sharing PII now."

# Manually verify the logic I added to PlaybookHandler.fire_connector
redacted_trigger = pii_service.redact(trigger_message) if trigger_message else ""
redacted_history = [
    {"role": m["role"], "content": pii_service.redact(m["content"])} 
    for m in history
]

print("Original Trigger:", trigger_message)
print("Redacted Trigger:", redacted_trigger)
print("---")
for i, m in enumerate(history):
    print(f"Original Msg {i}: {m['content']}")
    print(f"Redacted Msg {i}: {redacted_history[i]['content']}")
