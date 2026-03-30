"use client";

import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import type { AnchorHTMLAttributes, ReactNode } from "react";
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
};

const SSE_SEPARATOR = "\n\n";

const buildSourceMap = (sources: SourceItem[] = []) =>
  sources.reduce<Record<string, string>>((acc, source) => {
    acc[String(source.index)] = source.url;
    return acc;
  }, {});

const injectCitationLinks = (body: string, sources: SourceItem[] = []) => {
  const sourceMap = buildSourceMap(sources);
  return body.replace(/\[(\d+)]/g, (match, index) => {
    const url = sourceMap[index];
    return url ? `[${index}](${url})` : match;
  });
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
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
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
      const childText =
        typeof children === "string"
          ? children
          : Array.isArray(children) && typeof children[0] === "string"
            ? children[0]
            : "";
      const isCitation = /^\d+$/.test(childText);
      if (isCitation) {
        return (
          <sup className="mx-0.5 align-super">
            <a
              href={href}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center rounded-full bg-gray-200 px-1.5 py-0.5 text-[10px] font-semibold text-gray-700 transition hover:bg-gray-300"
              {...props}
            >
              {childText}
            </a>
          </sup>
        );
      }
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

  const applySuggestion = (prompt: string) => {
    setInput(prompt);
    requestAnimationFrame(() => {
      textareaRef.current?.focus();
    });
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
    }
  };

  const inputForm = (
    <form
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
                        {message.sources && message.sources.length > 0 && (
                          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
                            {message.sources.map((source) => {
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
                                  className="flex flex-col gap-2 rounded-xl border border-gray-200 bg-white p-3 text-left text-xs text-gray-600 shadow-sm transition hover:-translate-y-0.5 hover:border-gray-300 hover:bg-gray-50"
                                >
                                  <div className="flex items-center gap-2 text-[11px] font-semibold text-gray-500">
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
                                    <span className="truncate">{siteName}</span>
                                  </div>
                                  <span
                                    className="truncate text-xs font-semibold text-gray-900"
                                    title={source.title}
                                  >
                                    {source.title}
                                  </span>
                                  {source.snippet && (
                                    <span className="max-h-10 overflow-hidden text-[11px] text-gray-500">
                                      {source.snippet}
                                    </span>
                                  )}
                                </a>
                              );
                            })}
                          </div>
                        )}

                        {isStreaming &&
                          message.content.length === 0 &&
                          (!message.sources || message.sources.length === 0) && (
                            <div className="rounded-xl border border-dashed border-gray-300 bg-gray-50 px-3 py-2 text-xs text-gray-500">
                              Searching the web for &ldquo;{message.query ?? "your query"}&rdquo;...
                            </div>
                          )}

                        {message.content && (
                          <ReactMarkdown
                            remarkPlugins={[remarkGfm]}
                            className="prose prose-sm max-w-none whitespace-pre-wrap break-words text-gray-900"
                            components={markdownComponents}
                          >
                            {injectCitationLinks(
                              message.content,
                              message.sources
                            )}
                          </ReactMarkdown>
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
