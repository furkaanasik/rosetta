import { Fragment, type ReactNode } from "react";

/** `**bold**` spans inside one line, as React nodes (never innerHTML). */
function inline(line: string): ReactNode[] {
  return line.split(/(\*\*[^*]+\*\*)/g).map((part, i) =>
    part.startsWith("**") && part.endsWith("**") && part.length > 4 ? (
      <strong key={i}>{part.slice(2, -2)}</strong>
    ) : (
      <Fragment key={i}>{part}</Fragment>
    ),
  );
}

/**
 * Renders the engine's explanation text (a small Markdown subset: paragraphs, `**bold**`,
 * `- ` list items). The text comes from the model, so it is only ever rendered as text nodes.
 */
export function ExplanationText({ text }: { text: string }) {
  const blocks = text.trim().split(/\n{2,}/);
  return (
    <div className="explanation">
      {blocks.map((block, i) => {
        const lines = block.split("\n");
        const items = lines.filter((l) => l.startsWith("- "));
        const head = lines.filter((l) => !l.startsWith("- "));
        return (
          <Fragment key={i}>
            {head.length > 0 && <p>{inline(head.join(" "))}</p>}
            {items.length > 0 && (
              <ul>
                {items.map((l, j) => (
                  <li key={j}>{inline(l.slice(2))}</li>
                ))}
              </ul>
            )}
          </Fragment>
        );
      })}
    </div>
  );
}
