-- Library + reading progress (UI redesign v2): when a book was last opened and the
-- 0-based page the reader was on.
ALTER TABLE books ADD COLUMN last_opened_at TEXT;
ALTER TABLE books ADD COLUMN last_page INTEGER;
