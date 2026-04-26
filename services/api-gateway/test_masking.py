import sys
import os
sys.path.append(os.path.join(os.getcwd(), 'app'))
from app.services.audit_service import mask_sensitive_data

test_data = {
    "user": "alice",
    "password": "secret-password",
    "meta": {
        "api_key": "sk_live_123456789",
        "nested": {
            "token": "bearer-token-here"
        }
    },
    "items": [
        {"id": 1, "secret": "abc"},
        {"id": 2, "normal": "value"}
    ]
}

masked = mask_sensitive_data(test_data)
import json
print(json.dumps(masked, indent=2))
