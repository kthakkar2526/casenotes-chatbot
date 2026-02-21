/**
 * ChatInterface.tsx — Step 2 of the app: the actual chat view.
 *
 * WHAT IT DOES:
 *   Displays the conversation for a specific session (case + date window).
 *   The user types questions; each is sent to POST /api/chat/, which runs
 *   the full RAG pipeline and returns an answer + source notes.
 *
 * KEY BEHAVIOURS:
 *   - Optimistic UI: the user's message is appended immediately before the
 *     API call completes so the UI feels instant.
 *   - A "thinking" placeholder bubble is shown while waiting for the LLM.
 *   - Auto-scroll: the message list scrolls to the bottom after each new
 *     message (via a ref on the dummy anchor element at the list's end).
 *   - Keyboard shortcut: Enter submits, Shift+Enter inserts a newline.
 *
 * PROPS:
 *   session        – SessionInfo returned by createSession()
 *   onBack         – callback to return to CaseSelector (start a new session)
 */

import { useEffect, useRef, useState } from "react";
import { sendMessage } from "../api/client";
import type { ChatMessageItem, SessionInfo } from "../types";
import MessageBubble from "./MessageBubble";

interface Props {
  session: SessionInfo;
  onBack: () => void;
}

export default function ChatInterface({ session, onBack }: Props) {
  const [messages, setMessages] = useState<ChatMessageItem[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Ref to the invisible anchor at the bottom of the message list —
  // used to scroll to the latest message automatically.
  const bottomRef = useRef<HTMLDivElement>(null);

  // Scroll to bottom whenever the message list changes
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // ---- Send a message -------------------------------------------- //
  async function handleSend() {
    const text = input.trim();
    if (!text || loading) return;

    setInput("");
    setError(null);

    // 1. Optimistically add the user's message to the list
    const userMsg: ChatMessageItem = {
      id: `local-${Date.now()}`,
      role: "user",
      content: text,
    };
    setMessages((prev) => [...prev, userMsg]);

    // 2. Show a "thinking" placeholder for the assistant
    const placeholderId = `placeholder-${Date.now()}`;
    const placeholder: ChatMessageItem = {
      id: placeholderId,
      role: "assistant",
      content: "…",
    };
    setMessages((prev) => [...prev, placeholder]);
    setLoading(true);

    // 3. Call the API
    try {
      const data = await sendMessage(session.session_id, text);

      // 4. Replace the placeholder with the real answer
      setMessages((prev) =>
        prev.map((m) =>
          m.id === placeholderId
            ? { id: placeholderId, role: "assistant", content: data.answer, sources: data.sources }
            : m
        )
      );
    } catch (err: unknown) {
      // Remove the placeholder and show the error inline
      setMessages((prev) => prev.filter((m) => m.id !== placeholderId));
      setError(`Error: ${(err as Error).message}`);
    } finally {
      setLoading(false);
    }
  }

  // Submit on Enter (not Shift+Enter)
  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }

  // ---- Render ---------------------------------------------------- //
  return (
    <div className="min-h-screen bg-slate-50 flex flex-col">

      {/* ---- Header ---- */}
      <header className="bg-white border-b border-slate-200 px-4 py-3 flex items-center gap-3
                          sticky top-0 z-10">
        <button
          onClick={onBack}
          className="text-slate-500 hover:text-indigo-600 transition-colors p-1 rounded-lg
                     hover:bg-slate-100"
          title="Back to case selector"
        >
          {/* Left-arrow icon */}
          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M15 19l-7-7 7-7" />
          </svg>
        </button>

        <div>
          <p className="text-sm font-semibold text-slate-800">
            {session.case_number} — {session.client_name}
          </p>
          <p className="text-xs text-slate-400">
            {session.start_date} to {session.end_date}
          </p>
        </div>
      </header>

      {/* ---- Message list ---- */}
      <main className="flex-1 overflow-y-auto px-4 py-6 max-w-3xl w-full mx-auto">
        {messages.length === 0 && (
          <div className="text-center text-slate-400 text-sm mt-16">
            <p className="text-4xl mb-3">💬</p>
            <p>Ask anything about the case notes in the selected date range.</p>
          </div>
        )}

        {messages.map((msg) => (
          <MessageBubble key={msg.id} message={msg} />
        ))}

        {/* Error banner */}
        {error && (
          <div className="bg-red-50 border border-red-200 text-red-700 rounded-lg px-4 py-3
                          text-sm mb-4">
            {error}
          </div>
        )}

        {/* Auto-scroll anchor */}
        <div ref={bottomRef} />
      </main>

      {/* ---- Input bar ---- */}
      <footer className="bg-white border-t border-slate-200 px-4 py-3 sticky bottom-0">
        <div className="max-w-3xl mx-auto flex gap-2">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask a question about the case… (Enter to send, Shift+Enter for new line)"
            rows={2}
            disabled={loading}
            className="flex-1 border border-slate-200 rounded-xl px-3 py-2 text-sm resize-none
                       focus:outline-none focus:ring-2 focus:ring-indigo-500 disabled:bg-slate-50"
          />
          <button
            onClick={handleSend}
            disabled={loading || !input.trim()}
            className="bg-indigo-600 hover:bg-indigo-700 disabled:bg-indigo-300 text-white
                       rounded-xl px-4 py-2 text-sm font-medium transition-colors self-end"
          >
            {loading ? (
              /* Spinning loader icon */
              <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10"
                        stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor"
                      d="M4 12a8 8 0 018-8v8H4z" />
              </svg>
            ) : (
              "Send"
            )}
          </button>
        </div>
      </footer>
    </div>
  );
}
