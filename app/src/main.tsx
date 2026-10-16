import { StrictMode, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import type { EngineApi } from "./api/engine";
import { App } from "./App";
import { connectEngine } from "./lib/engineConnect";
import "./styles/app.css";

function Root() {
  const [conn, setConn] = useState<{ api: EngineApi | null; mock: boolean; error?: string } | null>(null);
  useEffect(() => {
    connectEngine()
      .then((c) => setConn(c))
      .catch((e: unknown) => setConn({ api: null, mock: false, error: String(e) }));
  }, []);
  if (!conn) return <div className="splash">Rosetta başlatılıyor…</div>;
  return <App api={conn.api} mock={conn.mock} engineError={conn.error ?? null} />;
}

const el = document.getElementById("root");
if (el) {
  createRoot(el).render(
    <StrictMode>
      <Root />
    </StrictMode>,
  );
}
