import sys
import os

# Add app directory to path
sys.path.append("/Users/visvasis/Home/Jamvant/AscenAI/services/api-gateway")

from app.utils.pii import mask_pii
from app.utils.dates import sanitize_for_csv

def test_pii_masking():
    data = {
        "user": {
            "email": "test@example.com",
            "phone": "555-123-4567",
            "metadata": {
                "secret_key": "sk_test_123456789",
                "nested": {
                    "password": "supersecretpassword"
                }
            }
        },
        "id": "trc_abcdef1234567890"
    }
    
    masked = mask_pii(data, deep=True)
    print("PII Masking Result:")
    import json
    print(json.dumps(masked, indent=2))
    
    # Assertions
    assert "t***@***.com" in str(masked)
    assert "[REDACTED_PHONE]" in str(masked)
    assert "sk_test_***" in str(masked)
    assert "[REDACTED]" in str(masked)
    assert "trc_***7890" in str(masked)
    print("PII Masking Assertions Passed!")

def test_csv_sanitization():
    unsafe = ["=SUM(A1:A10)", "+123", "-456", "@IMPORT"]
    safe = [sanitize_for_csv(x) for x in unsafe]
    print("\nCSV Sanitization Result:")
    for u, s in zip(unsafe, safe):
        print(f"'{u}' -> '{s}'")
        assert s.startswith("'")
    
    normal = "Hello World"
    assert sanitize_for_csv(normal) == "Hello World"
    print("CSV Sanitization Assertions Passed!")

if __name__ == "__main__":
    try:
        test_pii_masking()
        test_csv_sanitization()
        print("\nALL TESTS PASSED")
    except Exception as e:
        print(f"\nTEST FAILED: {e}")
        sys.exit(1)
