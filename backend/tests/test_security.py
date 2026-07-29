from __future__ import annotations

import jwt
import pytest

from app.core.security import (
    create_token,
    decode_token,
    generate_agent_public_key,
    generate_agent_secret_key,
    hash_password,
    verify_password,
    verify_secret_key,
)


def test_password_roundtrip():
    hashed = hash_password("correct horse battery staple")
    assert hashed != "correct horse battery staple"
    assert verify_password("correct horse battery staple", hashed)
    assert not verify_password("wrong password", hashed)


def test_same_password_gets_a_different_salt_each_time():
    assert hash_password("hunter2") != hash_password("hunter2")


def test_passwords_longer_than_bcrypts_72_byte_limit_stay_distinct():
    """Without the SHA-256 pre-hash, bcrypt truncates at 72 bytes and these two
    would verify against each other."""
    base = "A" * 80
    hashed = hash_password(base + "first")
    assert verify_password(base + "first", hashed)
    assert not verify_password(base + "second", hashed)


def test_malformed_hash_is_rejected_rather_than_raising():
    assert verify_password("anything", "not-a-bcrypt-hash") is False


def test_access_token_roundtrip():
    token = create_token("user-123", "access")
    payload = decode_token(token, expected_type="access")
    assert payload["sub"] == "user-123"
    assert payload["type"] == "access"


def test_token_type_confusion_is_rejected():
    """A refresh token must not be usable where an access token is expected."""
    refresh = create_token("user-123", "refresh")
    with pytest.raises(jwt.InvalidTokenError):
        decode_token(refresh, expected_type="access")


def test_extra_claims_cannot_overwrite_registered_claims():
    token = create_token("real-user", "access", extra_claims={"sub": "attacker", "role": "owner"})
    payload = decode_token(token)
    assert payload["sub"] == "real-user"
    assert payload["role"] == "owner"


def test_tampered_token_is_rejected():
    token = create_token("user-123", "access")
    head, body, sig = token.split(".")
    with pytest.raises(jwt.PyJWTError):
        decode_token(f"{head}.{body}.{sig[:-2]}xy")


def test_agent_public_keys_are_prefixed_and_unique():
    keys = {generate_agent_public_key() for _ in range(100)}
    assert len(keys) == 100
    assert all(k.startswith("agt_pub_") for k in keys)
    assert all(len(k) <= 80 for k in keys)  # fits the String(80) column


def test_agent_secret_key_verifies_against_its_hash_only():
    plaintext, stored = generate_agent_secret_key()
    assert plaintext not in stored
    assert verify_secret_key(plaintext, stored)
    assert not verify_secret_key(plaintext + "x", stored)
