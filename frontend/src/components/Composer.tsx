import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { KeyboardEvent } from "react";
import type { ChatOptions } from "../types";
import { SendIcon, SlidersIcon, StopIcon } from "./Icons";

export const DEFAULT_OPTIONS: ChatOptions = {
  include_live: null,
  include_covers: null,
  target_count: null,
};

const isCustom = (o: ChatOptions) =>
  o.include_live !== null || o.include_covers !== null || o.target_count !== null;

function OptionsPopover({
  options,
  onChange,
}: {
  options: ChatOptions;
  onChange: (o: ChatOptions) => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false);
    };
    const esc = (e: globalThis.KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("mousedown", away);
      document.removeEventListener("keydown", esc);
    };
  }, [open]);

  return (
    <div className="options" ref={ref}>
      <button
        type="button"
        className={`icon-btn ${isCustom(options) ? "dot" : ""}`}
        onClick={() => setOpen(!open)}
        aria-label="Search options"
        aria-expanded={open}
        title="Search options"
      >
        <SlidersIcon />
      </button>
      {open && (
        <div className="popover" role="dialog" aria-label="Search options">
          <label className="check">
            <input
              type="checkbox"
              checked={options.include_live === true}
              onChange={(e) => onChange({ ...options, include_live: e.target.checked || null })}
            />
            Include live recordings
          </label>
          <label className="check">
            <input
              type="checkbox"
              checked={options.include_covers === true}
              onChange={(e) => onChange({ ...options, include_covers: e.target.checked || null })}
            />
            Include covers
          </label>
          <label className="range">
            <span>
              Songs per theme: <strong>{options.target_count ?? "auto"}</strong>
            </span>
            <input
              type="range"
              min={3}
              max={25}
              value={options.target_count ?? 10}
              onChange={(e) => onChange({ ...options, target_count: Number(e.target.value) })}
            />
          </label>
          {isCustom(options) && (
            <button type="button" className="link" onClick={() => onChange(DEFAULT_OPTIONS)}>
              Reset to automatic
            </button>
          )}
        </div>
      )}
    </div>
  );
}

export default function Composer({
  draft,
  setDraft,
  running,
  onSend,
  onStop,
  options,
  setOptions,
  placeholder,
}: {
  draft: string;
  setDraft: (v: string) => void;
  running: boolean;
  onSend: () => void;
  onStop: () => void;
  options: ChatOptions;
  setOptions: (o: ChatOptions) => void;
  placeholder: string;
}) {
  const area = useRef<HTMLTextAreaElement>(null);

  // Grow with the text, up to a cap.
  useLayoutEffect(() => {
    const el = area.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }, [draft]);

  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      if (!running && draft.trim()) onSend();
    }
  };

  return (
    <form
      className="composer"
      onSubmit={(e) => {
        e.preventDefault();
        if (!running && draft.trim()) onSend();
      }}
    >
      <textarea
        ref={area}
        rows={1}
        value={draft}
        maxLength={2000}
        autoFocus
        placeholder={placeholder}
        aria-label="Message"
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={onKey}
      />
      <div className="composer-bar">
        <OptionsPopover options={options} onChange={setOptions} />
        <span className="hint-keys muted">Enter to send · Shift+Enter for a new line</span>
        {running ? (
          <button type="button" className="send stop" onClick={onStop} aria-label="Stop">
            <StopIcon />
          </button>
        ) : (
          <button className="send" disabled={!draft.trim()} aria-label="Send">
            <SendIcon />
          </button>
        )}
      </div>
    </form>
  );
}
