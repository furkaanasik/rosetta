CREATE TABLE books(id INTEGER PRIMARY KEY, file_hash TEXT UNIQUE NOT NULL, title TEXT,
  page_count INTEGER NOT NULL, typography_json TEXT, furniture_json TEXT, file_path TEXT,
  created_at TEXT NOT NULL);
CREATE TABLE pages(book_id INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
  page_no INTEGER NOT NULL, extractor_version INTEGER NOT NULL, extracted_at TEXT NOT NULL,
  has_text_layer INTEGER NOT NULL, continues_on_next_page INTEGER NOT NULL DEFAULT 0,
  width REAL NOT NULL DEFAULT 0, height REAL NOT NULL DEFAULT 0,
  PRIMARY KEY(book_id, page_no));
CREATE TABLE blocks(id INTEGER PRIMARY KEY, book_id INTEGER NOT NULL, page_no INTEGER NOT NULL,
  ord INTEGER NOT NULL, type TEXT NOT NULL, bbox_json TEXT NOT NULL, font TEXT, size REAL,
  bold INTEGER, italic INTEGER, heading_level INTEGER, text TEXT NOT NULL,
  sentences_json TEXT NOT NULL DEFAULT '[]', text_hash TEXT NOT NULL,
  family TEXT NOT NULL DEFAULT 'serif', aside INTEGER NOT NULL DEFAULT 0, list_marker TEXT,
  UNIQUE(book_id, page_no, ord),
  FOREIGN KEY(book_id, page_no) REFERENCES pages(book_id, page_no) ON DELETE CASCADE);
CREATE TABLE translations(id INTEGER PRIMARY KEY, book_id INTEGER NOT NULL REFERENCES books(id),
  page_no INTEGER NOT NULL, text_hash TEXT NOT NULL, lang TEXT NOT NULL, provider TEXT NOT NULL,
  model TEXT NOT NULL, text TEXT NOT NULL, sentences_json TEXT NOT NULL,
  sentence_aligned INTEGER NOT NULL, prompt_version INTEGER NOT NULL, created_at TEXT NOT NULL,
  UNIQUE(book_id, page_no, text_hash, lang, provider, model));
CREATE TABLE page_status(book_id INTEGER NOT NULL, page_no INTEGER NOT NULL, lang TEXT NOT NULL,
  provider TEXT NOT NULL, model TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('done','failed')), error TEXT, updated_at TEXT NOT NULL,
  PRIMARY KEY(book_id, page_no, lang, provider, model));
CREATE TABLE profiles(book_id INTEGER PRIMARY KEY REFERENCES books(id), json TEXT NOT NULL,
  updated_at TEXT NOT NULL);
CREATE TABLE usage(id INTEGER PRIMARY KEY, ts TEXT NOT NULL, book_id INTEGER, provider TEXT NOT NULL,
  model TEXT NOT NULL, operation TEXT NOT NULL, input_tokens INTEGER NOT NULL,
  output_tokens INTEGER NOT NULL, cache_read_tokens INTEGER NOT NULL DEFAULT 0,
  est_input_tokens INTEGER, est_output_tokens INTEGER, cost_usd REAL NOT NULL, ok INTEGER NOT NULL);
