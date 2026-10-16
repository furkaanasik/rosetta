import { isTauri } from "../lib/engineConnect";

export type DropState = "idle" | "over";

/**
 * File drops onto the window. Tauri intercepts OS drag-and-drop and hands us real file paths
 * (HTML5 drop events carry no path). In a plain browser (dev) drops can't be opened by path.
 */
export async function onPdfDrop(cb: { state: (s: DropState) => void; drop: (path: string) => void }): Promise<() => void> {
  if (!isTauri()) return () => undefined;
  const { getCurrentWebview } = await import("@tauri-apps/api/webview");
  return getCurrentWebview().onDragDropEvent((e) => {
    const p = e.payload;
    if (p.type === "enter" || p.type === "over") cb.state("over");
    else if (p.type === "leave") cb.state("idle");
    else if (p.type === "drop") {
      cb.state("idle");
      const pdf = p.paths.find((x) => x.toLowerCase().endsWith(".pdf"));
      if (pdf) cb.drop(pdf);
    }
  });
}
