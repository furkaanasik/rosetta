import {
  ArrowLeft,
  ArrowsClockwise,
  CheckCircle,
  Copy,
  FolderOpen,
  MagnifyingGlass,
  WarningCircle,
  XCircle,
} from "@phosphor-icons/react";
import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import type { EngineApi } from "../api/engine";
import type { ClaudeCandidate, Diagnostics, EditableSettings, SettingsPatch, SettingsView, ViewMode } from "../api/types";
import { EngineError } from "../api/types";
import { describeError } from "../lib/errors";
import { isTauri, openFolder } from "../lib/engineConnect";
import { Badge, Button, IconButton, Segmented, Skeleton, useToast, type ThemePref } from "../ui";
import { MODE_LABELS } from "../state";
import "./settings.css";

export type SettingsSection = "translate" | "claude" | "deepl" | "ollama" | "appearance" | "data" | "status";

const SECTIONS: { id: SettingsSection; label: string }[] = [
  { id: "translate", label: "Çeviri" },
  { id: "claude", label: "Claude CLI" },
  { id: "deepl", label: "DeepL" },
  { id: "ollama", label: "Ollama" },
  { id: "appearance", label: "Görünüm" },
  { id: "data", label: "Veri" },
  { id: "status", label: "Motor durumu" },
];

export type ThinkingLevel = "off" | "low" | "medium" | "high";

/** Settings fields → the four-step thinking control (MAX_THINKING_TOKENS=0 means off). */
export function thinkingOf(v: Pick<EditableSettings, "claude_effort" | "claude_max_thinking_tokens">): ThinkingLevel {
  if (v.claude_max_thinking_tokens !== null && v.claude_max_thinking_tokens <= 0) return "off";
  const e = v.claude_effort ?? "medium";
  return e === "low" || e === "high" ? e : "medium";
}

export function thinkingPatch(level: ThinkingLevel): Pick<EditableSettings, "claude_effort" | "claude_max_thinking_tokens"> {
  return level === "off"
    ? { claude_effort: "low", claude_max_thinking_tokens: 0 }
    : { claude_effort: level, claude_max_thinking_tokens: null };
}

/** Form values: numbers are edited as text so a half-typed "0." isn't lost. */
interface Draft {
  default_lang: string;
  provider: string;
  model: string;
  explain_model: string;
  claude_path: string;
  thinking: ThinkingLevel;
  claude_max_budget_usd: string;
  job_default_budget_usd: string;
  batch_max_pages: string;
  deepl_auth_key_env: string;
  ollama_url: string;
  ollama_model: string;
}

const num = (v: number | null) => (v === null ? "" : String(v));

export function draftOf(v: EditableSettings): Draft {
  return {
    default_lang: v.default_lang,
    provider: v.provider,
    model: v.model,
    explain_model: v.explain_model,
    claude_path: v.claude_path ?? "",
    thinking: thinkingOf(v),
    claude_max_budget_usd: num(v.claude_max_budget_usd),
    job_default_budget_usd: num(v.job_default_budget_usd),
    batch_max_pages: String(v.batch_max_pages),
    deepl_auth_key_env: v.deepl_auth_key_env,
    ollama_url: v.ollama_url,
    ollama_model: v.ollama_model,
  };
}

export type FieldErrors = Partial<Record<keyof Draft, string>>;

function money(text: string, field: keyof Draft, errors: FieldErrors): number | null {
  const t = text.trim().replace(",", ".");
  if (!t) return null;
  const n = Number(t);
  if (!Number.isFinite(n) || n <= 0) {
    errors[field] = "Pozitif bir tutar girin ya da boş bırakın";
    return null;
  }
  return Math.round(n * 10_000) / 10_000;
}

/** Draft → partial update containing only what changed (null = back to default). */
export function patchOf(draft: Draft, saved: EditableSettings): { patch: SettingsPatch; errors: FieldErrors } {
  const errors: FieldErrors = {};
  const next: Partial<EditableSettings> = {
    default_lang: draft.default_lang.trim() || "tr",
    provider: draft.provider,
    model: draft.model.trim(),
    explain_model: draft.explain_model.trim(),
    claude_path: draft.claude_path.trim() || null,
    ...thinkingPatch(draft.thinking),
    claude_max_budget_usd: money(draft.claude_max_budget_usd, "claude_max_budget_usd", errors),
    job_default_budget_usd: money(draft.job_default_budget_usd, "job_default_budget_usd", errors),
    deepl_auth_key_env: draft.deepl_auth_key_env.trim(),
    ollama_url: draft.ollama_url.trim(),
    ollama_model: draft.ollama_model.trim(),
  };
  if (!next.model) errors.model = "Model adı gerekli";
  if (!next.explain_model) errors.explain_model = "Model adı gerekli";
  if (next.claude_path && !next.claude_path.startsWith("/") && !next.claude_path.startsWith("~")) {
    errors.claude_path = "Tam yol girin (ör. /home/kullanıcı/.local/bin/claude)";
  }
  if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(next.deepl_auth_key_env ?? "")) {
    errors.deepl_auth_key_env = "Geçerli bir ortam değişkeni adı girin";
  }
  if (!/^https?:\/\/[^/\s]+/.test(next.ollama_url ?? "")) errors.ollama_url = "http(s)://sunucu:port biçiminde olmalı";
  const pages = Number(draft.batch_max_pages);
  if (!Number.isInteger(pages) || pages < 1 || pages > 20) errors.batch_max_pages = "1 ile 20 arasında bir sayı";
  else next.batch_max_pages = pages;
  const patch: SettingsPatch = {};
  for (const [k, v] of Object.entries(next) as [keyof EditableSettings, EditableSettings[keyof EditableSettings]][]) {
    if (v !== saved[k]) (patch as Record<string, unknown>)[k] = v;
  }
  return { patch, errors };
}

const MODE_KEY = "rosetta.mode";
const VIEW_MODES: ViewMode[] = ["original", "split", "translation", "learn"];

function readMode(): ViewMode {
  try {
    const v = localStorage.getItem(MODE_KEY);
    return VIEW_MODES.includes(v as ViewMode) ? (v as ViewMode) : "split";
  } catch {
    return "split";
  }
}

interface Props {
  api: EngineApi | null;
  mock?: boolean;
  theme: ThemePref;
  onTheme: (t: ThemePref) => void;
  onClose: () => void;
  /** Section to scroll to on open (e.g. "claude" from a "claude bulunamadı" error). */
  section?: SettingsSection;
  /** Called after a successful save so the app can refresh estimates. */
  onSaved?: (view: SettingsView) => void;
}

export function SettingsScreen({ api, mock, theme, onTheme, onClose, section, onSaved }: Props) {
  const toast = useToast();
  const [view, setView] = useState<SettingsView | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [diag, setDiag] = useState<Diagnostics | null>(null);
  const [diagBusy, setDiagBusy] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [errors, setErrors] = useState<FieldErrors>({});
  const [serverError, setServerError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [candidates, setCandidates] = useState<ClaudeCandidate[] | null>(null);
  const [detecting, setDetecting] = useState(false);
  const [mode, setMode] = useState<ViewMode>(readMode);
  const [active, setActive] = useState<SettingsSection>(section ?? "translate");

  const refreshDiag = useCallback(async () => {
    if (!api) return;
    setDiagBusy(true);
    try {
      setDiag(await api.diagnostics());
    } catch (e) {
      toast({ message: describeError(e).message, tone: "error" });
    } finally {
      setDiagBusy(false);
    }
  }, [api, toast]);

  useEffect(() => {
    if (!api) return;
    let alive = true;
    api
      .getSettings()
      .then((v) => {
        if (!alive) return;
        setView(v);
        setDraft(draftOf(v.values));
      })
      .catch((e: unknown) => alive && setLoadError(describeError(e).message));
    void refreshDiag();
    return () => {
      alive = false;
    };
  }, [api, refreshDiag]);

  useEffect(() => {
    if (!section) return;
    setActive(section);
    requestAnimationFrame(() => document.getElementById(`set-${section}`)?.scrollIntoView({ block: "start" }));
  }, [section, view]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !(e.target instanceof HTMLInputElement || e.target instanceof HTMLSelectElement)) onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  const computed = useMemo(() => (draft && view ? patchOf(draft, view.values) : null), [draft, view]);
  const dirty = !!computed && Object.keys(computed.patch).length > 0;

  const set = <K extends keyof Draft>(k: K, v: Draft[K]) => {
    setDraft((d) => (d ? { ...d, [k]: v } : d));
    setErrors((e) => ({ ...e, [k]: undefined }));
    setServerError(null);
  };

  const save = async () => {
    if (!api || !computed) return;
    if (Object.values(computed.errors).some(Boolean)) {
      setErrors(computed.errors);
      return;
    }
    setSaving(true);
    try {
      const v = await api.putSettings(computed.patch);
      setView(v);
      setDraft(draftOf(v.values));
      onSaved?.(v);
      toast({ message: "Ayarlar kaydedildi", tone: "success" });
      void refreshDiag();
    } catch (e) {
      setServerError(e instanceof EngineError ? e.message : describeError(e).message);
    } finally {
      setSaving(false);
    }
  };

  const reset = (k: keyof EditableSettings) => {
    if (!view || !draft) return;
    const d = draftOf({ ...view.values, [k]: view.defaults[k] });
    if (k === "claude_effort" || k === "claude_max_thinking_tokens") {
      setDraft({ ...draft, thinking: thinkingOf(view.defaults) });
    } else {
      const field = (k in d ? k : null) as keyof Draft | null;
      if (field) setDraft({ ...draft, [field]: d[field] });
    }
  };

  const detect = async () => {
    if (!api) return;
    setDetecting(true);
    try {
      setCandidates(await api.detectClaude());
    } catch (e) {
      toast({ message: describeError(e).message, tone: "error" });
    } finally {
      setDetecting(false);
    }
  };

  const chooseMode = (m: ViewMode) => {
    setMode(m);
    try {
      localStorage.setItem(MODE_KEY, m);
    } catch {
      /* private mode */
    }
  };

  const copy = (text: string) => {
    void navigator.clipboard?.writeText(text).then(
      () => toast({ message: "Yol kopyalandı", tone: "success" }),
      () => toast({ message: text }),
    );
  };

  const open = (path: string) => {
    openFolder(path)
      .then((ok) => {
        if (!ok) copy(path);
      })
      .catch((e: unknown) => toast({ message: describeError(e).message, tone: "error" }));
  };

  const fromFile = new Set(view?.from_file ?? []);
  const isDefault = (k: keyof EditableSettings) => !fromFile.has(k);

  return (
    <div className="settings" role="dialog" aria-label="Ayarlar">
      <header className="settings__bar">
        <IconButton label="Geri (Esc)" onClick={onClose}>
          <ArrowLeft />
        </IconButton>
        <h1 className="settings__title">Ayarlar</h1>
        <div className="settings__actions">
          {dirty && <span className="settings__dirty">Kaydedilmemiş değişiklikler</span>}
          <Button variant="ghost" disabled={!dirty || saving} onClick={() => view && setDraft(draftOf(view.values))}>
            Geri al
          </Button>
          <Button variant="primary" disabled={!dirty || saving || !api} onClick={() => void save()}>
            {saving ? "Kaydediliyor…" : "Kaydet"}
          </Button>
        </div>
      </header>

      <div className="settings__body">
        <nav className="settings__nav" aria-label="Bölümler">
          {SECTIONS.map((s) => (
            <a
              key={s.id}
              href={`#set-${s.id}`}
              className={active === s.id ? "is-active" : undefined}
              onClick={(e) => {
                e.preventDefault();
                setActive(s.id);
                document.getElementById(`set-${s.id}`)?.scrollIntoView({ block: "start", behavior: "smooth" });
              }}
            >
              {s.label}
              {s.id === "claude" && diag && !diag.claude.path && <span className="settings__navdot" aria-label="sorun" />}
            </a>
          ))}
        </nav>

        <main className="settings__main">
          {!api && <Notice tone="danger">Motor bağlı değil; ayarlar okunamıyor.</Notice>}
          {loadError && <Notice tone="danger">{loadError}</Notice>}
          {serverError && <Notice tone="danger">{serverError}</Notice>}
          {mock && <Notice tone="neutral">Deneme motoru: değişiklikler kalıcı değil.</Notice>}
          {!draft || !view ? (
            api && !loadError ? <Skeleton width="100%" height={320} /> : null
          ) : (
            <>
              <Section id="translate" title="Çeviri" lede="Yeni çevirilerde kullanılan varsayılanlar. Var olan çeviriler değişmez.">
                <Row label="Hedef dil" hint="Varsayılan: tr" dflt={isDefault("default_lang")} onReset={() => reset("default_lang")}>
                  <select value={draft.default_lang} onChange={(e) => set("default_lang", e.target.value)}>
                    {["tr", "de", "fr", "es", "it", "en"].map((l) => (
                      <option key={l} value={l}>
                        {LANG_LABEL[l] ?? l}
                      </option>
                    ))}
                  </select>
                </Row>
                <Row label="Sağlayıcı" dflt={isDefault("provider")} onReset={() => reset("provider")}>
                  <select value={draft.provider} onChange={(e) => set("provider", e.target.value)}>
                    <option value="claude-cli">Claude (abonelik, claude CLI)</option>
                    <option value="deepl">DeepL (API anahtarı)</option>
                    <option value="ollama">Ollama (yerel model)</option>
                    {!["claude-cli", "deepl", "ollama"].includes(draft.provider) && (
                      <option value={draft.provider}>{draft.provider === "fake" ? "Sahte (test)" : draft.provider}</option>
                    )}
                  </select>
                </Row>
                <Row label="Çeviri modeli" error={errors.model} dflt={isDefault("model")} onReset={() => reset("model")}>
                  <ModelInput value={draft.model} onChange={(v) => set("model", v)} />
                </Row>
                <Row
                  label="Düşünme"
                  hint="Kapalı: en hızlı ve ucuz. Orta: deyim ve anlam hatalarında daha güvenilir."
                  dflt={isDefault("claude_effort") && isDefault("claude_max_thinking_tokens")}
                  onReset={() => reset("claude_effort")}
                >
                  <Segmented
                    value={draft.thinking}
                    onChange={(v) => set("thinking", v)}
                    items={[
                      { value: "off", label: "Kapalı" },
                      { value: "low", label: "Düşük" },
                      { value: "medium", label: "Orta" },
                      { value: "high", label: "Yüksek" },
                    ]}
                    label="Düşünme seviyesi"
                  />
                </Row>
                <Row
                  label="Çağrı başı bütçe"
                  hint="Tek bir AI çağrısı bu tutarı aşamaz (liste fiyatı eşdeğeri $). Boş: sınır yok."
                  error={errors.claude_max_budget_usd}
                  dflt={isDefault("claude_max_budget_usd")}
                  onReset={() => reset("claude_max_budget_usd")}
                >
                  <Money value={draft.claude_max_budget_usd} onChange={(v) => set("claude_max_budget_usd", v)} />
                </Row>
                <Row
                  label="Toplu iş bütçesi (varsayılan)"
                  hint="Aralık / tüm kitap çevirisinde önerilen bütçe. Boş: sormadan başlamaz, siz girersiniz."
                  error={errors.job_default_budget_usd}
                  dflt={isDefault("job_default_budget_usd")}
                  onReset={() => reset("job_default_budget_usd")}
                >
                  <Money value={draft.job_default_budget_usd} onChange={(v) => set("job_default_budget_usd", v)} />
                </Row>
                <Row
                  label="Bir çağrıdaki en fazla sayfa"
                  error={errors.batch_max_pages}
                  dflt={isDefault("batch_max_pages")}
                  onReset={() => reset("batch_max_pages")}
                >
                  <input
                    inputMode="numeric"
                    value={draft.batch_max_pages}
                    onChange={(e) => set("batch_max_pages", e.target.value)}
                    className="settings__narrow"
                  />
                </Row>
                <Row
                  label="“Bunu açıkla” modeli"
                  error={errors.explain_model}
                  dflt={isDefault("explain_model")}
                  onReset={() => reset("explain_model")}
                >
                  <ModelInput value={draft.explain_model} onChange={(v) => set("explain_model", v)} />
                </Row>
              </Section>

              <Section id="claude" title="Claude CLI" lede="Çeviri bilgisayarınızdaki `claude` ile, aboneliğinizle yapılır. API anahtarı kullanılmaz.">
                <StatusLine
                  ok={!!diag?.claude.path}
                  loading={diagBusy && !diag}
                  okText={diag?.claude.path ? `${diag.claude.version ?? "sürüm okunamadı"} · ${SOURCE_LABEL[diag.claude.source]}` : ""}
                  badText="claude CLI bulunamadı — yolunu aşağıya girin ya da “Bul”a basın"
                />
                {diag?.claude.path && <code className="settings__path">{diag.claude.path}</code>}
                <Row
                  label="claude yolu"
                  hint="Boş bırakırsanız PATH ve bilinen kurulum klasörlerinde otomatik aranır."
                  error={errors.claude_path}
                  dflt={isDefault("claude_path")}
                  onReset={() => reset("claude_path")}
                >
                  <div className="settings__inline">
                    <input
                      value={draft.claude_path}
                      placeholder="Otomatik bul"
                      spellCheck={false}
                      onChange={(e) => set("claude_path", e.target.value)}
                    />
                    <Button icon={<MagnifyingGlass />} disabled={detecting || !api} onClick={() => void detect()}>
                      {detecting ? "Aranıyor…" : "Bul"}
                    </Button>
                  </div>
                </Row>
                {candidates && (
                  <ul className="settings__candidates" aria-label="Bulunan claude kurulumları">
                    {candidates.length === 0 && <li className="settings__muted">Hiçbir kurulum bulunamadı.</li>}
                    {candidates.map((c) => (
                      <li key={c.path}>
                        <button type="button" onClick={() => set("claude_path", c.path)}>
                          <code>{c.path}</code>
                          <span>{c.version ?? "sürüm okunamadı"}</span>
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </Section>

              <Section id="deepl" title="DeepL" lede="DeepL kitap profilini ve önceki sayfa bağlamını kullanmaz. Anahtar dosyaya yazılmaz, ortam değişkeninden okunur.">
                <StatusLine
                  ok={!!diag?.deepl.key_set}
                  loading={diagBusy && !diag}
                  okText={`${diag?.deepl.env ?? draft.deepl_auth_key_env} tanımlı`}
                  badText={`${diag?.deepl.env ?? draft.deepl_auth_key_env} tanımlı değil (DeepL kullanmayacaksanız sorun değil)`}
                  neutral
                />
                <Row
                  label="Anahtarın ortam değişkeni"
                  error={errors.deepl_auth_key_env}
                  dflt={isDefault("deepl_auth_key_env")}
                  onReset={() => reset("deepl_auth_key_env")}
                >
                  <input value={draft.deepl_auth_key_env} spellCheck={false} onChange={(e) => set("deepl_auth_key_env", e.target.value)} />
                </Row>
              </Section>

              <Section id="ollama" title="Ollama" lede="Bilgisayarınızda çalışan yerel model; ücretsiz.">
                <StatusLine
                  ok={!!diag?.ollama.reachable}
                  loading={diagBusy}
                  okText={
                    diag?.ollama.has_model === false
                      ? `Bağlandı, ama ${diag.ollama.model ?? "model"} indirilmemiş (ollama pull)`
                      : `Bağlandı · ${(diag?.ollama.models ?? []).length} model`
                  }
                  badText={diag?.ollama.note ?? "Ollama'ya ulaşılamadı (kullanmayacaksanız sorun değil)"}
                  neutral
                />
                <Row label="Adres" error={errors.ollama_url} dflt={isDefault("ollama_url")} onReset={() => reset("ollama_url")}>
                  <div className="settings__inline">
                    <input value={draft.ollama_url} spellCheck={false} onChange={(e) => set("ollama_url", e.target.value)} />
                    <Button icon={<ArrowsClockwise />} disabled={diagBusy || !api} onClick={() => void refreshDiag()}>
                      Bağlantıyı sına
                    </Button>
                  </div>
                </Row>
                <Row label="Model" dflt={isDefault("ollama_model")} onReset={() => reset("ollama_model")}>
                  <input value={draft.ollama_model} spellCheck={false} onChange={(e) => set("ollama_model", e.target.value)} />
                </Row>
              </Section>

              <Section id="appearance" title="Görünüm" lede="Bu ayarlar yalnızca bu bilgisayardaki uygulamayı etkiler.">
                <Row label="Tema">
                  <Segmented
                    value={theme}
                    onChange={(v) => onTheme(v)}
                    items={[
                      { value: "light", label: "Açık" },
                      { value: "dark", label: "Koyu" },
                      { value: "system", label: "Sistem" },
                    ]}
                    label="Tema"
                  />
                </Row>
                <Row label="Kitap açılınca görünüm">
                  <select value={mode} onChange={(e) => chooseMode(e.target.value as ViewMode)}>
                    {VIEW_MODES.map((m) => (
                      <option key={m} value={m}>
                        {MODE_LABELS[m]}
                      </option>
                    ))}
                  </select>
                </Row>
              </Section>

              <Section id="data" title="Veri" lede="Çeviriler, kelime defteri ve sözlük bu klasörlerde durur.">
                {diag ? (
                  <dl className="settings__paths">
                    <PathRow label="Veri klasörü" path={diag.paths.data_dir} onCopy={copy} onOpen={isTauri() ? open : undefined} />
                    <PathRow label="Ayar klasörü" path={diag.paths.config_dir} onCopy={copy} onOpen={isTauri() ? open : undefined} />
                    <PathRow label="Ayar dosyası" path={view.config_path} onCopy={copy} />
                    <PathRow label="Veritabanı" path={`${diag.paths.db} · ${formatBytes(diag.paths.db_bytes)}`} onCopy={() => copy(diag.paths.db)} />
                  </dl>
                ) : (
                  <Skeleton width="100%" height={120} />
                )}
              </Section>

              <Section id="status" title="Motor durumu" lede="Bir şey çalışmıyorsa nedeni burada görünür. Bu kontroller yapay zekâya istek göndermez.">
                <div className="settings__statusbar">
                  <Button icon={<ArrowsClockwise />} disabled={diagBusy || !api} onClick={() => void refreshDiag()}>
                    {diagBusy ? "Denetleniyor…" : "Yeniden denetle"}
                  </Button>
                </div>
                {diag ? (
                  <ul className="settings__checks">
                    <Check ok label="Motor" detail={`Rosetta ${diag.engine.version} · Python ${diag.engine.python} · PyMuPDF ${diag.engine.pymupdf}${diag.engine.frozen ? " · paket" : ""}`} />
                    <Check ok={!!diag.claude.path} label="claude CLI" detail={diag.claude.path ? `${diag.claude.version ?? "?"} — ${diag.claude.path}` : "bulunamadı"} />
                    <Check
                      ok={diag.dictionary.present}
                      warn
                      label="Sözlük"
                      detail={diag.dictionary.present ? `${(diag.dictionary.entries ?? 0).toLocaleString("tr-TR")} madde` : "kurulmamış — terminalde: rosetta dict build"}
                    />
                    <Check ok={!!diag.chromium} warn label="PDF dışa aktarım (Chromium)" detail={diag.chromium ?? "bulunamadı — PDF dışa aktarım çalışmaz"} />
                    <Check ok={diag.deepl.key_set} warn label="DeepL anahtarı" detail={diag.deepl.key_set ? `${diag.deepl.env} tanımlı` : `${diag.deepl.env} tanımlı değil`} />
                    <Check ok={!!diag.ollama.reachable} warn label="Ollama" detail={diag.ollama.reachable ? "erişilebilir" : diag.ollama.note ?? "erişilemiyor"} />
                  </ul>
                ) : (
                  <Skeleton width="100%" height={180} />
                )}
              </Section>
            </>
          )}
        </main>
      </div>
    </div>
  );
}

const LANG_LABEL: Record<string, string> = {
  tr: "Türkçe",
  de: "Almanca",
  fr: "Fransızca",
  es: "İspanyolca",
  it: "İtalyanca",
  en: "İngilizce",
};

const SOURCE_LABEL: Record<Diagnostics["claude"]["source"], string> = {
  settings: "ayarlardaki yol",
  path: "PATH'ten bulundu",
  fallback: "kurulum klasöründen otomatik bulundu",
  missing: "bulunamadı",
};

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 ** 2) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / 1024 ** 2).toFixed(1)} MB`;
}

function Section({ id, title, lede, children }: { id: SettingsSection; title: string; lede?: string; children: ReactNode }) {
  return (
    <section id={`set-${id}`} className="settings__section" aria-labelledby={`set-${id}-h`}>
      <h2 id={`set-${id}-h`}>{title}</h2>
      {lede && <p className="settings__lede">{lede}</p>}
      <div className="settings__card">{children}</div>
    </section>
  );
}

function Row({
  label,
  hint,
  error,
  dflt,
  onReset,
  children,
}: {
  label: string;
  hint?: string;
  error?: string;
  dflt?: boolean;
  onReset?: () => void;
  children: ReactNode;
}) {
  return (
    <div className={`settings__row${error ? " has-error" : ""}`}>
      <div className="settings__label">
        <span>{label}</span>
        {dflt === false && onReset && (
          <button type="button" className="settings__reset" onClick={onReset} title="Varsayılana dön">
            varsayılana dön
          </button>
        )}
        {hint && <small>{hint}</small>}
      </div>
      <div className="settings__control">
        {children}
        {error && (
          <p className="settings__error" role="alert">
            {error}
          </p>
        )}
      </div>
    </div>
  );
}

function ModelInput({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const known = ["sonnet", "haiku"];
  const custom = !known.includes(value);
  return (
    <div className="settings__inline">
      <select value={custom ? "__custom" : value} onChange={(e) => onChange(e.target.value === "__custom" ? "" : e.target.value)}>
        <option value="sonnet">Sonnet (önerilen)</option>
        <option value="haiku">Haiku (hızlı taslak)</option>
        <option value="__custom">Diğer…</option>
      </select>
      {custom && <input value={value} placeholder="model adı" spellCheck={false} onChange={(e) => onChange(e.target.value)} />}
    </div>
  );
}

function Money({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <div className="settings__money">
      <span aria-hidden="true">$</span>
      <input inputMode="decimal" value={value} placeholder="sınır yok" onChange={(e) => onChange(e.target.value)} />
    </div>
  );
}

function StatusLine({
  ok,
  loading,
  okText,
  badText,
  neutral,
}: {
  ok: boolean;
  loading?: boolean;
  okText: string;
  badText: string;
  neutral?: boolean;
}) {
  if (loading) return <p className="settings__status settings__muted">Denetleniyor…</p>;
  return (
    <p className={`settings__status ${ok ? "is-ok" : neutral ? "is-neutral" : "is-bad"}`}>
      {ok ? <CheckCircle weight="fill" /> : neutral ? <WarningCircle /> : <XCircle weight="fill" />}
      <span>{ok ? okText : badText}</span>
    </p>
  );
}

function Check({ ok, warn, label, detail }: { ok: boolean; warn?: boolean; label: string; detail: string }) {
  return (
    <li className={ok ? "is-ok" : warn ? "is-warn" : "is-bad"}>
      {ok ? <CheckCircle weight="fill" /> : warn ? <WarningCircle weight="fill" /> : <XCircle weight="fill" />}
      <span className="settings__checklabel">{label}</span>
      <span className="settings__checkdetail">{detail}</span>
      <Badge tone={ok ? "sage" : warn ? "amber" : "danger"}>{ok ? "tamam" : warn ? "isteğe bağlı" : "sorun"}</Badge>
    </li>
  );
}

function PathRow({ label, path, onCopy, onOpen }: { label: string; path: string; onCopy: (p: string) => void; onOpen?: (p: string) => void }) {
  return (
    <div className="settings__pathrow">
      <dt>{label}</dt>
      <dd>
        <code>{path}</code>
        <IconButton label="Kopyala" size="sm" onClick={() => onCopy(path)}>
          <Copy />
        </IconButton>
        {onOpen && (
          <IconButton label="Klasörü aç" size="sm" onClick={() => onOpen(path)}>
            <FolderOpen />
          </IconButton>
        )}
      </dd>
    </div>
  );
}

function Notice({ tone, children }: { tone: "danger" | "neutral"; children: ReactNode }) {
  return (
    <div className={`settings__notice settings__notice--${tone}`} role={tone === "danger" ? "alert" : undefined}>
      {children}
    </div>
  );
}
