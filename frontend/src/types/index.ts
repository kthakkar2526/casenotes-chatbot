/**
 * types/index.ts — Shared TypeScript interfaces used across components.
 *
 * These mirror the JSON shapes returned by the FastAPI backend so that
 * TypeScript can catch mismatches at compile time.
 */

/** One case returned by GET /api/cases */
export interface Case {
  id: string;
  case_number: string;
  client_name: string;
  min_note_date: string | null;  // "YYYY-MM-DD" — earliest note in the case
  max_note_date: string | null;  // "YYYY-MM-DD" — latest note in the case
}

/**
 * Metadata about a chat session, returned by POST /api/sessions.
 * Stored in component state and passed as props to ChatInterface.
 */
export interface SessionInfo {
  session_id: string;
  case_number: string;
  client_name: string;
  start_date: string;  // "YYYY-MM-DD"
  end_date: string;    // "YYYY-MM-DD"
}

/** A source note excerpt returned alongside each assistant answer */
export interface NoteSource {
  id: string;
  created_at: string;      // ISO 8601 datetime string
  note_type: string | null;
  caseworker_name: string | null;
  snippet: string;         // First 250 chars of the note
  similarity: number;      // Cosine similarity score [0, 1]
}

/**
 * One message bubble in the chat UI.
 * role = "user" | "assistant"
 * sources is only populated for assistant messages.
 */
export interface ChatMessageItem {
  id: string;             // temporary local id or server id
  role: "user" | "assistant";
  content: string;
  sources?: NoteSource[];
}
