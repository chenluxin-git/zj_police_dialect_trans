def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok"}

def test_password_and_token_roundtrip():
    from app.core.security import hash_password, verify_password, create_token, decode_token
    h = hash_password("123456")
    assert verify_password("123456", h) and not verify_password("000000", h)
    assert decode_token(create_token("42")) == "42"
