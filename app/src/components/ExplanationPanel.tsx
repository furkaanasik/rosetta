import { X } from "@phosphor-icons/react";
import { useRef } from "react";
import type { Explanation } from "../api/types";
import { useModalFocus } from "../lib/useModalFocus";
import { Badge, Button, IconButton } from "../ui";
import { ExplanationText } from "./ExplanationText";

/** "Bunu açıkla" result: a wide reading sheet sliding in from the right. */
export function ExplanationPanel({ explanation, onClose }: { explanation: Explanation; onClose: () => void }) {
  const dialog = useRef<HTMLDivElement>(null);
  const close = useRef<HTMLButtonElement>(null);
  useModalFocus(dialog, onClose, close);
  return (
    <div className="dialog-scrim dialog-scrim--side" role="presentation" onClick={onClose}>
      <div
        ref={dialog}
        tabIndex={-1}
        className="slideover explain"
        role="dialog"
        aria-modal="true"
        aria-label="Açıklama"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="slideover__head">
          <h2 className="slideover__title">Açıklama</h2>
          {explanation.cached && <Badge tone="sage">önbellekten</Badge>}
          <IconButton label="Açıklamayı kapat" className="slideover__close" onClick={onClose}>
            <X />
          </IconButton>
        </header>
        <div className="slideover__body">
          <blockquote className="explain__quote">{explanation.text}</blockquote>
          <ExplanationText text={explanation.explanation} />
        </div>
        <footer className="slideover__foot">
          <span className="muted small">{explanation.model}</span>
          <Button ref={close} variant="secondary" onClick={onClose}>
            Kapat
          </Button>
        </footer>
      </div>
    </div>
  );
}
