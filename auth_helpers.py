import bcrypt

def verify_password(password, encoded_hash):
    """Fail closed on missing, malformed, or oversized bcrypt credentials."""
    if not isinstance(password, str) or not isinstance(encoded_hash, str):
        return False
    raw = password.encode("utf-8")
    if not raw or len(raw) > 72:
        return False
    try:
        return bcrypt.checkpw(raw, encoded_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False
