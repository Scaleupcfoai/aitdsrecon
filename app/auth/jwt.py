"""
Supabase JWT verification — decode and validate tokens.

Supabase Auth issues JWTs signed with an EC key (ES256).
We verify using the project's public key directly.

Usage:
    from app.auth.jwt import verify_token
    payload = verify_token("eyJhbG...")
    # {"user_id": "abc-123", "email": "user@firm.com", "firm_id": "def-456"}
"""

from jose import jwt, JWTError, ExpiredSignatureError


# EC public key from Supabase Dashboard → Settings → API → JWT
SUPABASE_PUBLIC_KEY = {
    "x": "bacDFZDYNrPoJBE-pwfIXU4nDZGZTKqUBhCVBUhd3nY",
    "y": "khB9vF4L5DsZr9FXTqq-urCR3VBlZJw2oYsXFl-QKEY",
    "alg": "ES256",
    "crv": "P-256",
    "ext": True,
    "kid": "72a802eb-374b-4a8c-b8a2-e9a102e3122d",
    "kty": "EC",
    "key_ops": ["verify"],
}


def verify_token(token: str) -> dict:
    """Verify a Supabase JWT and extract claims.

    Args:
        token: Bearer token from Authorization header (with or without 'Bearer ' prefix)

    Returns:
        {user_id, email, role, firm_id (if available), raw_claims}

    Raises:
        ValueError: if token is invalid, expired, or missing
    """
    if not token:
        raise ValueError("No token provided")

    # Remove "Bearer " prefix if present
    if token.startswith("Bearer "):
        token = token[7:]

    try:
        payload = jwt.decode(
            token,
            SUPABASE_PUBLIC_KEY,
            algorithms=["ES256"],
            options={"verify_aud": False},
        )

        user_id = payload.get("sub", "")
        email = payload.get("email", "")
        role = payload.get("role", "anon")

        # Extract firm_id from user metadata (set during firm registration)
        user_metadata = payload.get("user_metadata", {})
        firm_id = user_metadata.get("firm_id", "")

        if not user_id:
            raise ValueError("Token missing user ID (sub claim)")

        return {
            "user_id": user_id,
            "email": email,
            "role": role,
            "firm_id": firm_id,
            "raw_claims": payload,
        }

    except ExpiredSignatureError:
        raise ValueError("Token expired — please login again")
    except JWTError as e:
        raise ValueError(f"Invalid token: {str(e)}")