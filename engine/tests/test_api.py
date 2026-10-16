"""HTTP API (Tauri sidecar) tests: TestClient + fake translator / fake complete_fn, no AI."""

from __future__ import annotations

import json
import re
import shutil
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pymupdf
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
    # "/assets/" in the path or query of another route is not the asset route
    err(client.get(f"/api/usage?x=/assets/&token={TOKEN}"), "unauthorized", 401)
    err(client.get(f"/api/books/1/file?token={TOKEN}"), "unauthorized", 401)
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


def test_book_file_served_with_bearer_only(client: TestClient, book_pdf: Path) -> None:
    book = open_book(client, book_pdf)
    url = f"/api/books/{book['id']}/file"
    err(client.get(url), "unauthorized", 401)
    err(client.get(f"{url}?token={TOKEN}"), "unauthorized", 401)  # query token: assets only
    r = client.get(url, headers=AUTH)
    assert r.status_code == 200 and r.content.startswith(b"%PDF")
    assert r.headers["content-type"] == "application/pdf"
    err(client.get("/api/books/999/file", headers=AUTH), "not_found", 404)


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


def _db_repos() -> Any:
    from rosetta_engine import config
    from rosetta_engine.store.db import connect, migrate
    from rosetta_engine.store.repo import Repos

    conn = connect(config.db_path())
    migrate(conn)
    return conn, Repos.from_conn(conn)


def test_retry_failed_runs_only_the_confirmed_failed_pages(
    client: TestClient, book_pdf: Path, translators: Translators
) -> None:
    """H1: a paused job with 1 failed + 2 never-started pages; retry must touch only page 1."""
    bid = open_book(client, book_pdf)["id"]
    conn, repos = _db_repos()
    try:
        row = repos.jobs.create(bid, "tr", "fake", "fake", "1-3", [0, 1, 2], None)
        repos.jobs.update_progress(row.id, done_pages=[], failed={0: "boom"}, spent_usd=0.0)
        repos.jobs.set_status(row.id, "paused", "3 consecutive provider errors")
    finally:
        conn.close()

    est = ok(client.post(f"/api/jobs/{row.id}/retry-failed/estimate", headers=AUTH))
    assert est["pages"] == [1]
    ok(
        client.post(
            f"/api/jobs/{row.id}/retry-failed",
            json={"confirm_token": est["confirm_token"]},
            headers=AUTH,
        )
    )
    after = wait_job(client, row.id, {"paused", "done", "failed"})

    assert translators.calls == 1  # exactly one batch: page 1 (batch_max_pages=1)
    assert after["done_pages"] == [1] and after["failed_pages"] == {}
    assert after["status"] == "paused"  # pages 2-3 still waiting, never estimated or paid


def test_job_estimate_warns_budget_cannot_be_preapplied_without_price(
    client: TestClient, book_pdf: Path
) -> None:
    bid = open_book(client, book_pdf)["id"]
    with_budget = ok(
        client.post(
            f"/api/books/{bid}/jobs/estimate", json={"pages": [1], "budget_usd": 1}, headers=AUTH
        )
    )
    without = ok(client.post(f"/api/books/{bid}/jobs/estimate", json={"pages": [1]}, headers=AUTH))

    assert with_budget["price_known"] is False
    assert any("bütçe önceden uygulanamaz" in w for w in with_budget["warnings"])
    assert without["warnings"] == []


def test_blank_vocab_word_is_bad_request(client: TestClient) -> None:
    err(client.post("/api/vocab", json={"word": "   "}, headers=AUTH), "bad_request", 400)


def test_retry_token_refused_if_failed_pages_changed(client: TestClient, book_pdf: Path) -> None:
    bid = open_book(client, book_pdf)["id"]
    conn, repos = _db_repos()
    try:
        row = repos.jobs.create(bid, "tr", "fake", "fake", "1-3", [0, 1, 2], None)
        repos.jobs.update_progress(row.id, done_pages=[], failed={0: "boom"}, spent_usd=0.0)
        repos.jobs.set_status(row.id, "failed", "1 sayfa hatalı")
        est = ok(client.post(f"/api/jobs/{row.id}/retry-failed/estimate", headers=AUTH))
        repos.jobs.update_progress(row.id, done_pages=[], failed={0: "a", 1: "b"}, spent_usd=0.0)
    finally:
        conn.close()

    err(
        client.post(
            f"/api/jobs/{row.id}/retry-failed",
            json={"confirm_token": est["confirm_token"]},
            headers=AUTH,
        ),
        "expired_token",
        409,
    )


def test_busy_job_slot_consumes_no_token_and_leaves_no_job(
    client: TestClient, book_pdf: Path, translators: Translators
) -> None:
    gate, entered = threading.Event(), threading.Event()
    translators.make = lambda: GateTranslator(gate, entered)
    bid = open_book(client, book_pdf)["id"]
    first = ok(client.post(f"/api/books/{bid}/jobs/estimate", json={"pages": [1]}, headers=AUTH))
    second = ok(client.post(f"/api/books/{bid}/jobs/estimate", json={"pages": [2]}, headers=AUTH))
    job = ok(client.post("/api/jobs", json={"confirm_token": first["confirm_token"]}, headers=AUTH))
    assert entered.wait(10)

    busy = client.post("/api/jobs", json={"confirm_token": second["confirm_token"]}, headers=AUTH)
    err(busy, "unavailable", 503)
    assert len(ok(client.get("/api/jobs", headers=AUTH))) == 1  # no orphan pending job

    gate.set()
    wait_job(client, job["id"], {"done"})
    translators.make = FakeTranslator
    # the refused token was not consumed: it still starts the second job
    later = ok(
        client.post("/api/jobs", json={"confirm_token": second["confirm_token"]}, headers=AUTH)
    )
    assert wait_job(client, later["id"], {"done"})["done_pages"] == [2]


def test_ai_calls_are_exclusive_while_a_job_runs(
    client: TestClient, book_pdf: Path, translators: Translators
) -> None:
    gate, entered = threading.Event(), threading.Event()
    translators.make = lambda: GateTranslator(gate, entered)
    bid = open_book(client, book_pdf)["id"]
    est_job = ok(client.post(f"/api/books/{bid}/jobs/estimate", json={"pages": [1]}, headers=AUTH))
    est_tr = ok(client.post(f"/api/books/{bid}/estimate", json={"pages": [2]}, headers=AUTH))
    job = ok(
        client.post("/api/jobs", json={"confirm_token": est_job["confirm_token"]}, headers=AUTH)
    )
    assert entered.wait(10)

    body = {"confirm_token": est_tr["confirm_token"]}
    err(client.post(f"/api/books/{bid}/translate", json=body, headers=AUTH), "unavailable", 503)

    gate.set()
    wait_job(client, job["id"], {"done"})
    translators.make = FakeTranslator
    assert ok(client.post(f"/api/books/{bid}/translate", json=body, headers=AUTH))["done_pages"]


def test_book_whose_file_changed_is_a_conflict(
    make_client: Callable[..., TestClient], book_pdf: Path, tmp_path: Path
) -> None:
    first = make_client()
    bid = open_book(first, book_pdf)["id"]
    other = tmp_path / "other.pdf"
    doc = pymupdf.open()  # type: ignore[no-untyped-call]
    doc.new_page().insert_text((50, 60), "A different book")
    doc.save(other)
    doc.close()
    shutil.copy(other, book_pdf)  # a different file now sits at the stored path

    restarted = make_client()
    err(restarted.get(f"/api/books/{bid}/toc", headers=AUTH), "conflict", 409)


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
    assert {c["vocab_id"] for c in due} == {keyed["id"]}  # a word marked known leaves the queue
    ok(client.patch(f"/api/vocab/{item['id']}", json={"unknown": True}, headers=AUTH))
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


# --- UI redesign v2: library, progress, cover, page overview, batch HTML, hints -----------------


def test_library_lists_opened_books_most_recent_first(
    client: TestClient, book_pdf: Path, two_column_pdf: Path
) -> None:
    assert ok(client.get("/api/books", headers=AUTH)) == []
    a = open_book(client, book_pdf)
    time.sleep(0.01)
    b = open_book(client, two_column_pdf)

    lib = ok(client.get("/api/books", headers=AUTH))
    assert [x["id"] for x in lib] == [b["id"], a["id"]]
    first = lib[1]
    assert first["title"] and first["page_count"] == 3
    assert first["file_path"] == str(book_pdf) and first["file_exists"] is True
    assert first["last_opened_at"] and first["last_page"] is None
    assert first["translated_pages"] == 0
    assert first["cover_url"] == f"/api/books/{a['id']}/cover"

    time.sleep(0.01)
    saved = ok(client.put(f"/api/books/{a['id']}/progress", json={"page": 2}, headers=AUTH))
    assert saved["last_page"] == 2 and saved["book_id"] == a["id"]
    lib = ok(client.get("/api/books", headers=AUTH))
    assert [x["id"] for x in lib] == [a["id"], b["id"]]
    assert lib[0]["last_page"] == 2


def test_library_shows_missing_file(client: TestClient, book_pdf: Path, tmp_path: Path) -> None:
    moved = tmp_path / "moved.pdf"
    shutil.copy(book_pdf, moved)
    open_book(client, moved)
    moved.unlink()
    (item,) = ok(client.get("/api/books", headers=AUTH))
    assert item["file_exists"] is False


def test_progress_validation(client: TestClient, book_pdf: Path) -> None:
    book = open_book(client, book_pdf)
    url = f"/api/books/{book['id']}/progress"
    err(client.put(url, json={"page": 4}, headers=AUTH), "bad_request", 400)
    err(client.put(url, json={"page": 0}, headers=AUTH), "bad_request", 400)
    err(client.put("/api/books/999/progress", json={"page": 1}, headers=AUTH), "not_found", 404)
    err(client.put(url, json={"page": 1}), "unauthorized", 401)


def test_translated_pages_counted_in_library(
    client: TestClient, book_pdf: Path, translators: Translators
) -> None:
    book = open_book(client, book_pdf)
    est = ok(client.post(f"/api/books/{book['id']}/estimate", json={"pages": [1]}, headers=AUTH))
    ok(
        client.post(
            f"/api/books/{book['id']}/translate",
            json={"confirm_token": est["confirm_token"]},
            headers=AUTH,
        )
    )
    (item,) = ok(client.get("/api/books", headers=AUTH))
    assert item["translated_pages"] == 1


def test_cover_png_cached_and_bearer_only(client: TestClient, book_pdf: Path, env: Path) -> None:
    book = open_book(client, book_pdf)
    url = f"/api/books/{book['id']}/cover"
    err(client.get(url), "unauthorized", 401)
    err(client.get(f"{url}?token={TOKEN}"), "unauthorized", 401)  # not the asset route
    r = client.get(f"{url}?w=120", headers=AUTH)
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    pix = pymupdf.Pixmap(r.content)
    assert pix.width == 120
    cached = list((env / "data" / "out").rglob("cover_w120.png"))
    assert len(cached) == 1
    assert client.get(f"{url}?w=120", headers=AUTH).content == r.content
    err(client.get(f"{url}?w=10", headers=AUTH), "bad_request", 400)
    err(client.get("/api/books/999/cover", headers=AUTH), "not_found", 404)


def test_pages_overview_without_extraction(
    client: TestClient, book_pdf: Path, translators: Translators
) -> None:
    book = open_book(client, book_pdf)
    url = f"/api/books/{book['id']}/pages"
    pages = ok(client.get(url, headers=AUTH))
    assert [p["page"] for p in pages] == [1, 2, 3]
    assert all(p["width"] > 0 and p["height"] > 0 for p in pages)
    assert all(p["translated"] is False for p in pages)
    assert all(p["has_text_layer"] is True for p in pages)  # from fonts, before extraction
    assert all(p["translatable_blocks"] is None for p in pages)

    ok(client.get(f"/api/books/{book['id']}/pages/2/blocks", headers=AUTH))
    pages = ok(client.get(url, headers=AUTH))
    assert pages[1]["has_text_layer"] is True and pages[1]["translatable_blocks"] > 0

    est = ok(client.post(f"/api/books/{book['id']}/estimate", json={"pages": [2]}, headers=AUTH))
    body = {"confirm_token": est["confirm_token"]}
    ok(client.post(f"/api/books/{book['id']}/translate", json=body, headers=AUTH))
    pages = ok(client.get(url, headers=AUTH))
    assert [p["translated"] for p in pages] == [False, True, False]
    assert translators.calls == 1


def test_page_html_has_size_and_content_box(client: TestClient, book_pdf: Path) -> None:
    book = open_book(client, book_pdf)
    html = ok(client.get(f"/api/books/{book['id']}/pages/1/html", headers=AUTH))
    assert html["width"] > 0 and html["height"] > 0 and html["has_text_layer"] is True
    x0, y0, x1, y1 = html["content_box"]
    assert 0 <= x0 < x1 <= html["width"]
    assert 0 <= y0 < y1 <= html["height"]
    blocks = ok(client.get(f"/api/books/{book['id']}/pages/1/blocks", headers=AUTH))["blocks"]
    furniture = [b["bbox"] for b in blocks if b["type"] == "furniture"]
    assert furniture  # the synthetic page has a header and a page number…
    body_y1 = max(b["bbox"][3] for b in blocks if b["type"] != "furniture")
    assert y1 == pytest.approx(body_y1, abs=0.01)  # …which the box ignores


def test_batch_page_html(client: TestClient, book_pdf: Path) -> None:
    book = open_book(client, book_pdf)
    url = f"/api/books/{book['id']}/html"
    out = ok(client.get(f"{url}?pages=1-2&mode=tr", headers=AUTH))
    assert [p["page"] for p in out["pages"]] == [1, 2]
    single = ok(client.get(f"/api/books/{book['id']}/pages/2/html", headers=AUTH))
    assert out["pages"][1] == single
    assert [p["page"] for p in ok(client.get(f"{url}?pages=3,1", headers=AUTH))["pages"]] == [1, 3]
    err(client.get(f"{url}?pages=1-20", headers=AUTH), "bad_request", 400)
    err(client.get(f"{url}?pages=a", headers=AUTH), "bad_request", 400)
    err(client.get(f"{url}?pages=2-9", headers=AUTH), "bad_request", 400)  # out of range
    err(client.get(url, headers=AUTH), "bad_request", 400)


def test_estimate_hint_issues_no_token_and_calls_no_ai(
    make_client: Callable[..., TestClient], book_pdf: Path, translators: Translators
) -> None:
    store = ConfirmStore()
    client = make_client(confirm=store)
    book = open_book(client, book_pdf)
    hint = ok(client.get(f"/api/books/{book['id']}/pages/1/estimate_hint", headers=AUTH))
    assert hint["calls"] == 1 and hint["total_blocks"] > 0 and hint["cached_blocks"] == 0
    assert hint["has_text_layer"] is True and hint["seconds_hint"] > 0
    assert "confirm_token" not in hint
    assert store._entries == {}  # no token: translating still needs /estimate + confirm
    assert translators.calls == 0

    est = ok(client.post(f"/api/books/{book['id']}/estimate", json={"pages": [1]}, headers=AUTH))
    body = {"confirm_token": est["confirm_token"]}
    ok(client.post(f"/api/books/{book['id']}/translate", json=body, headers=AUTH))
    calls = translators.calls
    hint = ok(client.get(f"/api/books/{book['id']}/pages/1/estimate_hint", headers=AUTH))
    assert hint["calls"] == 0 and hint["cached_blocks"] == hint["total_blocks"]
    assert hint["seconds_hint"] == 0 and translators.calls == calls


def test_learn_mode_keeps_figure_images(client: TestClient, book_pdf: Path) -> None:
    book = open_book(client, book_pdf)
    tr = ok(client.get(f"/api/books/{book['id']}/pages/1/html?mode=tr", headers=AUTH))["html"]
    learn = ok(client.get(f"/api/books/{book['id']}/pages/1/html?mode=learn", headers=AUTH))
    srcs = re.findall(r'<img [^>]*src="([^"]+)"', learn["html"])
    assert srcs and srcs == re.findall(r'<img [^>]*src="([^"]+)"', tr)
    assert all(s.startswith("assets/") for s in srcs)
    assert ">[image]<" not in learn["html"]


def test_pages_overview_flags_page_without_text(
    client: TestClient, make_pdf: Callable[..., Path]
) -> None:
    def fill(doc: Any) -> None:
        doc.new_page().insert_text((72, 72), "Some text", fontname="tiro", fontsize=11)
        blank = doc.new_page()
        blank.draw_rect(pymupdf.Rect(72, 72, 300, 300), color=(0, 0, 0), fill=(0.5, 0.5, 0.5))

    book = open_book(client, make_pdf(fill, "scan.pdf"))
    pages = ok(client.get(f"/api/books/{book['id']}/pages", headers=AUTH))
    assert [p["has_text_layer"] for p in pages] == [True, False]
