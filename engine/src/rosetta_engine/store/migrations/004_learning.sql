-- Faz 6: vocabulary notebook + FSRS spaced repetition.
-- One vocab row per lemma, so "unknown" marks apply book-wide; the first context is kept.
CREATE TABLE vocab(
  id INTEGER PRIMARY KEY,
  word TEXT NOT NULL,
  lemma TEXT NOT NULL UNIQUE,
  sentence TEXT NOT NULL DEFAULT '',
  book_id INTEGER REFERENCES books(id) ON DELETE SET NULL,
  page_no INTEGER,
  block_ord INTEGER,
  text_hash TEXT,
  meaning TEXT NOT NULL DEFAULT '',
  unknown INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL
);
CREATE INDEX ix_vocab_book ON vocab(book_id);
CREATE INDEX ix_vocab_created ON vocab(created_at);

CREATE TABLE reviews(
  vocab_id INTEGER PRIMARY KEY REFERENCES vocab(id) ON DELETE CASCADE,
  due_at TEXT NOT NULL,
  stability REAL,
  difficulty REAL,
  state INTEGER NOT NULL,
  step INTEGER,
  reps INTEGER NOT NULL DEFAULT 0,
  lapses INTEGER NOT NULL DEFAULT 0,
  last_review_at TEXT,
  card_json TEXT NOT NULL
);
CREATE INDEX ix_reviews_due ON reviews(due_at);

CREATE TABLE review_log(
  id INTEGER PRIMARY KEY,
  vocab_id INTEGER NOT NULL REFERENCES vocab(id) ON DELETE CASCADE,
  rating INTEGER NOT NULL CHECK(rating BETWEEN 1 AND 4),
  reviewed_at TEXT NOT NULL,
  log_json TEXT NOT NULL
);
CREATE INDEX ix_review_log_at ON review_log(reviewed_at);
