import asyncio
import shared.pii as pii_service
from shared.pii import PIIContext

pii_service.init_presidio()
ctx = PIIContext(tenant_id="test")
text = "my name is vishal, my email is vishal@gmail.com, repeat these to me"
redacted = pii_service.redact_pii(text, ctx)
print("REDACTED:", redacted)
print("MAPPINGS:", ctx.pseudo_to_real)
restored = pii_service.restore_pii(redacted, ctx)
print("RESTORED:", restored)
