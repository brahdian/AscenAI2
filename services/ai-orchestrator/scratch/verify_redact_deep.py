import sys
import os
import asyncio
from typing import Any

# Add current dir to path
sys.path.append(os.getcwd())

from app.services import pii_service

async def test_redact_deep():
    print("Pre-warming PII service...")
    await pii_service.warmup()
    
    test_data = {
        "user_id": "123",
        "nested": {
            "email": "john.doe@gmail.com",
            "phone": "Call me at 555-0199",
            "safe": "Nothing here"
        },
        "list": [
            "My name is John Connor",
            {"location": "I live in Los Angeles"}
        ],
        "tool_call": {
            "arguments": {
                "address": "123 Main St, New York"
            }
        }
    }
    
    print("\nOriginal Data:")
    import json
    print(json.dumps(test_data, indent=2))
    
    redacted = pii_service.redact_deep(test_data)
    
    print("\nRedacted Data:")
    print(json.dumps(redacted, indent=2))
    
    # Assertions
    assert "[EMAIL]" in redacted["nested"]["email"] or "ascenai.private" in redacted["nested"]["email"]
    # redact_deep uses redact() which uses labels like [EMAIL] by default (one-way)
    # wait, redact() returns strings with [TYPE]
    
    print("\nVerification successful!")

if __name__ == "__main__":
    asyncio.run(test_redact_deep())
