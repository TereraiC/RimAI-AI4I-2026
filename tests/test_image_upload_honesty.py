"""
Test for a real bug: the chat page had a working file-upload button
wired all the way to the backend (FormData with an 'image' field sent
to /api/chat), but the backend never read request.files at all —
an uploaded photo was silently discarded with zero acknowledgment to
the farmer, who would reasonably assume it had been analyzed.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import io


def test_image_attachment_gets_honest_acknowledgment(monkeypatch, tmp_path):
    fake_db = str(tmp_path / "image_test.db")
    import app as app_module
    monkeypatch.setattr(app_module, "DB", fake_db)
    app_module.init_db()

    client = app_module.app.test_client()
    client.post("/login", data={"username": "demo", "password": "rimai2026"})

    resp = client.post(
        "/api/chat",
        data={
            "message": "what pest is this?",
            "image": (io.BytesIO(b"fake image bytes"), "leaf.jpg"),
        },
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200
    reply = resp.get_json()["reply"]
    assert "under construction" in reply.lower()
    assert "haven't analyzed" in reply.lower() or "isn't available" in reply.lower()


def test_text_only_message_is_unaffected(monkeypatch, tmp_path):
    fake_db = str(tmp_path / "text_only_test.db")
    import app as app_module
    monkeypatch.setattr(app_module, "DB", fake_db)
    app_module.init_db()

    client = app_module.app.test_client()
    client.post("/login", data={"username": "demo", "password": "rimai2026"})

    resp = client.post("/api/chat", data={"message": "what fertilizer should I use?"})
    assert resp.status_code == 200
    reply = resp.get_json()["reply"]
    assert "under construction" not in reply.lower()
