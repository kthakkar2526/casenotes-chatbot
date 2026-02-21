/**
 * App.tsx — Root component and top-level state machine.
 *
 * The app has two views (steps):
 *
 *   Step 1 — CaseSelector
 *     The user picks a case and a 6-month date window, then clicks
 *     "Start Chat".  On success, the app transitions to Step 2.
 *
 *   Step 2 — ChatInterface
 *     The full chat view for the selected session.  The user can ask
 *     questions and see answers alongside source note excerpts.
 *     Clicking "Back" resets to Step 1.
 *
 * STATE:
 *   `session` — null while on Step 1; populated with SessionInfo on Step 2.
 *   This is the only piece of state managed here; everything else lives
 *   inside the child components.
 */

import { useState } from "react";
import CaseSelector from "./components/CaseSelector";
import ChatInterface from "./components/ChatInterface";
import type { SessionInfo } from "./types";

export default function App() {
  // null  → show CaseSelector
  // SessionInfo → show ChatInterface for that session
  const [session, setSession] = useState<SessionInfo | null>(null);

  return session === null ? (
    // Step 1: pick case + date window
    <CaseSelector onSessionCreated={(s) => setSession(s)} />
  ) : (
    // Step 2: chat about the selected case
    <ChatInterface
      session={session}
      onBack={() => setSession(null)}   // return to step 1
    />
  );
}
