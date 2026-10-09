import { useCallback, useEffect, useRef, useState } from "react";
import { useI18n } from "../../i18n/I18nContext.jsx";
import { TELEGRAM_DM, buildOrderPayload } from "../../lib/whatsapp.js";

const CHAT_WIDTH_KEY = "ak-chat-width";
const CHAT_WIDTH_DEFAULT = 340;
const CHAT_WIDTH_MIN = 280;
const CHAT_WIDTH_MAX = 560;
const CHAT_MAX_FILES = 3;
const CHAT_MAX_FILE_BYTES = 4 * 1024 * 1024;
const CHAT_SUGGEST_KEYS = [
  "services.ai.photo.title",
  "services.ai.video.title",
  "services.ai.viz3d.title",
  "services.ai.anim.title",
  "services.ai.character.title",
  "services.design.carousel.title",
  "services.design.card.title",
  "services.design.info.title",
  "services.design.pack.title",
];

function chatWidthLimits() {
  const maxByViewport = Math.max(CHAT_WIDTH_MIN, window.innerWidth - 24);
  return {
    min: CHAT_WIDTH_MIN,
    max: Math.min(CHAT_WIDTH_MAX, maxByViewport),
  };
}

function clampChatWidth(value) {
  const limits = chatWidthLimits();
  const width = Number(value);
  if (!Number.isFinite(width)) return CHAT_WIDTH_DEFAULT;
  return Math.round(Math.min(limits.max, Math.max(limits.min, width)));
}

function loadSavedWidth() {
  try {
    const raw = sessionStorage.getItem(CHAT_WIDTH_KEY);
    if (raw) return clampChatWidth(Number(raw));
  } catch (_) {}
  return CHAT_WIDTH_DEFAULT;
}

function readFileAsDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(reader.error || new Error("read failed"));
    reader.readAsDataURL(file);
  });
}

function ChatBubbleContent({ text }) {
  const value = String(text || "");
  const tokenRe =
    /\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)|(https?:\/\/[^\s<>"'）)\]]+)/g;
  const nodes = [];
  let lastIndex = 0;
  let match;
  let key = 0;
  while ((match = tokenRe.exec(value))) {
    if (match.index > lastIndex) {
      nodes.push(value.slice(lastIndex, match.index));
    }
    if (match[1] && match[2]) {
      nodes.push(
        <a
          key={key++}
          href={match[2]}
          target="_blank"
          rel="noopener noreferrer"
          className="chat-link"
        >
          {match[1]}
        </a>
      );
    } else {
      let href = match[3].replace(/[.,;:!?]+$/g, "");
      const trailing = match[3].slice(href.length);
      nodes.push(
        <a
          key={key++}
          href={href}
          target="_blank"
          rel="noopener noreferrer"
          className="chat-link"
        >
          {href}
        </a>
      );
      if (trailing) nodes.push(trailing);
    }
    lastIndex = match.index + match[0].length;
  }
  if (lastIndex < value.length) {
    nodes.push(value.slice(lastIndex));
  }
  return <>{nodes.length ? nodes : value}</>;
}

function ChatBubble({ role, text, extraClass, files }) {
  return (
    <div
      className={
        "chat-bubble " +
        (role === "user" ? "chat-bubble-user" : "chat-bubble-bot") +
        (extraClass ? " " + extraClass : "")
      }
    >
      {text ? <ChatBubbleContent text={text} /> : null}
      {files && files.length ? (
        <div className="chat-bubble-files">
          {files.map((file) => (
            <span key={file.name + (file.preview || "")} className="chat-bubble-file">
              {file.preview ? (
                <img src={file.preview} alt={file.name || ""} />
              ) : null}
              <span>{file.name || "file"}</span>
            </span>
          ))}
        </div>
      ) : null}
    </div>
  );
}

export default function ChatWidget({ visitorId, onOpenLead }) {
  const { t, lang } = useI18n();
  const [open, setOpen] = useState(false);
  const [panelVisible, setPanelVisible] = useState(false);
  const [panelHidden, setPanelHidden] = useState(true);
  const [width, setWidth] = useState(loadSavedWidth);
  const [input, setInput] = useState("");
  const [bubbles, setBubbles] = useState([]);
  const [history, setHistory] = useState([]);
  const [started, setStarted] = useState(false);
  const [busy, setBusy] = useState(false);
  const [attachments, setAttachments] = useState([]);
  const [attachMenuOpen, setAttachMenuOpen] = useState(false);
  const [resizing, setResizing] = useState(false);

  const messagesRef = useRef(null);
  const inputRef = useRef(null);
  const fileRef = useRef(null);
  const attachWrapRef = useRef(null);
  const panelRef = useRef(null);
  const resizeRef = useRef(null);
  const historyRef = useRef([]);
  const busyRef = useRef(false);
  const startedRef = useRef(false);
  const chatAbortRef = useRef(null);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      chatAbortRef.current?.abort();
    };
  }, []);

  useEffect(() => {
    historyRef.current = history;
  }, [history]);
  useEffect(() => {
    busyRef.current = busy;
  }, [busy]);
  useEffect(() => {
    startedRef.current = started;
  }, [started]);

  const applyWidth = useCallback((value) => {
    const next = clampChatWidth(value);
    setWidth(next);
    try {
      sessionStorage.setItem(CHAT_WIDTH_KEY, String(next));
    } catch (_) {}
    return next;
  }, []);

  useEffect(() => {
    function onResize() {
      applyWidth(width);
    }
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, [applyWidth, width]);

  useEffect(() => {
    const el = messagesRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [bubbles, open, panelVisible]);

  const ensureWelcome = useCallback(() => {
    if (startedRef.current) return;
    setBubbles([{ id: "welcome", role: "assistant", text: t("chat.welcome") }]);
  }, [t]);

  // Refresh welcome / suggestions on lang change before chat starts
  useEffect(() => {
    if (!started) {
      if (open) {
        setBubbles([
          { id: "welcome", role: "assistant", text: t("chat.welcome") },
        ]);
      }
    }
  }, [lang, t, started, open]);

  // bfcache restore — reset in-memory chat on pageshow
  useEffect(() => {
    function onPageShow(event) {
      if (!event.persisted) return;
      setHistory([]);
      setStarted(false);
      setBusy(false);
      setAttachments([]);
      setInput("");
      setBubbles([]);
      if (open) {
        setBubbles([
          { id: "welcome", role: "assistant", text: t("chat.welcome") },
        ]);
      }
    }
    window.addEventListener("pageshow", onPageShow);
    return () => window.removeEventListener("pageshow", onPageShow);
  }, [open, t]);

  const setChatOpen = useCallback(
    (nextOpen) => {
      if (nextOpen) {
        setOpen(true);
        setPanelHidden(false);
        ensureWelcome();
        requestAnimationFrame(() => {
          setPanelVisible(true);
          inputRef.current?.focus();
        });
        return;
      }
      setOpen(false);
      setPanelVisible(false);
    },
    [ensureWelcome]
  );

  useEffect(() => {
    if (open || panelHidden) return undefined;
    const timer = window.setTimeout(() => setPanelHidden(true), 280);
    return () => window.clearTimeout(timer);
  }, [open, panelHidden]);

  useEffect(() => {
    function onKey(event) {
      if (event.key !== "Escape") return;
      if (attachMenuOpen) {
        setAttachMenuOpen(false);
        return;
      }
      if (open) setChatOpen(false);
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, attachMenuOpen, setChatOpen]);

  useEffect(() => {
    if (!attachMenuOpen) return undefined;
    function onPointerDown(event) {
      const wrap = attachWrapRef.current;
      if (wrap && !wrap.contains(event.target)) {
        setAttachMenuOpen(false);
      }
    }
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [attachMenuOpen]);

  useEffect(() => {
    if (!open || busy || attachments.length >= CHAT_MAX_FILES) {
      setAttachMenuOpen(false);
    }
  }, [open, busy, attachments.length]);

  // Resize handlers
  useEffect(() => {
    const handle = resizeRef.current;
    const panel = panelRef.current;
    if (!handle || !panel) return undefined;

    let active = false;

    const onPointerMove = (event) => {
      if (!active) return;
      const rect = panel.getBoundingClientRect();
      applyWidth(rect.right - event.clientX);
    };

    const stopResize = () => {
      if (!active) return;
      active = false;
      setResizing(false);
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
      window.removeEventListener("pointermove", onPointerMove);
      window.removeEventListener("pointerup", stopResize);
      window.removeEventListener("pointercancel", stopResize);
    };

    const onPointerDown = (event) => {
      if (event.button != null && event.button !== 0) return;
      event.preventDefault();
      active = true;
      setResizing(true);
      document.body.style.cursor = "ew-resize";
      document.body.style.userSelect = "none";
      try {
        handle.setPointerCapture(event.pointerId);
      } catch (_) {}
      window.addEventListener("pointermove", onPointerMove);
      window.addEventListener("pointerup", stopResize);
      window.addEventListener("pointercancel", stopResize);
    };

    handle.addEventListener("pointerdown", onPointerDown);
    return () => {
      handle.removeEventListener("pointerdown", onPointerDown);
      stopResize();
    };
  }, [applyWidth, panelHidden]);

  function onResizeKey(event) {
    const step = event.shiftKey ? 24 : 12;
    if (event.key === "ArrowLeft") {
      event.preventDefault();
      applyWidth(width + step);
    } else if (event.key === "ArrowRight") {
      event.preventDefault();
      applyWidth(width - step);
    } else if (event.key === "Home") {
      event.preventDefault();
      applyWidth(chatWidthLimits().max);
    } else if (event.key === "End") {
      event.preventDefault();
      applyWidth(chatWidthLimits().min);
    }
  }

  async function addChatFiles(fileList) {
    const files = Array.from(fileList || []);
    if (!files.length) return;

    const loaded = [];
    for (const file of files) {
      if (file.size > CHAT_MAX_FILE_BYTES) {
        setBubbles((prev) => [
          ...prev,
          {
            id: String(Date.now()) + file.name,
            role: "assistant",
            text: t("chat.fileTooBig") + ": " + file.name,
          },
        ]);
        continue;
      }
      try {
        const dataUrl = await readFileAsDataUrl(file);
        loaded.push({
          name: file.name,
          type: file.type || "application/octet-stream",
          data: dataUrl,
          preview: file.type && file.type.startsWith("image/") ? dataUrl : "",
        });
      } catch (_) {
        setBubbles((prev) => [
          ...prev,
          { id: String(Date.now()), role: "assistant", text: t("chat.error") },
        ]);
      }
    }
    if (!loaded.length) return;

    let limited = false;
    setAttachments((prev) => {
      const room = CHAT_MAX_FILES - prev.length;
      if (room <= 0) {
        limited = true;
        return prev;
      }
      if (loaded.length > room) limited = true;
      return [...prev, ...loaded.slice(0, room)];
    });
    if (limited) {
      setBubbles((prev) => [
        ...prev,
        { id: String(Date.now()), role: "assistant", text: t("chat.fileLimit") },
      ]);
    }
  }

  async function sendChatMessage(rawText) {
    const text = String(rawText || "").trim();
    const pending = attachments.slice();
    if ((!text && !pending.length) || busyRef.current) return;

    // Lock immediately — useEffect sync of busyRef is one frame too late.
    busyRef.current = true;
    setStarted(true);
    setBusy(true);
    setInput("");
    setAttachments([]);

    const historyText =
      text ||
      (pending.length
        ? t("chat.fileOnly") + ": " + pending.map((item) => item.name).join(", ")
        : "");

    const userBubble = {
      id: "u-" + Date.now(),
      role: "user",
      text,
      files: pending.map((item) => ({ name: item.name, preview: item.preview })),
    };
    const typingId = "typing-" + Date.now();
    setBubbles((prev) => [
      ...prev,
      userBubble,
      {
        id: typingId,
        role: "assistant",
        text: t("chat.typing"),
        extraClass: "chat-bubble-typing",
      },
    ]);

    const nextHistory = [
      ...historyRef.current,
      { role: "user", content: historyText },
    ];
    setHistory(nextHistory);

    const controller =
      typeof AbortController !== "undefined" ? new AbortController() : null;
    chatAbortRef.current?.abort();
    chatAbortRef.current = controller;
    const timeoutId = controller
      ? window.setTimeout(() => controller.abort(), 35000)
      : null;

    try {
      const response = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        signal: controller ? controller.signal : undefined,
        body: JSON.stringify({
          lang,
          sessionId: visitorId,
          messages: nextHistory.slice(-12),
          attachments: pending.map((item) => ({
            name: item.name,
            type: item.type,
            data: item.data,
          })),
        }),
      });
      if (timeoutId) window.clearTimeout(timeoutId);
      if (!mountedRef.current) return;
      const data = await response.json().catch(() => ({}));
      if (!mountedRef.current) return;
      if (!response.ok) {
        setBubbles((prev) => [
          ...prev.filter((b) => b.id !== typingId),
          {
            id: "e-" + Date.now(),
            role: "assistant",
            text: data.error || t("chat.error"),
          },
        ]);
      } else {
        const reply = data.reply || t("chat.error");
        setBubbles((prev) => [
          ...prev.filter((b) => b.id !== typingId),
          { id: "a-" + Date.now(), role: "assistant", text: reply },
        ]);
        setHistory((prev) => [...prev, { role: "assistant", content: reply }]);
      }
    } catch (err) {
      if (timeoutId) window.clearTimeout(timeoutId);
      if (!mountedRef.current) return;
      // Superseded by a newer request or unmount — stay quiet.
      if (err?.name === "AbortError" && chatAbortRef.current !== controller) {
        return;
      }
      setBubbles((prev) => [
        ...prev.filter((b) => b.id !== typingId),
        { id: "e-" + Date.now(), role: "assistant", text: t("chat.error") },
      ]);
    } finally {
      const ownsLock = chatAbortRef.current === controller;
      if (ownsLock) chatAbortRef.current = null;
      if (!mountedRef.current) return;
      // Only the active request may clear busy — superseded ones must not.
      if (!ownsLock) return;
      busyRef.current = false;
      setBusy(false);
      inputRef.current?.focus();
    }
  }

  function handleChatWa() {
    onOpenLead?.(
      buildOrderPayload({
        source: "chat",
        serviceName: t("chat.title") || "AI chat",
        message: t("chat.waText"),
        visitorId,
        lang,
      })
    );
  }

  const showSuggestions = history.length === 0 && !started;

  return (
    <div className={`chat-widget${open ? " is-open" : ""}`} id="chat-widget">
      <div
        ref={panelRef}
        className={`chat-panel${panelVisible ? " is-visible" : ""}${
          resizing ? " is-resizing" : ""
        }`}
        id="chat-panel"
        role="dialog"
        aria-modal="false"
        aria-labelledby="chat-panel-title"
        hidden={panelHidden}
        data-width={String(width)}
        style={{ ["--chat-width"]: width + "px" }}
      >
        <div
          ref={resizeRef}
          className="chat-resize"
          id="chat-resize"
          role="separator"
          aria-orientation="vertical"
          aria-controls="chat-panel"
          aria-label={t("chat.resize")}
          tabIndex={0}
          onKeyDown={onResizeKey}
        />
        <div className="chat-head">
          <div>
            <p className="chat-panel-title" id="chat-panel-title">
              {t("chat.title")}
            </p>
            <p className="chat-panel-hint">{t("chat.hint")}</p>
          </div>
          <span className="chat-status">{t("chat.status")}</span>
        </div>

        <div className="chat-messages" id="chat-messages" aria-live="polite" ref={messagesRef}>
          {bubbles.map((bubble) => (
            <ChatBubble
              key={bubble.id}
              role={bubble.role}
              text={bubble.text}
              extraClass={bubble.extraClass}
              files={bubble.files}
            />
          ))}
        </div>

        <div
          className="chat-suggestions"
          id="chat-suggestions"
          hidden={!showSuggestions}
        >
          {showSuggestions
            ? CHAT_SUGGEST_KEYS.map((key) => (
                <button
                  key={key}
                  type="button"
                  className="chat-chip"
                  disabled={busy}
                  onClick={() => sendChatMessage(t(key))}
                >
                  {t(key)}
                </button>
              ))
            : null}
        </div>

        <div
          className="chat-attachments"
          id="chat-attachments"
          hidden={!attachments.length}
        >
          {attachments.map((file, index) => (
            <div key={file.name + index} className="chat-attachment-chip">
              {file.preview ? (
                <img
                  className="chat-attachment-thumb"
                  src={file.preview}
                  alt=""
                />
              ) : null}
              <span className="chat-attachment-name">{file.name}</span>
              <button
                type="button"
                className="chat-attachment-remove"
                aria-label={t("chat.removeFile")}
                onClick={() =>
                  setAttachments((prev) => prev.filter((_, i) => i !== index))
                }
              >
                ×
              </button>
            </div>
          ))}
        </div>

        <form
          className="chat-form"
          id="chat-form"
          onSubmit={(event) => {
            event.preventDefault();
            sendChatMessage(input);
          }}
        >
          <input
            ref={fileRef}
            id="chat-file"
            className="chat-file-input"
            type="file"
            multiple
            hidden
            onChange={(event) => {
              addChatFiles(event.target.files);
              event.target.value = "";
            }}
          />
          <div className="chat-composer">
            <div className="chat-attach-wrap" ref={attachWrapRef}>
              <button
                type="button"
                className="chat-attach"
                id="chat-attach"
                aria-label={t("chat.attach")}
                title={t("chat.attach")}
                aria-haspopup="menu"
                aria-expanded={attachMenuOpen}
                disabled={busy || attachments.length >= CHAT_MAX_FILES}
                onClick={() => setAttachMenuOpen((prev) => !prev)}
              >
                <span aria-hidden="true">+</span>
              </button>
              {attachMenuOpen ? (
                <div
                  className="chat-attach-menu"
                  id="chat-attach-menu"
                  role="menu"
                  aria-label={t("chat.attach")}
                >
                  <button
                    type="button"
                    className="chat-attach-option"
                    role="menuitem"
                    onClick={() => {
                      setAttachMenuOpen(false);
                      const input = fileRef.current;
                      if (!input) return;
                      input.accept = "image/*";
                      input.click();
                    }}
                  >
                    <span className="chat-attach-option-icon" aria-hidden="true">
                      <svg viewBox="0 0 24 24" width="16" height="16" fill="none">
                        <rect
                          x="4"
                          y="5"
                          width="16"
                          height="14"
                          rx="2"
                          stroke="currentColor"
                          strokeWidth="1.6"
                        />
                        <circle cx="9" cy="10" r="1.4" fill="currentColor" />
                        <path
                          d="M4 16.5l4.2-4.2a1.2 1.2 0 0 1 1.7 0L16 18M13 14l1.3-1.3a1.2 1.2 0 0 1 1.7 0L20 17"
                          stroke="currentColor"
                          strokeWidth="1.6"
                          strokeLinecap="round"
                          strokeLinejoin="round"
                        />
                      </svg>
                    </span>
                    {t("chat.attachPhoto")}
                  </button>
                  <button
                    type="button"
                    className="chat-attach-option"
                    role="menuitem"
                    onClick={() => {
                      setAttachMenuOpen(false);
                      const input = fileRef.current;
                      if (!input) return;
                      // Empty accept = any file type (pdf, video, archive, etc.)
                      input.accept = "";
                      input.click();
                    }}
                  >
                    <span className="chat-attach-option-icon" aria-hidden="true">
                      <svg viewBox="0 0 24 24" width="16" height="16" fill="none">
                        <path
                          d="M8 3.5h6.2L18.5 8v12.5a1 1 0 0 1-1 1H8a1 1 0 0 1-1-1V4.5a1 1 0 0 1 1-1z"
                          stroke="currentColor"
                          strokeWidth="1.6"
                          strokeLinejoin="round"
                        />
                        <path
                          d="M14 3.5V8h4.5M9.5 13h5M9.5 16.5h5"
                          stroke="currentColor"
                          strokeWidth="1.6"
                          strokeLinecap="round"
                          strokeLinejoin="round"
                        />
                      </svg>
                    </span>
                    <span className="chat-attach-option-text">
                      <span>{t("chat.attachFile")}</span>
                      <span className="chat-attach-option-hint">
                        {t("chat.attachFileHint")}
                      </span>
                    </span>
                  </button>
                </div>
              ) : null}
            </div>
            <label className="visually-hidden" htmlFor="chat-input">
              {t("chat.placeholder")}
            </label>
            <input
              ref={inputRef}
              id="chat-input"
              className="chat-input"
              type="text"
              autoComplete="off"
              maxLength={800}
              placeholder={t("chat.placeholder")}
              value={input}
              disabled={busy}
              onChange={(event) => setInput(event.target.value)}
            />
          </div>
          <button
            type="submit"
            className="chat-send"
            aria-label={t("chat.send")}
            disabled={busy}
          >
            <svg viewBox="0 0 24 24" width="18" height="18" fill="none" aria-hidden="true">
              <path
                d="M5 12h12M13 6l6 6-6 6"
                stroke="currentColor"
                strokeWidth="1.8"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </button>
        </form>

        <div className="chat-handoff">
          <span>{t("chat.handoff")}</span>
          <div className="chat-handoff-links">
            <a href={TELEGRAM_DM} target="_blank" rel="noopener noreferrer">
              {t("chat.telegram")}
            </a>
            <button type="button" className="js-chat-wa" onClick={handleChatWa}>
              {t("chat.whatsapp")}
            </button>
          </div>
        </div>
      </div>
      <button
        type="button"
        className="chat-fab"
        id="chat-fab"
        aria-expanded={open ? "true" : "false"}
        aria-controls="chat-panel"
        aria-label={t(open ? "chat.close" : "chat.open")}
        onClick={() => setChatOpen(!open)}
      >
        <span className="chat-fab-label chat-fab-open">{t("chat.fab")}</span>
        <span className="chat-fab-icon chat-fab-close" aria-hidden="true">
          <svg viewBox="0 0 24 24" width="18" height="18" fill="none">
            <path
              d="M7 7l10 10M17 7 7 17"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinecap="round"
            />
          </svg>
        </span>
      </button>
    </div>
  );
}
