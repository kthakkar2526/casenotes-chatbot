/**
 * client.ts — Typed fetch wrappers for all backend API calls.
 *
 * WHY NOT USE AXIOS?
 *   The native fetch API is sufficient for this POC and avoids an extra
 *   dependency.  Each function returns a typed Promise and throws on
 *   non-2xx responses so the calling component can catch and display errors.
 *
 * BASE URL:
 *   Read from the VITE_API_BASE_URL environment variable (set in .env).
 *   Vite replaces import.meta.env.VITE_* at build time.
 */

import type { Case, SessionInfo, ChatMessageItem } from "../types";

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

/** Throw a descriptive error for non-OK HTTP responses */
async function checkResponse(res: Response): Promise<Response> {
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`HTTP ${res.status}: ${body}`);
  }
  return res;
}

// ------------------------------------------------------------------ //
// Cases
// ------------------------------------------------------------------ //

/**
 * Fetch all cases for the dropdown selector.
 * Calls: GET /api/cases/
 */
export async function fetchCases(): Promise<Case[]> {
  const res = await fetch(`${BASE_URL}/api/cases/`);
  await checkResponse(res);
  return res.json();
}

// ------------------------------------------------------------------ //
// Sessions
// ------------------------------------------------------------------ //

/**
 * Create a new chat session for the selected case + date window.
 * Calls: POST /api/sessions/
 *
 * @param caseId     UUID of the selected case
 * @param startDate  "YYYY-MM-DD"
 * @param endDate    "YYYY-MM-DD"
 */
export async function createSession(
  caseId: string,
  startDate: string,
  endDate: string
): Promise<SessionInfo> {
  const res = await fetch(`${BASE_URL}/api/sessions/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      case_id: caseId,
      start_date: startDate,
      end_date: endDate,
    }),
  });
  await checkResponse(res);
  return res.json();
}

// ------------------------------------------------------------------ //
// Chat
// ------------------------------------------------------------------ //

/**
 * Send a user message and receive the assistant's answer + source notes.
 * Calls: POST /api/chat/
 *
 * @param sessionId UUID from createSession()
 * @param message   The user's question text
 *
 * Returns a ChatMessageItem (role="assistant") with sources populated.
 */
export async function sendMessage(
  sessionId: string,
  message: string
): Promise<{ answer: string; sources: ChatMessageItem["sources"] }> {
  const res = await fetch(`${BASE_URL}/api/chat/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, message }),
  });
  await checkResponse(res);
  return res.json();
}
