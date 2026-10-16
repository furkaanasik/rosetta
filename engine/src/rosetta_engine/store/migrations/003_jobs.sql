-- Faz 4: batch translation jobs (range / whole book), pausable and resumable.
CREATE TABLE jobs(
  id INTEGER PRIMARY KEY,
  book_id INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
  type TEXT NOT NULL DEFAULT 'translate' CHECK(type IN ('translate')),
  lang TEXT NOT NULL,
  provider TEXT NOT NULL,
  model TEXT NOT NULL,
  page_spec TEXT NOT NULL,
  pages_json TEXT NOT NULL,
  status TEXT NOT NULL
    CHECK(status IN ('pending','running','paused','done','failed','cancelled')),
  budget_usd REAL,
  spent_usd REAL NOT NULL DEFAULT 0,
  done_pages_json TEXT NOT NULL DEFAULT '[]',
  failed_json TEXT NOT NULL DEFAULT '{}',
  stop_reason TEXT,
  pause_requested INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX jobs_book ON jobs(book_id);
