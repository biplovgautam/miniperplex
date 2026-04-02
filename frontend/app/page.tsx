"use client";

import { AnimatePresence, motion } from "framer-motion";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import type {
  AnchorHTMLAttributes,
  KeyboardEvent,
  ReactNode,
} from "react";
import { FormEvent, useEffect, useMemo, useRef, useState } from "react";

type SourceItem = {
  index: number;
  title: string;
  url: string;
  site?: string;
  snippet?: string;
  favicon?: string;
};

type ChatMessage = {
  role: "user" | "assistant";
  content: string;
  sources?: SourceItem[];
  query?: string;
  status?: string;
};

type StatusPhase =
  | "idle"
  | "understanding"
  | "routing"
  | "searching"
  | "youtube"
  | "calculating"
  | "thinking";

const SSE_SEPARATOR = "\n\n";

const extractCitationIndexes = (body: string) => {
  const seen = new Set<number>();
  const ordered: number[] = [];
  for (const match of body.matchAll(/\[(\d+)]/g)) {
    const parsed = Number.parseInt(match[1], 10);
    if (!Number.isFinite(parsed) || seen.has(parsed)) {
      continue;
    }
    seen.add(parsed);
    ordered.push(parsed);
  }
  return ordered;
};

const getCitedSources = (body: string, sources: SourceItem[] = []) => {
  if (!body || sources.length === 0) {
    return [];
  }
  const cited = new Set(extractCitationIndexes(body));
  return sources
    .filter((source) => cited.has(source.index))
    .sort((first, second) => first.index - second.index);
};

const getSiteName = (url: string, fallback?: string) => {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return fallback ?? "source";
  }
};

const derivePhase = (status?: string): StatusPhase => {
  if (!status) {
    return "idle";
  }
  const normalized = status.toLowerCase();
  if (normalized.includes("youtube")) {
    return "youtube";
  }
  if (normalized.includes("searching")) {
    return "searching";
  }
  if (normalized.includes("routing")) {
    return "routing";
  }
  if (normalized.includes("understanding")) {
    return "understanding";
  }
  if (normalized.includes("response") || normalized.includes("calculating")) {
    return "calculating";
  }
  if (normalized.includes("thinking")) {
    return "thinking";
  }
  return "thinking";
};

const statusLabels: Record<StatusPhase, string> = {
  idle: "Idle",
  understanding: "Understanding the request...",
  routing: "Routing to metals specialist...",
  searching: "Browsing market data...",
  youtube: "Transcribing video context...",
  calculating: "Calculating answer...",
  thinking: "Thinking through the response...",
};

const iconForPhase = (phase: StatusPhase) => {
  if (phase === "searching") {
    return (
      <svg
        viewBox="0 0 24 24"
        className="h-4 w-4 text-slate-500"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.4"
      >
        <path d="M12 2a10 10 0 1 0 10 10" />
        <path d="M2 12h20" />
        <path d="M12 2a15 15 0 0 1 0 20" />
      </svg>
    );
  }
  if (phase === "youtube") {
    return (
      <svg
        viewBox="0 0 24 24"
        className="h-4 w-4 text-rose-400"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.4"
      >
        <path d="M4 7h16" />
        <path d="M4 12h16" />
        <path d="M4 17h16" />
      </svg>
    );
  }
  return (
    <svg
      viewBox="0 0 24 24"
      className="h-4 w-4 text-slate-500"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.4"
    >
      <circle cx="12" cy="12" r="8" />
      <path d="M12 8v4l3 3" />
    </svg>
  );
};

const buildSparkline = (seedText: string) => {
  let seed = 0;
  for (let i = 0; i < seedText.length; i += 1) {
    seed = (seed * 31 + seedText.charCodeAt(i)) % 9973;
  }
  const points = Array.from({ length: 12 }, (_, idx) => {
    seed = (seed * 9301 + 49297) % 233280;
    const value = 8 + (seed / 233280) * 12;
    const x = (idx / 11) * 64;
    const y = 24 - value;
    return `${x},${y}`;
  });
  return `M${points.join(" L")}`;
};

const extractMetrics = (content: string) => {
  const lines = content.split("\n");
  const metrics: { label: string; value: string }[] = [];
  for (const line of lines) {
    const match = line.match(/(\$[\d,]+(?:\.\d+)?(?:\s*(?:trillion|billion|million))?)/i);
    if (match) {
      const value = match[1];
      const label = line.replace(match[1], "").replace(/\[[^\]]+]/g, "").trim();
      metrics.push({ label: label || "Market data", value });
    }
  }
  return metrics.slice(0, 3);
};

export default function Home() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [tempChat, setTempChat] = useState(false);
  const controllerRef = useRef<AbortController | null>(null);
  const formRef = useRef<HTMLFormElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const messagesEndRef = useRef<HTMLDivElement | null>(null);
  const isEmpty = messages.length === 0;

  const suggestions = [
    {
      label: "Gold snapshot",
      prompt: "What is the gold price right now and what is driving it today?",
      icon: (
        <svg
          viewBox="0 0 24 24"
          className="h-4 w-4 text-slate-500"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.6"
        >
          <circle cx="12" cy="12" r="8" />
          <path d="M12 7v5l3 3" />
        </svg>
      ),
    },
    {
      label: "Silver snapshot",
      prompt: "How is silver trading today and what are the key catalysts?",
      icon: (
        <svg
          viewBox="0 0 24 24"
          className="h-4 w-4 text-slate-500"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.6"
        >
          <path d="M12 3l2.5 5 5.5.7-4 3.9.9 5.7-4.9-2.7-4.9 2.7.9-5.7-4-3.9 5.5-.7L12 3z" />
        </svg>
      ),
    },
    {
      label: "Gold market cap",
      prompt: "What is the total market cap of gold today?",
      icon: (
        <svg
          viewBox="0 0 24 24"
          className="h-4 w-4 text-slate-500"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.6"
        >
          <path d="M4 19h16" />
          <path d="M7 16V9" />
          <path d="M12 16V5" />
          <path d="M17 16v-3" />
        </svg>
      ),
    },
  ];

  const apiUrl = useMemo(
    () => process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000",
    []
  );

  const markdownComponents: Components = {
    a: ({ children, href, ...props }: AnchorHTMLAttributes<HTMLAnchorElement> & { children?: ReactNode }) => (
      <a
        href={href}
        target="_blank"
        rel="noreferrer"
        className="text-slate-900 underline decoration-slate-300 underline-offset-4 transition hover:decoration-slate-600"
        {...props}
      >
        {children}
      </a>
    ),
  };

  const focusComposer = () => {
    requestAnimationFrame(() => {
      const element = textareaRef.current;
      if (!element) {
        return;
      }
      element.focus();
      const caret = element.value.length;
      element.setSelectionRange(caret, caret);
    });
  };

  const scrollToBottom = (behavior: ScrollBehavior = "auto") => {
    requestAnimationFrame(() => {
      messagesEndRef.current?.scrollIntoView({ behavior, block: "end" });
    });
  };

  const applySuggestion = (prompt: string) => {
    setInput(prompt);
    focusComposer();
  };

  const handleComposerKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key !== "Enter" || event.shiftKey) {
      return;
    }
    event.preventDefault();
    if (isStreaming || !event.currentTarget.value.trim()) {
      return;
    }
    formRef.current?.requestSubmit();
  };

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const trimmed = input.trim();
    if (!trimmed || isStreaming) {
      return;
    }

    const historyPayload = messages
      .filter((message) => message.content.trim().length > 0)
      .slice(-6)
      .map(({ role, content }) => ({ role, content }));

    setInput("");
    setIsStreaming(true);
    focusComposer();

    const assistantIndex = messages.length + 1;
    setMessages((prev) => [
      ...prev,
      { role: "user", content: trimmed },
      { role: "assistant", content: "", sources: [], query: trimmed },
    ]);

    const controller = new AbortController();
    controllerRef.current = controller;

    try {
      const response = await fetch(`${apiUrl}/chat/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: trimmed, history: historyPayload }),
        signal: controller.signal,
      });

      if (!response.ok || !response.body) {
        throw new Error("Unable to stream response from the server.");
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      const handleEvent = (rawEvent: string) => {
        const lines = rawEvent.split("\n");
        let eventType = "message";
        const dataLines: string[] = [];

        for (const line of lines) {
          if (line.startsWith("event:")) {
            eventType = line.replace("event:", "").trim();
          } else if (line.startsWith("data:")) {
            const raw = line.slice(5);
            dataLines.push(raw.startsWith(" ") ? raw.slice(1) : raw);
          }
        }

        const data = dataLines.join("\n");

        if (eventType === "sources") {
          try {
            const payload = JSON.parse(data) as {
              query?: string;
              sources?: SourceItem[];
            };
            setMessages((prev) =>
              prev.map((message, index) =>
                index === assistantIndex
                  ? {
                      ...message,
                      sources: payload.sources ?? [],
                      query: payload.query ?? message.query,
                    }
                  : message
              )
            );
          } catch {
            // Ignore malformed source payloads.
          }
          return;
        }

        if (eventType === "status") {
          if (!data) {
            return;
          }
          setMessages((prev) =>
            prev.map((message, index) =>
              index === assistantIndex ? { ...message, status: data } : message
            )
          );
          return;
        }

        if (eventType === "token") {
          if (!data) {
            return;
          }
          setMessages((prev) =>
            prev.map((message, index) =>
              index === assistantIndex
                ? { ...message, content: message.content + data }
                : message
            )
          );
          return;
        }

        if (eventType === "done") {
          setMessages((prev) =>
            prev.map((message, index) =>
              index === assistantIndex ? { ...message, status: undefined } : message
            )
          );
          return;
        }
      };

      while (true) {
        const { value, done } = await reader.read();
        if (done) {
          break;
        }
        buffer += decoder.decode(value, { stream: true });
        const parts = buffer.split(SSE_SEPARATOR);
        buffer = parts.pop() ?? "";
        parts.forEach(handleEvent);
      }
    } catch (error) {
      const errorMessage =
        error instanceof Error ? error.message : "Streaming failed.";
      setMessages((prev) =>
        prev.map((message, index) =>
          index === assistantIndex
            ? { ...message, content: errorMessage }
            : message
        )
      );
    } finally {
      setIsStreaming(false);
      focusComposer();
    }
  };

  const inputForm = (variant: "hero" | "dock") => {
    const isHero = variant === "hero";
    return (
      <div className="relative w-full">
        {tempChat && (
          <div className="absolute -top-4 right-3 flex items-center gap-2 rounded-full border border-[var(--accent)]/40 bg-[var(--accent)]/10 px-3 py-1 text-[11px] font-semibold text-[var(--accent)]">
            <span className="inline-flex h-2 w-2 rounded-full bg-[var(--accent)]" />
            Temporary chat on
          </div>
        )}
        <form
          ref={formRef}
          onSubmit={handleSubmit}
          className={`w-full ${
            isHero
              ? "rounded-[32px] border border-white/50 bg-white/40 px-6 py-5 shadow-[0_16px_50px_rgba(15,23,42,0.12)] backdrop-blur-md"
              : "rounded-2xl border border-white/40 bg-white/70 px-4 py-3 shadow-[0_18px_60px_rgba(15,23,42,0.12)] backdrop-blur-md"
          } transition ${isStreaming ? "opacity-75" : "opacity-100"} ${
            tempChat ? "ring-1 ring-[var(--accent)]/50" : ""
          }`}
        >
          <div className="flex flex-col gap-4">
            <textarea
              ref={textareaRef}
              className={`w-full resize-none bg-transparent outline-none placeholder:text-slate-400 ${
                isHero
                  ? "min-h-[80px] text-lg text-slate-900"
                  : "min-h-[36px] text-sm text-slate-900"
              }`}
              placeholder={isHero ? "How can I help you today?" : "Reply..."}
              value={input}
              rows={1}
              onChange={(event) => setInput(event.target.value)}
              onKeyDown={handleComposerKeyDown}
            />

            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <button
                  type="button"
                  className="flex h-10 w-10 items-center justify-center rounded-full border border-white/40 bg-white/70 text-slate-500 transition hover:bg-white"
                  aria-label="Add attachment"
                >
                  +
                </button>
              </div>

              <div className="flex items-center gap-3">
                <button
                  type="button"
                  onClick={() => setTempChat((prev) => !prev)}
                  className={`flex items-center gap-2 rounded-full border px-3 py-2 text-xs font-semibold transition ${
                    tempChat
                      ? "border-[var(--accent)]/60 bg-[var(--accent)]/10 text-[var(--accent)]"
                      : "border-white/40 bg-white/70 text-slate-600"
                  }`}
                  aria-pressed={tempChat}
                  aria-label="Toggle temporary chat"
                >
                  <svg
                    viewBox="0 0 24 24"
                    className="h-4 w-4"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1.6"
                  >
                    <path d="M12 6v6l4 2" />
                    <path d="M12 2a10 10 0 1 0 10 10" />
                  </svg>
                  Temp
                </button>
                <button
                  type="button"
                  className="hidden items-center gap-2 rounded-full border border-white/40 bg-white/70 px-3 py-2 text-xs font-semibold text-slate-600 sm:flex"
                >
                  Metals Expert
                  <span className="text-[10px] text-slate-400">▼</span>
                </button>
                <button
                  type="button"
                  className="hidden items-center gap-1 rounded-full border border-white/40 bg-white/70 px-3 py-2 text-xs font-semibold text-slate-600 sm:flex"
                >
                  <span className="inline-flex h-3 w-[2px] bg-slate-400" />
                  <span className="inline-flex h-4 w-[2px] bg-slate-400" />
                  <span className="inline-flex h-2 w-[2px] bg-slate-400" />
                </button>
                <button
                  type="submit"
                  disabled={isStreaming || !input.trim()}
                  className="rounded-full bg-slate-900 px-4 py-2 text-xs font-semibold text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {isStreaming ? "Streaming..." : "Send"}
                </button>
              </div>
            </div>
          </div>
        </form>
      </div>
    );
  };

  useEffect(() => {
    const element = textareaRef.current;
    if (!element) {
      return;
    }
    element.style.height = "0px";
    const next = Math.min(element.scrollHeight, 160);
    element.style.height = `${next}px`;
  }, [input]);

  useEffect(() => {
    focusComposer();
  }, []);

  useEffect(() => {
    if (messages.length === 0) {
      return;
    }
    scrollToBottom(isStreaming ? "auto" : "smooth");
  }, [isStreaming, messages]);

  const activeAssistant = [...messages].reverse().find((msg) => msg.role === "assistant");
  const activePhase = derivePhase(activeAssistant?.status);
  const showStatus = isStreaming && activeAssistant?.content.length === 0;

  return (
    <div className="h-screen overflow-hidden bg-[var(--background)] text-slate-900">
      <div className="flex h-screen">
        <aside
          className={`flex h-screen flex-col gap-6 border-r border-white/40 bg-white/70 px-4 py-6 backdrop-blur-md transition-all duration-300 ${
            sidebarOpen ? "w-64" : "w-20"
          }`}
        >
          <div className="flex items-center justify-between">
            <span className="text-sm font-semibold text-slate-900">
              {sidebarOpen ? "Miniperplex" : "MP"}
            </span>
            <button
              type="button"
              onClick={() => setSidebarOpen((prev) => !prev)}
              className="flex h-8 w-8 items-center justify-center rounded-full border border-white/40 bg-white/70 text-slate-700 transition hover:bg-white"
              aria-label={sidebarOpen ? "Collapse sidebar" : "Expand sidebar"}
            >
              <svg
                viewBox="0 0 24 24"
                className={`h-4 w-4 transition ${
                  sidebarOpen ? "rotate-180" : "rotate-0"
                }`}
                fill="none"
                stroke="currentColor"
                strokeWidth="1.6"
              >
                <path d="M9 6l6 6-6 6" />
              </svg>
            </button>
          </div>
          <div className="flex flex-col gap-4 text-[11px] text-slate-800">
            <button
              type="button"
              className="flex items-center justify-center gap-2 rounded-full border border-white/40 bg-white/80 px-3 py-2 text-xs font-semibold text-slate-900 transition hover:bg-white"
            >
              <svg
                viewBox="0 0 24 24"
                className="h-4 w-4"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.6"
              >
                <path d="M12 5v14" />
                <path d="M5 12h14" />
              </svg>
              {sidebarOpen && "New chat"}
            </button>

            <nav className="flex flex-col gap-1 text-xs">
              {[
                { label: "Search", icon: "search" },
                { label: "Chats", icon: "chat" },
                { label: "Artifacts", icon: "artifact" },
              ].map((item) => (
                <button
                  key={item.label}
                  type="button"
                  className="flex items-center gap-2 rounded-lg px-2 py-2 text-left text-slate-900 transition hover:bg-white/70"
                >
                  {item.icon === "search" && (
                    <svg
                      viewBox="0 0 24 24"
                      className="h-4 w-4"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="1.6"
                    >
                      <circle cx="11" cy="11" r="7" />
                      <path d="M20 20l-3.5-3.5" />
                    </svg>
                  )}
                  {item.icon === "chat" && (
                    <svg
                      viewBox="0 0 24 24"
                      className="h-4 w-4"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="1.6"
                    >
                      <path d="M4 5h16v10H8l-4 4V5z" />
                    </svg>
                  )}
                  {item.icon === "artifact" && (
                    <svg
                      viewBox="0 0 24 24"
                      className="h-4 w-4"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="1.6"
                    >
                      <path d="M4 6h16v12H4z" />
                      <path d="M8 10h8" />
                      <path d="M8 14h6" />
                    </svg>
                  )}
                  {sidebarOpen && <span>{item.label}</span>}
                </button>
              ))}
            </nav>

            <div className="mt-2">
              <p className="text-[10px] uppercase tracking-[0.2em] text-slate-500">
                Recents
              </p>
              {sidebarOpen && (
                <div className="mt-3 space-y-2 text-xs text-slate-800">
                  <button className="flex w-full items-center gap-2 rounded-lg px-2 py-2 text-left transition hover:bg-white/70">
                    <span className="h-1.5 w-1.5 rounded-full bg-[var(--accent)]" />
                    Gold price breakout
                  </button>
                  <button className="flex w-full items-center gap-2 rounded-lg px-2 py-2 text-left transition hover:bg-white/70">
                    <span className="h-1.5 w-1.5 rounded-full bg-slate-300" />
                    Silver trend check
                  </button>
                  <button className="flex w-full items-center gap-2 rounded-lg px-2 py-2 text-left transition hover:bg-white/70">
                    <span className="h-1.5 w-1.5 rounded-full bg-slate-300" />
                    Gold market cap
                  </button>
                </div>
              )}
            </div>
          </div>

          <div className="mt-auto rounded-2xl border border-white/40 bg-white/80 p-3 text-xs text-slate-800">
            <div className="flex items-center justify-between">
              <span className="uppercase tracking-[0.2em] text-[10px] text-slate-500">
                Account
              </span>
              <span className="rounded-full border border-white/40 px-2 py-0.5 text-[10px] text-slate-500">
                Free
              </span>
            </div>
            {sidebarOpen && (
              <div className="mt-3 flex items-center justify-between">
                <span className="text-[11px] text-slate-700">
                  Upgrade for Pro insights
                </span>
                <button className="rounded-full border border-white/40 bg-white/80 px-3 py-1 text-[10px] font-semibold text-slate-900 transition hover:bg-white">
                  Upgrade
                </button>
              </div>
            )}
          </div>
        </aside>

        <main className="flex-1 h-screen overflow-y-auto">
          <div className="mx-auto flex min-h-full w-full max-w-[940px] flex-col gap-8 px-6 py-10">
            <section className="flex flex-1 flex-col gap-6 pb-36">
              {isEmpty ? (
                <div className="flex min-h-[65vh] items-center justify-center">
                  <div className="mx-auto flex w-full max-w-[940px] flex-col items-center text-center">
                    <div className="inline-flex items-center gap-2 rounded-full border border-white/40 bg-white/80 px-3 py-1 text-xs text-slate-600">
                      <span className="h-2 w-2 rounded-full bg-[var(--accent)]" />
                      Welcome — ready when you are
                    </div>
                    <h2 className="mt-4 text-3xl font-semibold text-slate-900">
                      What do you want to analyze today?
                    </h2>
                    <p className="mt-3 text-sm text-slate-500">
                      Ask about gold, silver, or metals market dynamics.
                    </p>
                    <div className="mt-8 w-full max-w-[780px]">{inputForm("hero")}</div>
                    <div className="mt-6 flex flex-wrap justify-center gap-3">
                      {suggestions.map((suggestion) => (
                        <button
                          key={suggestion.label}
                          type="button"
                          onClick={() => applySuggestion(suggestion.prompt)}
                          className="flex items-center gap-2 rounded-full border border-white/50 bg-white/40 px-4 py-2 text-xs font-medium text-slate-600/90 shadow-[0_8px_24px_rgba(15,23,42,0.08)] transition hover:-translate-y-0.5 hover:border-white/80 hover:bg-white/70"
                        >
                          {suggestion.icon}
                          {suggestion.label}
                        </button>
                      ))}
                    </div>
                  </div>
                </div>
              ) : (
                <AnimatePresence initial={false}>
                  {messages.map((message, index) => {
                    const isAssistant = message.role === "assistant";
                    const metrics = isAssistant ? extractMetrics(message.content) : [];
                    const citedSources = isAssistant
                      ? getCitedSources(message.content, message.sources)
                      : [];
                    const statusPhase = derivePhase(message.status);
                    const showStatusPill =
                      isStreaming && isAssistant && message.content.length === 0;

                    return (
                      <motion.div
                        key={`${message.role}-${index}`}
                        initial={{ opacity: 0, y: 16 }}
                        animate={{ opacity: 1, y: 0 }}
                        exit={{ opacity: 0, y: 12 }}
                        transition={{ duration: 0.35 }}
                        className={`flex ${
                          isAssistant ? "justify-start" : "justify-end"
                        }`}
                      >
                        <div
                          className={`relative w-full max-w-[90%] text-sm ${
                            isAssistant
                              ? "rounded-none border border-transparent bg-transparent px-0 py-0 text-slate-900 shadow-none"
                              : "rounded-xl bg-zinc-50/80 px-4 py-3 text-slate-900 shadow-sm sm:px-5 sm:py-4"
                          }`}
                        >
                          {isAssistant && isStreaming && (
                            <span className="progress-bar" />
                          )}

                          {isAssistant ? (
                            <div className="flex flex-col gap-4">
                              {showStatusPill && (
                                <motion.div
                                  initial={{ opacity: 0, y: -6 }}
                                  animate={{ opacity: 1, y: 0 }}
                                  className="status-pill flex items-center gap-2 rounded-full px-3 py-1.5 text-[11px] text-slate-500"
                                >
                                  <span className="relative flex h-7 w-7 items-center justify-center">
                                    <span className="status-ring" />
                                    <span className="status-orb" />
                                  </span>
                                  {iconForPhase(statusPhase)}
                                  <span className="truncate text-slate-500/80">
                                    {message.status ?? statusLabels[statusPhase]}
                                  </span>
                                </motion.div>
                              )}

                              {showStatusPill &&
                                (statusPhase === "searching" ||
                                  statusPhase === "youtube") && (
                                  <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                                    {[0, 1, 2].map((idx) => (
                                      <div
                                        key={`ghost-${idx}`}
                                        className="ghost-card rounded-2xl border border-white/60 p-4"
                                      >
                                        <div className="h-3 w-16 rounded-full bg-white/60" />
                                        <div className="mt-3 h-4 w-32 rounded-full bg-white/70" />
                                        <div className="mt-2 h-3 w-24 rounded-full bg-white/70" />
                                      </div>
                                    ))}
                                  </div>
                                )}

                              {metrics.length > 0 && (
                                <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                                  {metrics.map((metric) => (
                                    <div
                                      key={`${metric.label}-${metric.value}`}
                                      className="rounded-2xl border border-white/60 bg-white/60 p-3 shadow-sm"
                                    >
                                      <div className="text-[11px] uppercase tracking-[0.2em] text-slate-400">
                                        {metric.label || "Metric"}
                                      </div>
                                      <div className="mt-2 text-lg font-semibold text-slate-900">
                                        {metric.value}
                                      </div>
                                      <svg
                                        viewBox="0 0 64 24"
                                        className="mt-3 h-6 w-full"
                                      >
                                        <path
                                          d={buildSparkline(metric.value)}
                                          fill="none"
                                          stroke="rgba(93, 95, 239, 0.8)"
                                          strokeWidth="2"
                                        />
                                      </svg>
                                    </div>
                                  ))}
                                </div>
                              )}

                              {message.content && (
                                <ReactMarkdown
                                  remarkPlugins={[remarkGfm]}
                                  className="prose prose-sm max-w-none whitespace-pre-wrap break-words text-slate-900"
                                  components={markdownComponents}
                                >
                                  {message.content}
                                </ReactMarkdown>
                              )}

                              {citedSources.length > 0 && (
                                <details className="group rounded-2xl border border-white/60 bg-white/70 p-3">
                                  <summary className="flex cursor-pointer list-none items-center justify-between text-xs font-semibold text-slate-600">
                                    <span>Sources ({citedSources.length})</span>
                                    <span className="text-[10px] text-slate-400 group-open:hidden">
                                      Show
                                    </span>
                                    <span className="hidden text-[10px] text-slate-400 group-open:inline">
                                      Hide
                                    </span>
                                  </summary>
                                  <div className="mt-3 flex flex-col gap-2">
                                    {citedSources.map((source) => {
                                      const siteName = getSiteName(
                                        source.url,
                                        source.site
                                      );
                                      return (
                                        <a
                                          key={`${source.index}-${source.url}`}
                                          href={source.url}
                                          target="_blank"
                                          rel="noreferrer"
                                          className="flex items-center gap-3 rounded-xl border border-white/60 bg-white/70 px-3 py-2 text-left transition hover:bg-white"
                                        >
                                          <span className="flex h-6 w-6 items-center justify-center rounded-full bg-slate-900 text-[10px] font-semibold text-white">
                                            {source.index}
                                          </span>
                                          {/* eslint-disable-next-line @next/next/no-img-element */}
                                          <img
                                            src={
                                              source.favicon ||
                                              `https://www.google.com/s2/favicons?domain=${encodeURIComponent(
                                                siteName
                                              )}&sz=32`
                                            }
                                            alt={siteName}
                                            className="h-4 w-4"
                                          />
                                          <span className="min-w-0 flex-1">
                                            <span className="block truncate text-xs font-semibold text-slate-900">
                                              {source.title}
                                            </span>
                                            <span className="block truncate text-[11px] text-slate-500">
                                              {siteName}
                                            </span>
                                          </span>
                                        </a>
                                      );
                                    })}
                                  </div>
                                </details>
                              )}
                            </div>
                          ) : (
                            <p className="whitespace-pre-wrap break-words">
                              {message.content}
                            </p>
                          )}
                        </div>
                      </motion.div>
                    );
                  })}
                  <div ref={messagesEndRef} aria-hidden className="h-px w-full" />
                </AnimatePresence>
              )}
            </section>

            {!isEmpty && (
              <div
                className="fixed bottom-6 right-0 z-30 px-6"
                style={{ left: sidebarOpen ? "16rem" : "5rem" }}
              >
                <div className="mx-auto flex w-full max-w-[980px] flex-col gap-3">
                  <AnimatePresence>
                    {showStatus && (
                      <motion.div
                        initial={{ opacity: 0, y: 10 }}
                        animate={{ opacity: 1, y: 0 }}
                        exit={{ opacity: 0, y: 10 }}
                        className="status-pill inline-flex items-center gap-3 rounded-full px-4 py-2 text-xs text-slate-500"
                      >
                        <span className="relative flex h-8 w-8 items-center justify-center">
                          <span className="status-ring" />
                          <span className="status-orb" />
                        </span>
                        {iconForPhase(activePhase)}
                        <span className="text-slate-500/80">
                          {activeAssistant?.status ?? statusLabels[activePhase]}
                        </span>
                      </motion.div>
                    )}
                  </AnimatePresence>
                  {inputForm("dock")}
                </div>
              </div>
            )}
          </div>
        </main>
      </div>
    </div>
  );
}
