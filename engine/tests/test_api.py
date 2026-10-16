"""HTTP API (Tauri sidecar) tests: TestClient + fake translator / fake complete_fn, no AI."""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from rosetta_engine.api import create_app
from rosetta_engine.api.confirm import ConfirmStore
from rosetta_engine.api.errors import ApiError
from rosetta_engine.config import Settings
from rosetta_engine.translate.base import ProviderResult, TranslationRequest
from rosetta_engine.translate.claude_cli import Completion
from rosetta_engine.translate.fake import FakeTranslator

TOKEN = "secret-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}

PROFILE_JSON = {
    "tur": "yazılım / dağıtık sistemler",
    "ton": "teknik ama akıcı",
    "hedef_dil": "tr",
    "cevrilmeyecek": ["Kafka"],
    "sozluk": {"replication": "replikasyon", "latency": "gecikme"},
    "kod_dili": ["SQL"],
}
EXPLAIN_JSON = {
    "ceviri": "Replikasyon, verinin kopyasını tutmak demektir.",
    "yapi": "Basit bir yüklem cümlesi.",
    "deyimler": [],
    "kelimeler": [{"kelime": "replication", "anlam": "replikasyon"}],
    "notlar": "",
}


class FakeComplete:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def __call__(self, system_prompt: str, user_message: str, **_: Any) -> Completion:
        self.calls.append(system_prompt)
        payload = PROFILE_JSON if "sozluk" in system_prompt else EXPLAIN_JSON
        return Completion(json.dumps(payload), None, 500, 200, 0.004)


class Translators:
    """Translator factory whose behaviour tests can swap; records every created translator."""

    def __init__(self) -> None:
        self.make: Callable[[], Any] = FakeTranslator
        self.created: list[Any] = []

    def __call__(self, provider: str, model: str | None, settings: Settings) -> Any:
        t = self.make()
        self.created.append(t)
        return t

    @property
    def calls(self) -> int:
        return sum(len(t.calls) for t in self.created)


class GateTranslator(FakeTranslator):
    """Blocks every call until the test opens the gate (to pause a running job)."""

    def __init__(self, gate: threading.Event, entered: threading.Event) -> None:
        super().__init__()
        self.gate = gate
        self.entered = entered

    def translate(self, request: TranslationRequest, *, strict: bool = False) -> ProviderResult:
        self.entered.set()
        assert self.gate.wait(10)
        return super().translate(request, strict=strict)


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("ROSETTA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ROSETTA_CONFIG_DIR", str(tmp_path / "cfg"))
    return tmp_path


@pytest.fixture
def translators() -> Translators:
    return Translators()


@pytest.fixture
def completer() -> FakeComplete:
    return FakeComplete()


@pytest.fixture
def make_client(
    env: Path, translators: Translators, completer: FakeComplete
) -> Iterator[Callable[..., TestClient]]:
    clients: list[TestClient] = []

    def make(settings: Settings | None = None, confirm: ConfirmStore | None = None) -> TestClient:
        app = create_app(
            settings or Settings(provider="fake", model="fake", batch_max_pages=1),
            token=TOKEN,
            translator_factory=translators,
            complete_fn=completer,
            confirm=confirm,
        )
        c = TestClient(app)
        c.__enter__()
        clients.append(c)
        return c

    yield make
    for c in clients:
        c.__exit__(None, None, None)


@pytest.fixture
def client(make_client: Callable[..., TestClient]) -> TestClient:
    return make_client()


def ok(r: Any, status: int = 200) -> Any:
    assert r.status_code == status, r.text
    return r.json() if r.content else None


def err(r: Any, kind: str, status: int) -> None:
    assert r.status_code == status, r.text
    assert r.json()["error"]["kind"] == kind


def open_book(client: TestClient, pdf: Path) -> dict[str, Any]:
    return ok(client.post("/api/books/open", json={"path": str(pdf)}, headers=AUTH))


def wait_job(client: TestClient, job_id: int, statuses: set[str], timeout: float = 10) -> Any:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        j = ok(client.get(f"/api/jobs/{job_id}", headers=AUTH))
        if j["status"] in statuses:
            return j
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} never reached {statuses}: {j}")


# --- auth, CORS, errors ------------------------------------------------------------------------


def test_requires_token(client: TestClient) -> None:
    err(client.get("/api/health"), "unauthorized", 401)
    err(client.get("/api/health", headers={"Authorization": "Bearer nope"}), "unauthorized", 401)
    err(client.get(f"/api/health?token={TOKEN}"), "unauthorized", 401)  # only assets
    assert ok(client.get("/api/health", headers=AUTH))["ok"] is True


def test_empty_token_rejected(env: Path) -> None:
    with pytest.raises(ValueError):
        create_app(Settings(), token="")


def test_cors_allows_only_app_origins(client: TestClient) -> None:
    pre = {
        "Access-Control-Request-Method": "GET",
        "Access-Control-Request-Headers": "authorization",
    }
    good = client.options("/api/health", headers={"Origin": "http://localhost:1420", **pre})
    assert good.headers.get("access-control-allow-origin") == "http://localhost:1420"
    tauri = client.get("/api/health", headers={"Origin": "tauri://localhost", **AUTH})
    assert tauri.headers.get("access-control-allow-origin") == "tauri://localhost"
    evil = client.options("/api/health", headers={"Origin": "https://evil.example", **pre})
    assert "access-control-allow-origin" not in evil.headers


def test_error_shapes(client: TestClient, book_pdf: Path) -> None:
    err(client.get("/api/books/999", headers=AUTH), "not_found", 404)
    err(client.get("/api/nope", headers=AUTH), "not_found", 404)
    err(
        client.post("/api/books/open", json={"path": "/no/such.pdf"}, headers=AUTH),
        "bad_request",
        400,
    )
    err(client.post("/api/books/open", json={}, headers=AUTH), "bad_request", 400)
    book = open_book(client, book_pdf)
    err(client.get(f"/api/books/{book['id']}/pages/99/blocks", headers=AUTH), "bad_request", 400)


# --- books and pages --------------------------------------------------------------------------


def test_open_book_toc_and_blocks(client: TestClient, book_pdf: Path) -> None:
    book = open_book(client, book_pdf)
    assert book["page_count"] == 3
    assert book["path"] == str(book_pdf)
    assert ok(client.get(f"/api/books/{book['id']}", headers=AUTH))["id"] == book["id"]
    toc = ok(client.get(f"/api/books/{book['id']}/toc", headers=AUTH))
    assert toc == [{"level": 1, "title": "Chapter 5. Replication", "page": 1}]

    blocks = ok(client.get(f"/api/books/{book['id']}/pages/1/blocks", headers=AUTH))
    assert blocks["page"] == 1 and blocks["has_text_layer"] is True
    types = {b["type"] for b in blocks["blocks"]}
    assert {"heading", "paragraph", "code"} <= types
    code = next(b for b in blocks["blocks"] if b["type"] == "code")
    assert code["translatable"] is False and code["translated"] is False
    assert all(len(b["bbox"]) == 4 for b in blocks["blocks"])

    html = ok(client.get(f"/api/books/{book['id']}/pages/1/html?mode=tr", headers=AUTH))
    for b in blocks["blocks"]:
        if b["type"] not in {"furniture", "footnote"}:
            assert f'data-block="{b["key"]}"' in html["html"]
    assert html["html"].startswith("<main") and "<script" not in html["html"]
    assert "<html" not in html["html"] and "<link" not in html["html"]
    assert html["translated_blocks"] == 0 and html["translatable_blocks"] > 0


def test_book_reopens_after_restart(make_client: Callable[..., TestClient], book_pdf: Path) -> None:
    first = make_client()
    book = open_book(first, book_pdf)
    second = make_client()  # new server process state, same DB
    assert ok(second.get(f"/api/books/{book['id']}/toc", headers=AUTH))


def test_assets_need_token_and_block_traversal(
    client: TestClient, book_pdf: Path, env: Path
) -> None:
    book = open_book(client, book_pdf)
    html = ok(client.get(f"/api/books/{book['id']}/pages/1/html", headers=AUTH))["html"]
    assert 'src="assets/' in html
    name = html.split('src="assets/', 1)[1].split('"', 1)[0]
    url = f"/api/books/{book['id']}/assets/{name}"
    err(client.get(url), "unauthorized", 401)
    r = client.get(f"{url}?token={TOKEN}")
    assert r.status_code == 200 and r.content.startswith(b"\x89PNG")
    assert client.get(url, headers=AUTH).status_code == 200
    (env / "data" / "secret.png").write_bytes(b"x")
    for bad in ("..%2F..%2Fsecret.png", "..%2F..%2Frosetta.db", "%2Fetc%2Fpasswd", "x.txt"):
        err(client.get(f"/api/books/{book['id']}/assets/{bad}?token={TOKEN}"), "not_found", 404)


# --- translation ------------------------------------------------------------------------------


def test_translate_flow_and_cache(
    client: TestClient, book_pdf: Path, translators: Translators
) -> None:
    book = open_book(client, book_pdf)
    bid = book["id"]
    est = ok(client.post(f"/api/books/{bid}/estimate", json={"pages": [1, 2]}, headers=AUTH))
    assert est["operation"] == "translate" and est["calls"] >= 2
    assert est["pages"] == [1, 2] and est["cached_blocks"] == 0 and est["expires_in"] == 600
    assert est["provider"] == "fake" and est["supports_profile"] is True
    assert translators.calls == 0  # estimate never calls the provider

    rep = ok(
        client.post(
            f"/api/books/{bid}/translate",
            json={"confirm_token": est["confirm_token"]},
            headers=AUTH,
        )
    )
    assert rep["done_pages"] == [1, 2] and rep["failed_pages"] == {} and rep["stop_kind"] is None
    calls = translators.calls
    assert calls >= 2

    # the token is one-shot
    err(
        client.post(
            f"/api/books/{bid}/translate",
            json={"confirm_token": est["confirm_token"]},
            headers=AUTH,
        ),
        "expired_token",
        409,
    )
    again = ok(client.post(f"/api/books/{bid}/estimate", json={"pages": [1, 2]}, headers=AUTH))
    assert again["calls"] == 0 and again["cached_blocks"] == again["total_blocks"]
    ok(
        client.post(
            f"/api/books/{bid}/translate",
            json={"confirm_token": again["confirm_token"]},
            headers=AUTH,
        )
    )
    assert translators.calls == calls  # cache: no second call

    blocks = ok(client.get(f"/api/books/{bid}/pages/1/blocks", headers=AUTH))
    assert any(b["translated"] for b in blocks["blocks"])
    html = ok(client.get(f"/api/books/{bid}/pages/1/html?mode=review", headers=AUTH))
    assert "[TR]" in html["html"] and html["translated_blocks"] == html["translatable_blocks"]
    usage = ok(client.get(f"/api/usage?book_id={bid}", headers=AUTH))
    assert usage["calls"] == calls


def test_translation_text_is_escaped(
    client: TestClient, book_pdf: Path, translators: Translators
) -> None:
    translators.make = lambda: FakeTranslator(prefix="<script>alert(1)</script><b>")
    bid = open_book(client, book_pdf)["id"]
    est = ok(client.post(f"/api/books/{bid}/estimate", json={"pages": [1]}, headers=AUTH))
    ok(
        client.post(
            f"/api/books/{bid}/translate",
            json={"confirm_token": est["confirm_token"]},
            headers=AUTH,
        )
    )
    html = ok(client.get(f"/api/books/{bid}/pages/1/html?mode=tr", headers=AUTH))["html"]
    assert "&lt;script&gt;alert(1)&lt;/script&gt;&lt;b&gt;" in html
    assert "<script" not in html and "<b>" not in html


def test_estimate_rejects_bad_pages(client: TestClient, book_pdf: Path) -> None:
    bid = open_book(client, book_pdf)["id"]
    for pages in ([], [0], [4]):
        err(
            client.post(f"/api/books/{bid}/estimate", json={"pages": pages}, headers=AUTH),
            "bad_request",
            400,
        )


def test_token_bound_to_book(
    client: TestClient, book_pdf: Path, two_column_pdf: Path, translators: Translators
) -> None:
    a = open_book(client, book_pdf)["id"]
    b = open_book(client, two_column_pdf)["id"]
    est = ok(client.post(f"/api/books/{a}/estimate", json={"pages": [1]}, headers=AUTH))
    err(
        client.post(
            f"/api/books/{b}/translate", json={"confirm_token": est["confirm_token"]}, headers=AUTH
        ),
        "expired_token",
        409,
    )
    assert translators.calls == 0


def test_token_expires(
    make_client: Callable[..., TestClient], book_pdf: Path, translators: Translators
) -> None:
    now = [1000.0]
    client = make_client(confirm=ConfirmStore(ttl_s=600, clock=lambda: now[0]))
    bid = open_book(client, book_pdf)["id"]
    est = ok(client.post(f"/api/books/{bid}/estimate", json={"pages": [1]}, headers=AUTH))
    now[0] += 601
    err(
        client.post(
            f"/api/books/{bid}/translate",
            json={"confirm_token": est["confirm_token"]},
            headers=AUTH,
        ),
        "expired_token",
        409,
    )
    assert translators.calls == 0


def test_confirm_store_scope_mismatch() -> None:
    store = ConfirmStore()
    token = store.issue("translate", "book:1", "plan")
    with pytest.raises(ApiError) as e:
        store.take(token, "explain", "book:1")
    assert e.value.kind == "expired_token"
    with pytest.raises(ApiError):
        store.take(token, "translate", "book:1")  # consumed by the failed attempt


@pytest.mark.parametrize(
    "path",
    [
        "/api/books/{bid}/translate",
        "/api/jobs",
        "/api/jobs/1/resume",
        "/api/jobs/1/retry-failed",
        "/api/books/{bid}/profile/analyze",
        "/api/explain",
    ],
)
@pytest.mark.parametrize("token", [None, "", "forged"])
def test_every_ai_endpoint_requires_confirm_token(
    client: TestClient,
    book_pdf: Path,
    translators: Translators,
    completer: FakeComplete,
    path: str,
    token: str | None,
) -> None:
    bid = open_book(client, book_pdf)["id"]
    body = {} if token is None else {"confirm_token": token}
    err(client.post(path.format(bid=bid), json=body, headers=AUTH), "expired_token", 409)
    assert translators.calls == 0 and completer.calls == []


# --- jobs -------------------------------------------------------------------------------------


def test_job_runs_in_background(client: TestClient, book_pdf: Path) -> None:
    bid = open_book(client, book_pdf)["id"]
    est = ok(
        client.post(
            f"/api/books/{bid}/jobs/estimate", json={"all": True, "budget_usd": 2}, headers=AUTH
        )
    )
    assert est["operation"] == "job" and est["pages"] == [1, 2, 3]
    started = ok(
        client.post("/api/jobs", json={"confirm_token": est["confirm_token"]}, headers=AUTH)
    )
    assert started["pages"] == [1, 2, 3] and started["budget_usd"] == 2
    done = wait_job(client, started["id"], {"done"})
    assert done["done_pages"] == [1, 2, 3] and done["failed_pages"] == {}
    listed = ok(client.get(f"/api/jobs?book_id={bid}", headers=AUTH))
    assert [j["id"] for j in listed] == [started["id"]]
    err(client.post(f"/api/jobs/{started['id']}/resume/estimate", headers=AUTH), "bad_request", 400)
    err(client.get("/api/jobs/999", headers=AUTH), "not_found", 404)


def test_job_pause_and_resume(client: TestClient, book_pdf: Path, translators: Translators) -> None:
    gate, entered = threading.Event(), threading.Event()
    translators.make = lambda: GateTranslator(gate, entered)
    bid = open_book(client, book_pdf)["id"]
    est = ok(
        client.post(f"/api/books/{bid}/jobs/estimate", json={"pages": [1, 2, 3]}, headers=AUTH)
    )
    job = ok(client.post("/api/jobs", json={"confirm_token": est["confirm_token"]}, headers=AUTH))
    assert entered.wait(10)
    ok(client.post(f"/api/jobs/{job['id']}/pause", headers=AUTH))
    # a second job can't start while one is running
    other = ok(client.post(f"/api/books/{bid}/jobs/estimate", json={"pages": [3]}, headers=AUTH))
    err(
        client.post("/api/jobs", json={"confirm_token": other["confirm_token"]}, headers=AUTH),
        "unavailable",
        503,
    )
    gate.set()
    paused = wait_job(client, job["id"], {"paused"})
    assert paused["done_pages"] and len(paused["done_pages"]) < 3

    translators.make = FakeTranslator
    res = ok(client.post(f"/api/jobs/{job['id']}/resume/estimate", headers=AUTH))
    assert set(res["pages"]) == set(range(1, 4)) - set(paused["done_pages"])
    ok(
        client.post(
            f"/api/jobs/{job['id']}/resume",
            json={"confirm_token": res["confirm_token"]},
            headers=AUTH,
        )
    )
    finished = wait_job(client, job["id"], {"done"})
    assert finished["done_pages"] == [1, 2, 3]


def test_job_retry_failed_and_cancel(
    client: TestClient, book_pdf: Path, translators: Translators
) -> None:
    translators.make = lambda: FakeTranslator(fail_mode="invalid")
    bid = open_book(client, book_pdf)["id"]
    est = ok(client.post(f"/api/books/{bid}/jobs/estimate", json={"pages": [2]}, headers=AUTH))
    job = ok(client.post("/api/jobs", json={"confirm_token": est["confirm_token"]}, headers=AUTH))
    failed = wait_job(client, job["id"], {"failed"})
    assert list(failed["failed_pages"]) == ["2"]

    translators.make = FakeTranslator
    retry = ok(client.post(f"/api/jobs/{job['id']}/retry-failed/estimate", headers=AUTH))
    assert retry["pages"] == [2]
    # a resume token can't be used for retry
    res = client.post(
        f"/api/jobs/{job['id']}/retry-failed",
        json={"confirm_token": "x" + retry["confirm_token"]},
        headers=AUTH,
    )
    err(res, "expired_token", 409)
    ok(
        client.post(
            f"/api/jobs/{job['id']}/retry-failed",
            json={"confirm_token": retry["confirm_token"]},
            headers=AUTH,
        )
    )
    assert wait_job(client, job["id"], {"done"})["done_pages"] == [2]

    est2 = ok(client.post(f"/api/books/{bid}/jobs/estimate", json={"pages": [3]}, headers=AUTH))
    gate, entered = threading.Event(), threading.Event()
    translators.make = lambda: GateTranslator(gate, entered)
    job2 = ok(client.post("/api/jobs", json={"confirm_token": est2["confirm_token"]}, headers=AUTH))
    assert entered.wait(10)
    assert ok(client.post(f"/api/jobs/{job2['id']}/cancel", headers=AUTH))["status"] == "cancelled"
    gate.set()
    assert wait_job(client, job2["id"], {"cancelled"})["status"] == "cancelled"


# --- profile ----------------------------------------------------------------------------------


def test_profile_crud_and_analyze(
    client: TestClient, book_pdf: Path, completer: FakeComplete
) -> None:
    bid = open_book(client, book_pdf)["id"]
    assert ok(client.get(f"/api/books/{bid}/profile", headers=AUTH)) is None
    put = ok(client.put(f"/api/books/{bid}/profile", json=PROFILE_JSON, headers=AUTH))
    assert put["sozluk"] == PROFILE_JSON["sozluk"] and put["cevrilmeyecek"] == ["Kafka"]
    err(
        client.put(f"/api/books/{bid}/profile", json={"sozluk": "x"}, headers=AUTH),
        "bad_request",
        400,
    )

    est = ok(client.post(f"/api/books/{bid}/profile/analyze/estimate", headers=AUTH))
    assert est["operation"] == "profile" and est["calls"] == 1 and completer.calls == []
    prof = ok(
        client.post(
            f"/api/books/{bid}/profile/analyze",
            json={"confirm_token": est["confirm_token"]},
            headers=AUTH,
        )
    )
    assert prof["tur"] == PROFILE_JSON["tur"] and len(completer.calls) == 1
    assert ok(client.get(f"/api/books/{bid}/profile", headers=AUTH))["ton"] == PROFILE_JSON["ton"]


# --- explain ----------------------------------------------------------------------------------


def test_explain_estimate_run_and_cache(
    client: TestClient, book_pdf: Path, completer: FakeComplete
) -> None:
    bid = open_book(client, book_pdf)["id"]
    req = {"text": "Replication means keeping a copy of the same data.", "book_id": bid, "page": 1}
    est = ok(client.post("/api/explain/estimate", json=req, headers=AUTH))
    assert est["operation"] == "explain" and "explanation" not in est and completer.calls == []
    out = ok(
        client.post("/api/explain", json={"confirm_token": est["confirm_token"]}, headers=AUTH)
    )
    assert out["cached"] is False and "Replikasyon" in out["explanation"]
    hit = ok(client.post("/api/explain/estimate", json=req, headers=AUTH))
    assert hit["cached"] is True and "confirm_token" not in hit
    assert len(completer.calls) == 1
    blank = client.post("/api/explain/estimate", json={"text": "   "}, headers=AUTH)
    err(blank, "bad_request", 400)


# --- learning ---------------------------------------------------------------------------------


def test_learning_endpoints(client: TestClient, book_pdf: Path) -> None:
    bid = open_book(client, book_pdf)["id"]
    look = ok(client.get("/api/lookup?q=replicated", headers=AUTH))
    assert look["query"] == "replicated" and isinstance(look["tr"], list)

    item = ok(
        client.post(
            "/api/vocab",
            json={"word": "replication", "book_id": bid, "page": 1, "meaning": "replikasyon"},
            headers=AUTH,
        )
    )
    assert item["page"] == 1 and item["unknown"] is True and item["meaning"] == "replikasyon"
    assert "eplication" in item["sentence"] and item["block_key"] is not None
    keyed = ok(
        client.post(
            "/api/vocab",
            json={"word": "network", "book_id": bid, "page": 1, "block_key": item["block_key"]},
            headers=AUTH,
        )
    )
    assert keyed["block_key"] == item["block_key"]
    err(
        client.post(
            "/api/vocab",
            json={"word": "x", "book_id": bid, "page": 1, "block_key": "a"},
            headers=AUTH,
        ),
        "bad_request",
        400,
    )
    err(
        client.post("/api/vocab", json={"word": "x", "book_id": 999}, headers=AUTH),
        "not_found",
        404,
    )

    listed = ok(client.get(f"/api/vocab?book_id={bid}&search=replic", headers=AUTH))
    assert [v["id"] for v in listed] == [item["id"]]
    patched = ok(client.patch(f"/api/vocab/{item['id']}", json={"unknown": False}, headers=AUTH))
    assert patched["unknown"] is False

    due = ok(client.get("/api/review/due?limit=10", headers=AUTH))
    assert {c["vocab_id"] for c in due} == {item["id"], keyed["id"]}
    card = next(c for c in due if c["vocab_id"] == item["id"])
    assert "_____" in card["front"] and card["word"] == "replication"
    nxt = ok(client.post(f"/api/review/{item['id']}", json={"rating": "good"}, headers=AUTH))
    assert nxt is None or nxt["vocab_id"] == keyed["id"]
    err(
        client.post(f"/api/review/{item['id']}", json={"rating": "meh"}, headers=AUTH),
        "bad_request",
        400,
    )
    stats = ok(client.get("/api/stats", headers=AUTH))
    assert stats["total_words"] == 2 and stats["reviewed_today"] == 1 and stats["streak_days"] == 1

    assert client.delete(f"/api/vocab/{keyed['id']}", headers=AUTH).status_code == 204
    err(client.delete(f"/api/vocab/{keyed['id']}", headers=AUTH), "not_found", 404)
    err(client.patch("/api/vocab/999", json={"unknown": True}, headers=AUTH), "not_found", 404)

    html = ok(client.get(f"/api/books/{bid}/pages/1/html?mode=learn", headers=AUTH))["html"]
    assert "data-w=" in html


def test_terms_from_profile(client: TestClient, book_pdf: Path) -> None:
    bid = open_book(client, book_pdf)["id"]
    assert ok(client.get(f"/api/books/{bid}/terms", headers=AUTH)) == []
    ok(client.put(f"/api/books/{bid}/profile", json=PROFILE_JSON, headers=AUTH))
    terms = ok(client.get(f"/api/books/{bid}/terms", headers=AUTH))
    assert {t["term"] for t in terms} == {"replication", "latency"}
    assert all(t["in_vocab"] is False for t in terms)
    one = ok(client.post(f"/api/books/{bid}/terms/add", json={"terms": ["latency"]}, headers=AUTH))
    assert one == {"added": 1}
    rest = ok(client.post(f"/api/books/{bid}/terms/add", json={"terms": None}, headers=AUTH))
    assert rest == {"added": 1}
    assert all(t["in_vocab"] for t in ok(client.get(f"/api/books/{bid}/terms", headers=AUTH)))


# --- export -----------------------------------------------------------------------------------


def _has_chromium() -> bool:
    from rosetta_engine.errors import RosettaError
    from rosetta_engine.export.chromium import find_chromium

    try:
        find_chromium()
    except RosettaError:
        return False
    return True


@pytest.mark.skipif(not _has_chromium(), reason="no Chromium for PDF printing")
def test_export_translated_pages(client: TestClient, book_pdf: Path, env: Path) -> None:
    bid = open_book(client, book_pdf)["id"]
    est = ok(client.post(f"/api/books/{bid}/estimate", json={"pages": [1]}, headers=AUTH))
    ok(
        client.post(
            f"/api/books/{bid}/translate",
            json={"confirm_token": est["confirm_token"]},
            headers=AUTH,
        )
    )
    out = env / "out.pdf"
    res = ok(
        client.post(
            f"/api/books/{bid}/export",
            json={"mode": "bilingual", "out_path": str(out)},
            headers=AUTH,
        )
    )
    assert res == {"path": str(out), "pages": 1, "untranslated_blocks": 0}
    assert out.read_bytes().startswith(b"%PDF")
    default = ok(
        client.post(f"/api/books/{bid}/export", json={"mode": "tr", "pages": [1]}, headers=AUTH)
    )
    assert default["path"].endswith(".tr.pdf") and Path(default["path"]).is_file()
    err(
        client.post(
            f"/api/books/{bid}/export",
            json={"mode": "tr", "out_path": str(env / "x.txt")},
            headers=AUTH,
        ),
        "bad_request",
        400,
    )


def test_export_without_chromium(
    client: TestClient, book_pdf: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from rosetta_engine.api import books
    from rosetta_engine.export.chromium import ExportError

    def missing() -> Path:
        raise ExportError("Chromium bulunamadı")

    monkeypatch.setattr(books, "find_chromium", missing)
    bid = open_book(client, book_pdf)["id"]
    err(
        client.post(f"/api/books/{bid}/export", json={"mode": "tr"}, headers=AUTH),
        "unavailable",
        503,
    )
