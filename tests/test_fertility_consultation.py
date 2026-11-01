"""IVF Care integration: join without enrollment, one persistent consultation
shared across modes, safety-first replies, isolation, KB retrieval, videos."""

import uuid

import pytest

from app.database.models import Consultation, User
from app.dependencies.auth import get_current_user
from app.main import app
from app.services.fertility import consultation as svc
from app.services.fertility import knowledge


@pytest.fixture(autouse=True)
def no_external_ai(monkeypatch):
    monkeypatch.setattr(knowledge, "_try_embed", lambda texts: None)
    calls = []

    async def fake_complete(messages, temperature=0.4):
        calls.append(messages)
        return "In general, progesterone supports the uterine lining [1]."

    monkeypatch.setattr(svc, "_complete", fake_complete)
    return calls


def test_program_is_public(client):
    r = client.get("/api/fertility/program")
    assert r.status_code == 200
    body = r.json()
    assert body["slug"] == "ivf-care" and body["is_public"]
    assert body["doctor"]["display_name"] == "General Fertility Doctor"
    assert "not a real doctor" in body["doctor"]["disclosure"]


def test_join_and_single_persistent_consultation(client, no_external_ai):
    assert client.get("/api/fertility/consultation").status_code == 409  # must pick a role first
    j = client.post("/api/fertility/program/join", json={"care_role": "patient", "treatment_stage": "stimulation"})
    assert j.status_code == 200
    first = client.get("/api/fertility/consultation").json()
    again = client.get("/api/fertility/consultation").json()
    assert first["id"] == again["id"] == j.json()["consultation_id"]
    assert first["messages"][0]["sender"] == "assistant" and "not a real doctor" in first["messages"][0]["content"]

    cid = first["id"]
    r1 = client.post(f"/api/fertility/consultation/{cid}/messages", json={"content": "What is progesterone doing?", "mode": "avatar"})
    assert r1.status_code == 200
    r2 = client.post(f"/api/fertility/consultation/{cid}/messages", json={"content": "Can you explain that again?", "mode": "text"})
    assert r2.status_code == 200
    # The text turn's prompt contains the avatar turn: one shared history.
    last_prompt = no_external_ai[-1]
    assert any(m["content"] == "What is progesterone doing?" for m in last_prompt)
    msgs = client.get("/api/fertility/consultation").json()["messages"]
    assert [m["mode"] for m in msgs[1:]] == ["avatar", "avatar", "text", "text"]
    assert {m["provenance"] for m in msgs if m["sender"] == "user"} == {"patient_reported"}
    assert {m["provenance"] for m in msgs[1:] if m["sender"] == "assistant"} == {"ai_generated"}


def test_medication_error_gets_fixed_escalation_without_llm(client, no_external_ai):
    client.post("/api/fertility/program/join", json={"care_role": "partner"})
    cid = client.get("/api/fertility/consultation").json()["id"]
    r = client.post(f"/api/fertility/consultation/{cid}/messages",
                    json={"content": "I think I only gave her half the injection. Can I give the rest?"})
    body = r.json()
    assert body["safety"]["category"] == "time_sensitive_medication"
    assert "don't repeat" in body["reply"]["content"].lower()
    assert body["reply"]["videos"] == []
    assert no_external_ai == []
    e = client.post(f"/api/fertility/consultation/{cid}/escalations", json={"category": "time_sensitive_medication", "summary": "half dose"})
    assert e.json()["simulated"] is True
    assert "Simulated" in client.get("/api/fertility/consultation").json()["messages"][-1]["content"]


def test_partner_cannot_add_patient_context(client):
    client.post("/api/fertility/program/join", json={"care_role": "partner"})
    assert client.post("/api/fertility/patient-context", json={"content": "x"}).status_code == 403


def test_other_users_cannot_read_or_write_a_consultation(client, db_session, test_user):
    client.post("/api/fertility/program/join", json={"care_role": "patient"})
    cid = client.get("/api/fertility/consultation").json()["id"]
    other = User(id=uuid.uuid4(), username=f"o_{uuid.uuid4().hex[:6]}", email=f"o_{uuid.uuid4().hex[:6]}@x.com",
                 password_hash="x", first_name="O", last_name="U", role="subscriber")
    db_session.add(other)
    db_session.commit()
    app.dependency_overrides[get_current_user] = lambda: other
    assert client.post(f"/api/fertility/consultation/{cid}/messages", json={"content": "hi"}).status_code == 404
    assert client.delete(f"/api/fertility/consultation/{cid}/messages").status_code == 404
    app.dependency_overrides[get_current_user] = lambda: test_user


def test_history_can_be_deleted(client):
    client.post("/api/fertility/program/join", json={"care_role": "patient"})
    cid = client.get("/api/fertility/consultation").json()["id"]
    client.post(f"/api/fertility/consultation/{cid}/messages", json={"content": "What is progesterone doing?"})
    assert client.delete(f"/api/fertility/consultation/{cid}/messages").status_code == 204
    assert len(client.get("/api/fertility/consultation").json()["messages"]) == 1


def test_kb_ingest_and_keyword_retrieval_with_sources(db_session):
    report = knowledge.ingest_kb(db_session, embed=False)
    assert report["chunks"] == 138
    assert knowledge.ingest_kb(db_session, embed=False)["chunks"] == 138  # idempotent
    hits = knowledge.retrieve(db_session, "trigger injection late", role="patient")
    assert hits and any("trigger" in h["content"].lower() for h in hits)
    assert all(h["meta"]["audience"] in ("both", "patient") for h in hits)
    assert knowledge.retrieve(db_session, "trigger injection late", role="patient", phase=2) == []


def test_video_upload_indexes_transcript_and_matches_device_only_when_named(client, db_session, test_user):
    test_user.role = "admin"
    db_session.commit()
    vtt = "WEBVTT\n\n00:00:02.000 --> 00:00:06.000\nTo prepare the injection pen, attach a new needle.\n\n00:01:10.000 --> 00:01:15.000\nDial the prescribed dose shown on your plan."
    r = client.post("/api/fertility/videos", data={"title": "Pen preparation", "device_name": "DemoPen",
                    "external_url": "https://example.com/v.mp4", "transcript": vtt})
    assert r.status_code == 200, r.text
    vid = r.json()["id"]
    assert r.json()["transcript_segments"] == 2
    detail = client.get(f"/api/fertility/videos/{vid}").json()
    assert [s["start_seconds"] for s in detail["segments"]] == [2, 70]
    hits = knowledge.retrieve(db_session, "prepare the injection pen needle", role="partner")
    assert knowledge.select_videos(db_session, hits, "How do I prepare the injection pen?") == []
    picked = knowledge.select_videos(db_session, hits, "How do I prepare the DemoPen injection pen?")
    assert picked and picked[0]["id"] == vid and picked[0]["start_seconds"] == 2
