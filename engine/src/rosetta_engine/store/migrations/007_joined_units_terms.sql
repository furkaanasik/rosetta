-- Paragraphs joined across a page break are translated as one unit; its two rows (the head on
-- page N, the tail on page N+1) carry the unit's hash and their role. NULL = translated alone.
ALTER TABLE translations ADD COLUMN unit_hash TEXT;
ALTER TABLE translations ADD COLUMN unit_role TEXT;
-- Term consistency: terms the user chose to ignore, per book and language.
CREATE TABLE term_ignores(book_id INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
  lang TEXT NOT NULL, term TEXT NOT NULL, created_at TEXT NOT NULL,
  PRIMARY KEY(book_id, lang, term));
