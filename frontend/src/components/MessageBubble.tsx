/**
 * MessageBubble.tsx — Renders a single chat message (user or assistant).
 *
 * LAYOUT:
 *   User messages:     right-aligned, indigo background.
 *   Assistant messages: left-aligned, white card with a subtle border.
 *
 * SOURCES (assistant only):
 *   Each assistant message may carry a list of source note excerpts that
 *   were retrieved by pgvector.  These are shown in a collapsible accordion
 *   below the answer text.  The user can expand them to see which notes
 *   the answer was drawn from, including the date, caseworker, and a snippet.
 *
 * PROPS:
 *   message – a ChatMessageItem (role, content, optional sources array)
 */

import { useState } from "react";
import type { ChatMessageItem } from "../types";

interface Props {
  message: ChatMessageItem;
}

export default function MessageBubble({ message }: Props) {
  // Controls whether the sources accordion is open
  const [sourcesOpen, setSourcesOpen] = useState(false);

  const isUser = message.role === "user";

  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"} mb-4`}>
      <div className={`max-w-[80%] ${isUser ? "items-end" : "items-start"} flex flex-col`}>

        {/* Message bubble */}
        <div
          className={
            isUser
              ? "bg-indigo-600 text-white rounded-2xl rounded-tr-sm px-4 py-3 text-sm leading-relaxed"
              : "bg-white border border-slate-200 text-slate-800 rounded-2xl rounded-tl-sm px-4 py-3 text-sm leading-relaxed shadow-sm"
          }
        >
          {/* Render content — preserve newlines from the LLM response */}
          {message.content.split("\n").map((line, i) => (
            <span key={i}>
              {line}
              {i < message.content.split("\n").length - 1 && <br />}
            </span>
          ))}
        </div>

        {/* Sources accordion (assistant messages only) */}
        {!isUser && message.sources && message.sources.length > 0 && (
          <div className="mt-2 w-full">
            {/* Toggle button */}
            <button
              onClick={() => setSourcesOpen((o) => !o)}
              className="flex items-center gap-1.5 text-xs text-slate-500 hover:text-indigo-600
                         transition-colors"
            >
              {/* Chevron icon — rotates when open */}
              <svg
                className={`w-3 h-3 transition-transform ${sourcesOpen ? "rotate-90" : ""}`}
                fill="none" stroke="currentColor" viewBox="0 0 24 24"
              >
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                      d="M9 5l7 7-7 7" />
              </svg>
              {message.sources.length} source note{message.sources.length !== 1 ? "s" : ""}
            </button>

            {/* Expanded sources */}
            {sourcesOpen && (
              <div className="mt-2 space-y-2">
                {message.sources.map((src) => {
                  // Format the note date for display
                  const dateStr = new Date(src.created_at).toLocaleDateString("en-US", {
                    year: "numeric", month: "short", day: "numeric",
                  });

                  return (
                    <div
                      key={src.id}
                      className="bg-slate-50 border border-slate-200 rounded-lg px-3 py-2.5
                                 text-xs text-slate-600"
                    >
                      {/* Note metadata header */}
                      <div className="flex items-center gap-2 mb-1 flex-wrap">
                        <span className="font-medium text-slate-700">{dateStr}</span>
                        {src.note_type && (
                          <span className="bg-indigo-100 text-indigo-700 px-1.5 py-0.5 rounded text-[10px] font-medium uppercase tracking-wide">
                            {src.note_type}
                          </span>
                        )}
                        {src.caseworker_name && (
                          <span className="text-slate-400">{src.caseworker_name}</span>
                        )}
                        <span className="ml-auto text-slate-400">
                          {(src.similarity * 100).toFixed(0)}% match
                        </span>
                      </div>
                      {/* Snippet text */}
                      <p className="text-slate-600 leading-relaxed">{src.snippet}</p>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        )}

      </div>
    </div>
  );
}
