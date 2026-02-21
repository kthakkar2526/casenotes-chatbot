/**
 * CaseSelector.tsx — Step 1 of the app.
 *
 * WHAT IT DOES:
 *   1. Fetches all cases from the backend.
 *   2. Shows a dropdown to pick a case.
 *   3. Once a case is selected, renders a visual timeline bar spanning the
 *      case's first to last note date.
 *   4. User picks a START date; the END date is automatically set to
 *      start + 6 months (read-only).
 *   5. The start-date input is constrained so the 6-month window always
 *      fits within the case's actual note range.
 *   6. The selected window is highlighted on the timeline bar in real time.
 *
 * VALIDATION:
 *   - Window must be exactly 6 months (enforced by auto-filling end date).
 *   - Start date must be ≥ case's min_note_date.
 *   - End date (start + 6 months) must be ≤ case's max_note_date.
 */

import { useEffect, useMemo, useState } from "react";
import { fetchCases, createSession } from "../api/client";
import type { Case, SessionInfo } from "../types";

interface Props {
  onSessionCreated: (session: SessionInfo) => void;
}

// ------------------------------------------------------------------ //
// Date helpers (all operate on local time — no UTC surprises)
// ------------------------------------------------------------------ //

/** Parse a "YYYY-MM-DD" string as a local Date (avoids UTC off-by-one). */
function parseLocal(str: string): Date {
  const [y, m, d] = str.split("-").map(Number);
  return new Date(y, m - 1, d);
}

/** Return a new Date that is `months` months after `date`. */
function addMonths(date: Date, months: number): Date {
  const d = new Date(date);
  d.setMonth(d.getMonth() + months);
  return d;
}

/** Format a Date as "YYYY-MM-DD" for <input type="date"> values. */
function toInputStr(date: Date): string {
  return date.toISOString().slice(0, 10);
}

/** Format a "YYYY-MM-DD" string as "Mon YYYY" for display labels. */
function formatMonthYear(dateStr: string): string {
  const [y, m] = dateStr.split("-").map(Number);
  return new Date(y, m - 1, 1).toLocaleDateString("en-US", {
    month: "short",
    year: "numeric",
  });
}

// ------------------------------------------------------------------ //
// Component
// ------------------------------------------------------------------ //

export default function CaseSelector({ onSessionCreated }: Props) {
  const [cases, setCases] = useState<Case[]>([]);
  const [loadingCases, setLoadingCases] = useState(true);
  const [selectedCaseId, setSelectedCaseId] = useState("");
  const [startDate, setStartDate] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // ---- Fetch cases on mount -------------------------------------- //
  useEffect(() => {
    fetchCases()
      .then((data) => {
        setCases(data);
        if (data.length > 0) setSelectedCaseId(data[0].id);
      })
      .catch((err) => setError(`Failed to load cases: ${err.message}`))
      .finally(() => setLoadingCases(false));
  }, []);

  // ---- Derived: the currently selected Case object -------------- //
  const selectedCase = useMemo(
    () => cases.find((c) => c.id === selectedCaseId) ?? null,
    [cases, selectedCaseId]
  );

  // ---- Clear dates when case changes so user picks their own window --- //
  useEffect(() => {
    setStartDate("");
    setError(null);
  }, [selectedCaseId]);

  // ---- End date is always start + 6 months (read-only) ---------- //
  const endDate = useMemo(() => {
    if (!startDate) return "";
    return toInputStr(addMonths(parseLocal(startDate), 6));
  }, [startDate]);

  // ---- Constraints for the start-date <input> ------------------- //
  // Min: case's first note date (can't start before any notes exist).
  // Max: case's last note date minus 6 months (so end always fits).
  const startDateMin = selectedCase?.min_note_date ?? "";
  const startDateMax = useMemo(() => {
    if (!selectedCase?.max_note_date) return "";
    const latest = addMonths(parseLocal(selectedCase.max_note_date), -6);
    // If the case is shorter than 6 months, this could go negative —
    // fall back to the first note date so the picker stays usable.
    const earliest = selectedCase.min_note_date
      ? parseLocal(selectedCase.min_note_date)
      : latest;
    return toInputStr(latest < earliest ? earliest : latest);
  }, [selectedCase]);

  // ---- Case span in months (for "too short" warning) ------------ //
  const caseSpanMonths = useMemo(() => {
    if (!selectedCase?.min_note_date || !selectedCase?.max_note_date) return null;
    const min = parseLocal(selectedCase.min_note_date);
    const max = parseLocal(selectedCase.max_note_date);
    return (
      (max.getFullYear() - min.getFullYear()) * 12 +
      (max.getMonth() - min.getMonth())
    );
  }, [selectedCase]);

  // ---- Timeline bar: left% and width% of the selected window ---- //
  const timelineHighlight = useMemo(() => {
    if (!selectedCase?.min_note_date || !selectedCase?.max_note_date || !startDate)
      return null;

    const minMs = parseLocal(selectedCase.min_note_date).getTime();
    const maxMs = parseLocal(selectedCase.max_note_date).getTime();
    const startMs = parseLocal(startDate).getTime();
    const endMs = addMonths(parseLocal(startDate), 6).getTime();
    const total = maxMs - minMs;
    if (total <= 0) return null;

    const leftPct = Math.max(0, ((startMs - minMs) / total) * 100);
    const widthPct = Math.min(100 - leftPct, ((endMs - startMs) / total) * 100);
    return { leftPct, widthPct };
  }, [selectedCase, startDate]);

  // ---- Form submission ------------------------------------------- //
  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    if (!selectedCaseId || !startDate || !endDate) {
      setError("Please select a case and a start date.");
      return;
    }

    // Guard: window must fit within the case's actual note range.
    if (selectedCase?.min_note_date && startDate < selectedCase.min_note_date) {
      setError("Start date is before the case's first note.");
      return;
    }
    if (selectedCase?.max_note_date && endDate > selectedCase.max_note_date) {
      setError("The 6-month window extends beyond the case's last note.");
      return;
    }

    setSubmitting(true);
    try {
      const session = await createSession(selectedCaseId, startDate, endDate);
      onSessionCreated(session);
    } catch (err: unknown) {
      setError(`Could not start session: ${(err as Error).message}`);
    } finally {
      setSubmitting(false);
    }
  }

  // ---- Render ---------------------------------------------------- //
  return (
    <div className="min-h-screen bg-slate-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-2xl shadow-lg w-full max-w-lg p-8">

        {/* Header */}
        <h1 className="text-2xl font-bold text-slate-800 mb-1">
          Case Notes Assistant
        </h1>
        <p className="text-sm text-slate-500 mb-8">
          Select a case, then choose a 6-month window to explore.
        </p>

        <form onSubmit={handleSubmit} className="space-y-6">

          {/* ── Case dropdown ──────────────────────────────────── */}
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">
              Case
            </label>
            {loadingCases ? (
              <div className="h-10 bg-slate-100 rounded-lg animate-pulse" />
            ) : (
              <select
                value={selectedCaseId}
                onChange={(e) => {
                  setSelectedCaseId(e.target.value);
                  setError(null);
                }}
                className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm
                           focus:outline-none focus:ring-2 focus:ring-indigo-500"
              >
                {cases.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.case_number} — {c.client_name}
                  </option>
                ))}
              </select>
            )}
          </div>

          {/* ── Timeline + window picker ────────────────────────── */}
          {selectedCase?.min_note_date && selectedCase?.max_note_date && (
            <div className="space-y-4">

              {/* Warning: case shorter than 6 months */}
              {caseSpanMonths !== null && caseSpanMonths < 6 && (
                <p className="text-xs text-amber-700 bg-amber-50 border border-amber-200
                              rounded-lg px-3 py-2">
                  This case only spans ~{caseSpanMonths} month
                  {caseSpanMonths !== 1 ? "s" : ""}. The 6-month window may
                  extend slightly beyond the last note.
                </p>
              )}

              {/* Case date range pills */}
              <div className="flex items-center gap-2 text-xs">
                <span className="bg-slate-100 text-slate-600 rounded-md px-2.5 py-1 font-medium">
                  Case start: {formatMonthYear(selectedCase.min_note_date)}
                </span>
                <span className="text-slate-300 flex-1 border-t border-dashed border-slate-200" />
                <span className="bg-slate-100 text-slate-600 rounded-md px-2.5 py-1 font-medium">
                  Case end: {formatMonthYear(selectedCase.max_note_date)}
                </span>
              </div>

              {/* Timeline bar */}
              <div>
                <div className="flex justify-between text-xs text-slate-400 mb-1 px-0.5">
                  <span>{formatMonthYear(selectedCase.min_note_date)}</span>
                  <span className="text-slate-500 font-medium">Select a 6-month window</span>
                  <span>{formatMonthYear(selectedCase.max_note_date)}</span>
                </div>

                {/* Track */}
                <div className="h-5 bg-slate-100 rounded-full relative overflow-hidden">
                  {/* Highlighted window */}
                  {timelineHighlight && (
                    <div
                      className="absolute h-full bg-indigo-500 rounded-full
                                 transition-all duration-150"
                      style={{
                        left: `${timelineHighlight.leftPct}%`,
                        width: `${timelineHighlight.widthPct}%`,
                      }}
                    />
                  )}
                </div>

                {/* Selected range label under the bar */}
                {startDate && endDate && (
                  <p className="text-xs text-indigo-600 mt-1.5 text-center font-medium">
                    {formatMonthYear(startDate)}
                    <span className="mx-1.5 text-indigo-300">→</span>
                    {formatMonthYear(endDate)}
                  </p>
                )}
              </div>

              {/* Date pickers */}
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-medium text-slate-500 mb-1">
                    Start date
                  </label>
                  <input
                    type="date"
                    value={startDate}
                    min={startDateMin}
                    max={startDateMax}
                    onChange={(e) => {
                      setStartDate(e.target.value);
                      setError(null);
                    }}
                    className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm
                               focus:outline-none focus:ring-2 focus:ring-indigo-500"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-slate-500 mb-1">
                    End date
                    <span className="ml-1 text-slate-400 font-normal">(auto · +6 months)</span>
                  </label>
                  <input
                    type="date"
                    value={endDate}
                    readOnly
                    tabIndex={-1}
                    className="w-full border border-slate-100 rounded-lg px-3 py-2 text-sm
                               bg-slate-50 text-slate-400 cursor-not-allowed"
                  />
                </div>
              </div>

            </div>
          )}

          {/* ── Error message ───────────────────────────────────── */}
          {error && (
            <p className="text-sm text-red-600 bg-red-50 border border-red-200
                          rounded-lg px-3 py-2">
              {error}
            </p>
          )}

          {/* ── Submit ──────────────────────────────────────────── */}
          <button
            type="submit"
            disabled={submitting || loadingCases || !startDate}
            className="w-full bg-indigo-600 hover:bg-indigo-700 disabled:bg-indigo-300
                       text-white font-medium py-2.5 rounded-lg transition-colors text-sm"
          >
            {submitting ? "Starting…" : "Start Chat"}
          </button>

        </form>
      </div>
    </div>
  );
}
