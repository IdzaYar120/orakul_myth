"""HTTP API (FastAPI): encyclopedia, map, oracle (local/remote/off), SSE, token, rate limit."""

import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from delphi.api.app import create_app
from delphi.api.oracle_backends import TOKEN_HEADER, LocalOracle, OffOracle, RemoteOracle
from delphi.api.ratelimit import RateLimiter
from delphi.config import settings
from delphi.rag.prompts import REFUSAL_PHRASE_EN
from tests.test_oracle_service import PASSAGES, _oracle


def _sse_events(body: str) -> list[tuple[str, dict]]:
    events = []
    for block in body.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        events.append((lines["event"], json.loads(lines["data"])))
    return events


@pytest.fixture
def client(seeded_default_db: Path, seeded_session: Session) -> TestClient:
    oracle = LocalOracle(_oracle(seeded_session, PASSAGES, responses=["Син Зевса і Лето [1]."]))
    return TestClient(create_app(oracle=oracle, limiter=RateLimiter(100)))


# ---------------------------------------------------------------------- service
def test_health_and_meta(client: TestClient):
    health = client.get("/api/health").json()
    assert health["status"] == "ok" and health["entities"] > 100 and health["places"] > 50
    assert health["oracle"]["mode"] == "local"

    uk = client.get("/api/meta").json()
    en = client.get("/api/meta", params={"lang": "en"}).json()
    assert uk["labels"]["entity_types"]["god"] == "Бог / божество"
    assert en["labels"]["entity_types"]["god"] == "God / deity"
    assert [s["id"] for s in en["styles"]] == ["pythia", "scholar"]
    assert en["langs"] == ["uk", "en"]


def test_openapi_lists_the_endpoints(client: TestClient):
    paths = client.get("/api/openapi.json").json()["paths"]
    for path in ("/api/entities/{entity_id}", "/api/map/layer", "/api/oracle/stream"):
        assert path in paths


# ---------------------------------------------------------------------- encyclopedia
def test_entities_search_list_and_card(client: TestClient):
    found = client.get("/api/entities", params={"q": "Зевс"}).json()
    assert found[0]["id"] == "zeus"
    gods = client.get("/api/entities", params={"type": "god", "limit": 500}).json()
    assert gods and all(g["type"] == "god" for g in gods)

    card = client.get("/api/entities/zeus").json()
    assert card["name_en"] == "Zeus" and card["lineage"]["children"]
    missing = client.get("/api/entities/no-such-god")
    assert missing.status_code == 404 and missing.json()["detail"]["code"] == "not_found"


def test_myths(client: TestClient):
    myths = client.get("/api/myths").json()
    assert len(myths) > 20 and all(m["participants"] for m in myths)
    argonauts = client.get("/api/myths", params={"cycle": "argonauts"}).json()
    assert argonauts and {m["cycle"] for m in argonauts} == {"argonauts"}


# ---------------------------------------------------------------------- map
def test_map_layer_filters_and_nearest(client: TestClient):
    layer = client.get("/api/map/layer").json()
    assert len(layer["markers"]) > 50 and layer["off_map"]
    sanctuaries = client.get("/api/map/layer", params={"kinds": ["sanctuary"]}).json()
    assert {m["place_kind"] for m in sanctuaries["markers"]} == {"sanctuary"}
    filters = client.get("/api/map/filters").json()
    assert filters["routes"] and filters["gods"]

    delphi = next(m for m in layer["markers"] if m["entity_id"] == "delphi")
    near = client.get("/api/map/nearest", params={"lat": delphi["lat"], "lon": delphi["lon"]})
    assert near.json() == {"entity_id": "delphi"}
    assert client.get("/api/map/nearest", params={"lat": 100, "lon": 0}).status_code == 422


# ---------------------------------------------------------------------- oracle: local
def test_oracle_ask(client: TestClient):
    answer = client.post(
        "/api/oracle/ask", json={"question": "Хто батьки Аполлона?", "style": "scholar"}
    ).json()
    assert answer["text"] == "Син Зевса і Лето [1]."
    assert answer["grounded"] and answer["lang"] == "uk" and not answer["refused"]
    assert answer["citations"][0]["cited"] and answer["citations"][0]["entity_ids"]


def test_oracle_stream_sends_meta_tokens_done(client: TestClient):
    resp = client.post("/api/oracle/stream", json={"question": "Хто батьки Аполлона?"})
    assert resp.status_code == 200 and resp.headers["content-type"].startswith("text/event-stream")
    events = _sse_events(resp.text)
    kinds = [e for e, _ in events]
    assert kinds[0] == "meta" and kinds[-1] == "done" and "token" in kinds
    meta, done = events[0][1], events[-1][1]
    assert len(meta["citations"]) == 2  # sources arrive before the answer
    assert "".join(d["text"] for e, d in events if e == "token") == done["text"]


def test_oracle_english_refusal(seeded_default_db: Path, seeded_session: Session):
    client = TestClient(create_app(oracle=LocalOracle(_oracle(seeded_session, []))))
    answer = client.post(
        "/api/oracle/ask", json={"question": "What is Zeus's phone number?", "lang": "en"}
    ).json()
    assert answer["refused"] and answer["lang"] == "en"
    assert answer["text"].startswith(REFUSAL_PHRASE_EN)


def test_oracle_validates_input(client: TestClient):
    too_long = "?" * (settings.max_question_chars + 1)
    assert client.post("/api/oracle/ask", json={"question": too_long}).status_code == 422
    assert client.post("/api/oracle/ask", json={"question": "   "}).status_code == 422
    bad_lang = {"question": "Хто?", "lang": "fr"}
    assert client.post("/api/oracle/ask", json=bad_lang).status_code == 422


def test_oracle_rate_limit(seeded_default_db: Path, seeded_session: Session):
    oracle = LocalOracle(_oracle(seeded_session, PASSAGES, responses=["Так [1]."] * 3))
    client = TestClient(create_app(oracle=oracle, limiter=RateLimiter(1)))
    assert client.post("/api/oracle/ask", json={"question": "Хто?"}).status_code == 200
    second = client.post("/api/oracle/ask", json={"question": "Хто?"})
    assert second.status_code == 429 and second.json()["detail"]["code"] == "rate_limited"


def test_oracle_token_protects_an_exposed_backend(
    seeded_default_db: Path, seeded_session: Session, monkeypatch
):
    monkeypatch.setattr(settings, "oracle_token", "s3cret")
    oracle = LocalOracle(_oracle(seeded_session, PASSAGES, responses=["Так [1]."] * 5))
    client = TestClient(create_app(oracle=oracle, limiter=RateLimiter(1)))
    assert client.post("/api/oracle/ask", json={"question": "Хто?"}).status_code == 401
    wrong = {TOKEN_HEADER: "nope"}
    assert (
        client.post("/api/oracle/ask", json={"question": "Хто?"}, headers=wrong).status_code == 401
    )
    ok = {TOKEN_HEADER: "s3cret"}
    for _ in range(3):  # trusted upstream: not rate-limited per IP
        assert (
            client.post("/api/oracle/ask", json={"question": "Хто?"}, headers=ok).status_code == 200
        )
    # the encyclopedia stays public
    assert client.get("/api/entities/zeus").status_code == 200


# ---------------------------------------------------------------------- oracle: remote/off
def _remote(handler) -> RemoteOracle:
    return RemoteOracle("http://pc.example", token="s3cret", transport=httpx.MockTransport(handler))


def test_remote_oracle_forwards_with_token(seeded_default_db: Path):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/api/health":
            return httpx.Response(200, json={"oracle": {"available": True, "model": "mamay"}})
        if request.url.path == "/api/oracle/ask":
            return httpx.Response(200, json={"text": "Відповідь [1].", "lang": "uk"})
        body = 'event: done\ndata: {"text": "Відповідь"}\n\n'
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

    client = TestClient(create_app(oracle=_remote(handler)))
    assert client.get("/api/health").json()["oracle"] == {
        "mode": "remote",
        "available": True,
        "model": "mamay",
        "detail": None,
    }
    assert client.post("/api/oracle/ask", json={"question": "Хто?"}).json()["text"] == (
        "Відповідь [1]."
    )
    events = _sse_events(client.post("/api/oracle/stream", json={"question": "Хто?"}).text)
    assert events == [("done", {"text": "Відповідь"})]
    assert all(r.headers[TOKEN_HEADER] == "s3cret" for r in seen)


def test_remote_oracle_unreachable(seeded_default_db: Path):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("the PC is off")

    client = TestClient(create_app(oracle=_remote(handler)))
    assert client.get("/api/health").json()["oracle"]["available"] is False
    resp = client.post("/api/oracle/ask", json={"question": "Хто?", "lang": "en"})
    assert resp.status_code == 503
    assert resp.json()["detail"]["message"].startswith("The Pythia is silent")
    events = _sse_events(client.post("/api/oracle/stream", json={"question": "Хто?"}).text)
    assert events[0][0] == "error" and events[0][1]["code"] == "oracle_unavailable"
    # the encyclopedia and the map do not depend on the oracle
    assert client.get("/api/map/filters").status_code == 200


def test_oracle_off(seeded_default_db: Path):
    client = TestClient(create_app(oracle=OffOracle()))
    resp = client.post("/api/oracle/ask", json={"question": "Хто?"})
    assert resp.status_code == 503 and resp.json()["detail"]["message"].startswith("Піфія")
    assert client.get("/api/meta").json()["oracle_mode"] == "off"


def test_rate_limiter_window():
    limiter = RateLimiter(2, window_seconds=10)
    assert limiter.allow("a", now=0) and limiter.allow("a", now=1)
    assert not limiter.allow("a", now=2) and limiter.allow("b", now=2)
    assert limiter.allow("a", now=10.5)  # the first hit left the window
    assert RateLimiter(0).allow("x")  # 0 = unlimited


def test_cli_openapi(tmp_path: Path):
    from typer.testing import CliRunner

    from delphi.cli import app as cli_app

    out = tmp_path / "openapi.json"
    res = CliRunner().invoke(cli_app, ["openapi", "--out", str(out)])
    assert res.exit_code == 0, res.output
    assert "/api/oracle/ask" in json.loads(out.read_text(encoding="utf-8"))["paths"]
