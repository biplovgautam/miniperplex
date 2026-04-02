"use client";

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

export default function Home() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const controllerRef = useRef<AbortController | null>(null);
  const formRef = useRef<HTMLFormElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const messagesEndRef = useRef<HTMLDivElement | null>(null);
  const isEmpty = messages.length === 0;

  const suggestions = [
    {
      label: "Market overview",
      prompt: "What has been affecting the market lately, and what is the outlook for this year?",
    },
    {
      label: "Gold outlook",
      prompt: "What is affecting gold today and what is the base, bull, and bear case for this year and next year?",
    },
    {
      label: "Silver outlook",
      prompt: "What is affecting silver today and what are analysts saying about next year's outlook?",
    },
    {
      label: "Bitcoin outlook",
      prompt: "How is Bitcoin performing today and what key factors could drive performance this year and next year?",
    },
  ];

  const apiUrl = useMemo(
    () => process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000",
    []
  );

  const markdownComponents: Components = {
    a: ({
      children,
      href,
      ...props
    }: AnchorHTMLAttributes<HTMLAnchorElement> & { children?: ReactNode }) => {
      return (
        <a
          href={href}
          target="_blank"
          rel="noreferrer"
          className="text-blue-600 hover:underline"
          {...props}
        >
          {children}
        </a>
      );
    },
  };

  const stopStream = () => {
    controllerRef.current?.abort();
    controllerRef.current = null;
    setIsStreaming(false);
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

  const inputForm = (
    <form
      ref={formRef}
      onSubmit={handleSubmit}
      className="w-full rounded-2xl border border-gray-200 bg-white p-4 shadow-sm"
    >
      <div className="flex flex-col gap-3">
        <textarea
          ref={textareaRef}
          className="max-h-[220px] min-h-[56px] w-full resize-none rounded-xl border border-gray-200 px-4 py-3 text-sm outline-none focus:border-gray-400"
          placeholder="Ask about markets, stocks, gold, silver, or crypto..."
          value={input}
          rows={1}
          onChange={(event) => setInput(event.target.value)}
          onKeyDown={handleComposerKeyDown}
        />
        <div className="flex flex-col gap-2 text-xs text-gray-400 sm:flex-row sm:items-center sm:justify-between">
          {isEmpty ? (
            <span>Press Enter to send</span>
          ) : (
            <span>Streaming from {apiUrl}</span>
          )}
          <div className="flex gap-2">
            <button
              type="button"
              onClick={stopStream}
              disabled={!isStreaming}
              className="rounded-full border border-gray-200 px-4 py-2 text-xs font-medium text-gray-600 disabled:cursor-not-allowed disabled:opacity-50"
            >
              Stop
            </button>
            <button
              type="submit"
              disabled={isStreaming || !input.trim()}
              className="rounded-full bg-gray-900 px-5 py-2 text-xs font-semibold text-white disabled:cursor-not-allowed disabled:opacity-50"
            >
              {isStreaming ? "Streaming..." : "Send"}
            </button>
          </div>
        </div>
      </div>
    </form>
  );

  useEffect(() => {
    const element = textareaRef.current;
    if (!element) {
      return;
    }
    element.style.height = "0px";
    const next = Math.min(element.scrollHeight, 220);
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

  return (
    <div className="min-h-screen bg-gray-50 text-gray-900">
      <main className="mx-auto flex min-h-screen w-full max-w-3xl flex-col px-5 pb-32 pt-10 sm:px-6">
        <header className="mb-6 flex flex-col gap-2">
          <h1 className="text-2xl font-semibold">Miniperplex</h1>
          <p className="text-sm text-gray-500">
            Financial market analysis powered by Groq and live web sources.
          </p>
        </header>

        <section className="flex flex-1 flex-col gap-6">
          {isEmpty ? (
            <div className="flex flex-1 items-center justify-center">
              <div className="w-full max-w-2xl text-center">
                <div className="mb-6 flex flex-col gap-3">
                  <span className="text-sm font-semibold text-gray-500">
                    Financial Analysis Agent
                  </span>
                  <h2 className="text-3xl font-semibold tracking-tight text-gray-900 sm:text-4xl">
                    What do you want to analyze today?
                  </h2>
                </div>

                <div className="mt-4 text-left">
                  {inputForm}
                </div>

                <div className="mt-6 flex flex-wrap justify-center gap-3">
                  {suggestions.map((suggestion) => (
                    <button
                      key={suggestion.label}
                      type="button"
                      onClick={() => applySuggestion(suggestion.prompt)}
                      className="rounded-full border border-gray-200 bg-white px-4 py-2 text-xs font-medium text-gray-700 shadow-sm transition hover:-translate-y-0.5 hover:border-gray-300 hover:bg-gray-50"
                    >
                      {suggestion.label}
                    </button>
                  ))}
                </div>
              </div>
            </div>
          ) : (
            <div className="flex flex-col gap-5">
              {messages.map((message, index) => (
                <div
                  key={`${message.role}-${index}`}
                  className={`flex ${{
                    user: "justify-end",
                    assistant: "justify-start",
                  }[message.role]}`}
                >
                  <div
                    className={`w-full max-w-[90%] rounded-xl px-4 py-3 text-sm shadow-sm sm:px-5 sm:py-4 ${
                      message.role === "user"
                        ? "bg-gray-900 text-white"
                        : "bg-white text-gray-900"
                    }`}
                  >
                    {message.role === "assistant" ? (
                      <div className="flex flex-col gap-4">
                        {isStreaming && message.content.length === 0 && (
                          <div className="flex items-center gap-2 rounded-full border border-white/60 bg-white/70 px-3 py-1.5 text-[11px] text-gray-500 shadow-sm backdrop-blur">
                            <span className="relative flex h-5 w-5 items-center justify-center">
                              <span className="status-pulse" />
                              <span className="status-orb" />
                            </span>
                            <span className="truncate text-gray-500/80">
                              {message.status ?? "Thinking..."}
                            </span>
                          </div>
                        )}

                        

                        {message.content && (
                          <>
                            <ReactMarkdown
                              remarkPlugins={[remarkGfm]}
                              className="prose prose-sm max-w-none whitespace-pre-wrap break-words text-gray-900"
                              components={markdownComponents}
                            >
                              {message.content}
                            </ReactMarkdown>

                            {(() => {
                              const citedSources = getCitedSources(
                                message.content,
                                message.sources
                              );
                              if (citedSources.length === 0) {
                                return null;
                              }
                              return (
                                <details className="group rounded-xl border border-gray-200 bg-gray-50/70 p-2">
                                  <summary className="flex cursor-pointer list-none items-center justify-between rounded-lg px-2 py-1.5 text-xs font-semibold text-gray-700 transition hover:bg-gray-100">
                                    <span>Sources ({citedSources.length})</span>
                                    <span className="text-[10px] text-gray-500 group-open:hidden">
                                      Show
                                    </span>
                                    <span className="hidden text-[10px] text-gray-500 group-open:inline">
                                      Hide
                                    </span>
                                  </summary>

                                  <div className="mt-2 flex flex-col gap-2">
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
                                          className="flex items-start gap-2 rounded-lg border border-gray-200 bg-white px-2.5 py-2 text-left transition hover:border-gray-300 hover:bg-gray-50"
                                        >
                                          <span className="mt-[1px] inline-flex h-5 min-w-5 items-center justify-center rounded-full bg-gray-900 px-1 text-[10px] font-semibold text-white">
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
                                            className="mt-[2px] h-4 w-4"
                                          />
                                          <span className="min-w-0 flex-1">
                                            <span
                                              className="block truncate text-xs font-semibold text-gray-800"
                                              title={source.title}
                                            >
                                              {source.title}
                                            </span>
                                            <span className="block truncate text-[11px] text-gray-500">
                                              {siteName}
                                            </span>
                                          </span>
                                        </a>
                                      );
                                    })}
                                  </div>
                                </details>
                              );
                            })()}
                          </>
                        )}
                      </div>
                    ) : (
                      <p className="whitespace-pre-wrap break-words">
                        {message.content}
                      </p>
                    )}
                  </div>
                </div>
              ))}
              <div ref={messagesEndRef} aria-hidden className="h-px w-full" />
            </div>
          )}
        </section>
      </main>

      {!isEmpty && (
        <div className="sticky bottom-0 w-full border-t border-gray-200 bg-gray-50/80 px-5 py-4 backdrop-blur sm:px-6">
          <div className="mx-auto w-full max-w-3xl">{inputForm}</div>
        </div>
      )}
    </div>
  );
}
