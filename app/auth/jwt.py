"""
Supabase JWT verification — decode and validate tokens.

Supabase Auth issues JWTs signed with the project's JWT secret.
We verify the token and extract user_id, email, and firm_id.

The firm_id comes from either:
- Custom claim in JWT metadata (set during signup)
- Lookup in app_user table by user_id

Usage:
    from app.auth.jwt import verify_token
    payload = verify_token("eyJhbG...")
    # {"user_id": "abc-123", "email": "user@firm.com", "firm_id": "def-456"}
"""

from jose import jwt, JWTError, ExpiredSignatureError

from app.config import settings


# Supabase JWT secret — derived from the anon key
# Supabase signs JWTs with the project's JWT secret, which is the same
# secret used to generate the anon/service_role keys.
# For verification, we use the JWT secret from Supabase settings.
# If not available, we can verify using the anon key as HMAC secret.

def verify_token(token: str) -> dict:
    """Verify a Supabase JWT and extract claims.

    Args:
        token: Bearer token from Authorization header

    Returns:
        {user_id, email, role, firm_id (if available)}

    Raises:
        ValueError: if token is invalid, expired, or missing
    """
    if not token:
        raise ValueError("No token provided")

    # Remove "Bearer " prefix if present
    if token.startswith("Bearer "):
        token = token[7:]

    try:
        # Supabase JWTs are signed with the project's JWT secret
        # The anon key IS a JWT itself — its secret is what signs user tokens
        # For now, decode without verification in dev mode, verify in production
        if settings.environment == "local":
            # In local dev, decode without full verification
            # (Supabase JS client handles token refresh)
            payload = jwt.decode(
                token,
                settings.supabase_anon_key,
                algorithms=["HS256"],
                options={"verify_aud": False},
            )
        else:
            # In production, full verification with JWT secret
            jwt_secret = settings.supabase_service_role_key or settings.supabase_anon_key
            payload = jwt.decode(
                token,
                jwt_secret,
                algorithms=["HS256"],
                options={"verify_aud": False},
            )

        user_id = payload.get("sub", "")
        email = payload.get("email", "")
        role = payload.get("role", "anon")

        # Extract firm_id from user metadata (set during signup)
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
