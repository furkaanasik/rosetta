-- Faz 7: "Bunu açıkla" cache. One row per (sentence, lang, model, prompt version).
CREATE TABLE explanations(
  hash TEXT PRIMARY KEY,
  text TEXT NOT NULL,
  context TEXT,
  lang TEXT NOT NULL,
  model TEXT NOT NULL,
  explanation_json TEXT NOT NULL,
  input_tokens INTEGER NOT NULL DEFAULT 0,
  output_tokens INTEGER NOT NULL DEFAULT 0,
  cost_usd REAL NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);
