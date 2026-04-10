import asyncio
import sys
import os

# Add the app directory to sys.path to allow imports
sys.path.append(os.path.join(os.getcwd(), "app"))

from app.services import pii_service
from app.services.pii_service import PIIContext

async def test_pii():
    print("--- PII Service Verification ---")
    
    # Initialize Presidio
    await pii_service.warmup()
    
    ctx = PIIContext()
    session_id = "test-session-123"
    
    test_cases = [
        ("My name is John Doe and my email is john.doe@example.com", ["PERSON", "EMAIL_ADDRESS"]),
        ("Call me at 647-123-4567 or visit 123 Main St, Toronto.", ["PHONE_NUMBER", "LOCATION"]),
        ("I have a severe headache and high fever. I think I have COVID.", ["HEALTH_CONDITION"]),
        ("My credit card number is 4111-1111-1111-1111.", ["CREDIT_CARD"]),
    ]
    
    for text, expected_types in test_cases:
        print(f"\nOriginal: {text}")
        redacted = pii_service.redact_pii(text, ctx, session_id)
        print(f"Redacted: {redacted}")
        
        restored = pii_service.restore_pii(redacted, ctx, session_id)
        print(f"Restored: {restored}")
        
        display = pii_service.redact_for_display(redacted, ctx)
        print(f"Display:  {display}")
        
        if text == restored:
            print("✅ Restoration Success")
        else:
            print("❌ Restoration Failed")

if __name__ == "__main__":
    asyncio.run(test_pii())
