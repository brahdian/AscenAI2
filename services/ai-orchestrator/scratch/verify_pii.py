from app.utils.pii import redact_pii

test_cases = [
    ("Contact me at test@example.com", "Contact me at [EMAIL]"),
    ("My number is +1 555-0199", "My number is [PHONE]"),
    ("CC: 4111-2222-3333-4444", "CC: [CARD]"),
    ("SSN: 123-45-6789", "SSN: [SSN]"),
    ("Safe text without PII", "Safe text without PII"),
    (None, None),
    ("", ""),
]

def verify():
    print("Starting PII Redaction Verification...")
    passed = 0
    for input_text, expected in test_cases:
        result = redact_pii(input_text)
        if result == expected:
            print(f"✅ PASS: '{input_text}' -> '{result}'")
            passed += 1
        else:
            print(f"❌ FAIL: '{input_text}' -> got '{result}', expected '{expected}'")
    
    print(f"\nResults: {passed}/{len(test_cases)} passed.")

if __name__ == "__main__":
    verify()
