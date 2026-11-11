from fastapi.testclient import TestClient


def signed_in(app, name="Yann", password="correct horse"):
    """A test client signed in as the owner, as after the first start of the app."""
    c = TestClient(app)
    r = c.post("/api/auth/setup", json={"name": name, "password": password})
    assert r.status_code == 200, r.text
    return c
