"""Term-consistency API (no AI) and targeted re-translation through estimate → confirm."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from conftest import seed_terms
from fastapi.testclient import TestClient

from rosetta_engine import config
from rosetta_engine.api import create_app
from rosetta_engine.config import Settings
from rosetta_engine.store import db
from rosetta_engine.store.repo import Repos
from rosetta_engine.translate.fake import FakeTranslator

TOKEN = "q-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


class Translators:
    def __init__(self) -> None:
        self.created: list[FakeTranslator] = []

    def __call__(self, provider: str, model: str | None, settings: Settings) -> FakeTranslator:
        t = FakeTranslator()
        self.created.append(t)
        return t

    @property
    def calls(self) -> int:
        return sum(len(t.calls) for t in self.created)


@pytest.fixture
def translators() -> Translators:
    return Translators()


@pytest.fixture
def client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, translators: Translators
) -> Iterator[TestClient]:
    monkeypatch.setenv("ROSETTA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ROSETTA_CONFIG_DIR", str(tmp_path / "cfg"))
    app = create_app(
        Settings(provider="fake", model="fake", batch_max_pages=1),
        token=TOKEN,
        translator_factory=translators,
    )
    with TestClient(app) as c:
        yield c


def ok(r: Any, status: int = 200) -> Any:
    assert r.status_code == status, r.text
    return r.json() if r.content else None


def _conn() -> sqlite3.Connection:
    conn = db.connect(config.db_path())
    db.migrate(conn)
    return conn


def _usage_rows() -> int:
    conn = _conn()
    try:
        return int(conn.execute("SELECT COUNT(*) FROM usage").fetchone()[0])
    finally:
        conn.close()


@pytest.fixture
def seeded(client: TestClient, terms_pdf: Path, translators: Translators) -> int:
    """Book with extracted pages 1-3 and hand-written translations (conftest.TERMS_PAGES)."""
    bid = int(ok(client.post("/api/books/open", json={"path": str(terms_pdf)}, headers=AUTH))["id"])
    ok(client.post(f"/api/books/{bid}/estimate", json={"pages": [1, 2, 3]}, headers=AUTH))
    conn = _conn()
    seed_terms(Repos.from_conn(conn), bid)
    conn.close()
    assert translators.calls == 0
    return bid


def _replication(report: dict[str, Any]) -> dict[str, Any]:
    (issue,) = [i for i in report["issues"] if i["term"] == "replication"]
    return issue


def test_consistency_reports_variants_without_ai(
    client: TestClient, seeded: int, translators: Translators
) -> None:
    report = ok(client.get(f"/api/books/{seeded}/consistency", headers=AUTH))

    assert report["provider"] == "fake" and report["lang"] == "tr"
    assert report["analyzed_blocks"] == 9
    assert report["aligned_ratio"] == 1.0
    issue = _replication(report)
    assert issue["source"] == "mined" and issue["preferred"] is None
    assert [(v["label"], v["count"]) for v in issue["variants"]] == [
        ("çoğaltma", 6),
        ("replikasyon", 3),
    ]
    example = issue["variants"][0]["examples"][0]
    assert example["page"] in (1, 2) and example["block"].startswith(f"{example['page'] - 1}-")
    assert translators.calls == 0


def test_empty_book_and_unknown_book(client: TestClient, book_pdf: Path) -> None:
    bid = ok(client.post("/api/books/open", json={"path": str(book_pdf)}, headers=AUTH))["id"]
    report = ok(client.get(f"/api/books/{bid}/consistency", headers=AUTH))
    assert report["issues"] == [] and report["analyzed_blocks"] == 0
    r = client.get("/api/books/999/consistency", headers=AUTH)
    assert r.status_code == 404


def test_accept_updates_glossary_and_lists_affected(
    client: TestClient, seeded: int, translators: Translators
) -> None:
    usage_before = _usage_rows()

    res = ok(
        client.post(
            f"/api/books/{seeded}/consistency/accept",
            json={"term": "replication", "tr": "çoğaltma"},
            headers=AUTH,
        )
    )

    assert res["profile"]["sozluk"] == {"replication": "çoğaltma"}
    assert res["affected_count"] == 3  # page 3's three blocks use "replikasyon"
    assert {a["page"] for a in res["affected"]} == {3}
    assert translators.calls == 0 and _usage_rows() == usage_before
    profile = ok(client.get(f"/api/books/{seeded}/profile", headers=AUTH))
    assert profile["sozluk"] == {"replication": "çoğaltma"}

    issue = _replication(ok(client.get(f"/api/books/{seeded}/consistency", headers=AUTH)))
    assert issue["source"] == "glossary" and issue["preferred"] == "çoğaltma"
    assert issue["affected_count"] == 3


def test_accept_validates_input(client: TestClient, seeded: int) -> None:
    for body in ({"term": " ", "tr": "x"}, {"term": "a", "tr": "x" * 201}):
        r = client.post(f"/api/books/{seeded}/consistency/accept", json=body, headers=AUTH)
        assert r.status_code == 400, r.text


def test_ignore_and_unignore(client: TestClient, seeded: int) -> None:
    url = f"/api/books/{seeded}/consistency"
    assert ok(client.post(f"{url}/ignore", json={"term": "replication"}, headers=AUTH)) == {
        "ignored": ["replication"]
    }
    report = ok(client.get(url, headers=AUTH))
    assert all(i["term"] != "replication" for i in report["issues"])
    assert report["ignored"] == ["replication"]

    ok(client.delete(f"{url}/ignore", params={"term": "replication"}, headers=AUTH))
    _replication(ok(client.get(url, headers=AUTH)))


def test_targeted_retranslation_needs_confirmation(
    client: TestClient, seeded: int, translators: Translators
) -> None:
    res = ok(
        client.post(
            f"/api/books/{seeded}/consistency/accept",
            json={"term": "replication", "tr": "çoğaltma"},
            headers=AUTH,
        )
    )
    blocks = [{"page": a["page"], "text_hash": a["text_hash"]} for a in res["affected"]]

    est = ok(client.post(f"/api/books/{seeded}/estimate", json={"blocks": blocks}, headers=AUTH))
    assert est["operation"] == "translate" and est["calls"] == 1
    assert est["pages"] == [3] and est["total_blocks"] == 3 and est["cached_blocks"] == 0
    assert len(blocks) == 3
    assert translators.calls == 0  # nothing runs before confirmation

    ok(client.post(f"/api/books/{seeded}/translate", json={"confirm_token": est["confirm_token"]},
                   headers=AUTH))  # fmt: skip
    assert translators.calls == 1
    conn = _conn()
    row = Repos.from_conn(conn).translations.for_page(seeded, 2, "tr", "fake", "fake")
    status = Repos.from_conn(conn).page_status.get(seeded, 2, "tr", "fake", "fake")
    conn.close()
    assert all(row[b["text_hash"]].text.startswith("[TR] ") for b in blocks)
    assert status is None  # a targeted run never writes page status


def test_targeted_estimate_limits(client: TestClient, seeded: int) -> None:
    url = f"/api/books/{seeded}/estimate"
    too_many = [{"page": 1, "text_hash": f"h{i}"} for i in range(201)]
    assert client.post(url, json={"blocks": too_many}, headers=AUTH).status_code in (400, 422)
    assert client.post(url, json={"blocks": []}, headers=AUTH).status_code == 400
    bad_page = [{"page": 99, "text_hash": "x"}]
    assert client.post(url, json={"blocks": bad_page}, headers=AUTH).status_code == 400
