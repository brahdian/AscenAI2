import time
from jose import jwt, JWTError

def generate_internal_token(secret_key: str, algorithm: str = "HS256", issuer: str = "internal-service") -> str:
    """
    Generate a short-lived (60s) JWT for inter-service authentication.
    """
    payload = {
        "iss": issuer,
        "sub": "internal-service-call",
        "iat": int(time.time()),
        "exp": int(time.time()) + 60,
    }
    return jwt.encode(payload, secret_key, algorithm=algorithm)


def verify_internal_token(token: str, secret_key: str, algorithm: str = "HS256") -> bool:
    """
    Verify a JWT for inter-service calls.
    Returns True if valid, False otherwise.
    """
    try:
        payload = jwt.decode(
            token, 
            secret_key, 
            algorithms=[algorithm]
        )
        return payload.get("sub") == "internal-service-call"
    except JWTError:
        return False
