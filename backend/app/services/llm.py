"""
llm.py — Gemini 2.5 Flash call + prompt assembly for the RAG chatbot.

PROMPT STRUCTURE:
  System instruction (set once per chat model):
    Tells Gemini it is a case-note assistant and explains how to behave.

  Each call to generate_answer() constructs:
    [Context block]
      A numbered list of the retrieved case notes (from pgvector), each
      labelled with its date and note type.

    [Conversation history]
      All previous turns in this session (user + model), formatted as
      google.generativeai Content objects, so Gemini can maintain context.

    [Current user turn]
      The user's new question, with the context block prepended.

WHY PREPEND CONTEXT TO EACH USER TURN (NOT AS A SEPARATE SYSTEM MESSAGE)?
  Gemini's system_instruction is set at model-init time and doesn't change
  per call.  We inject the retrieved notes into the *user* turn so that:
  a) They are always fresh (different notes per question).
  b) The model clearly sees the notes as supporting evidence for this turn.

HISTORY FORMAT:
  We pass prior messages as a list of {"role": ..., "parts": [...]} dicts,
  which is the format expected by google-generativeai's ChatSession /
  generate_content() with the `history` parameter.

  We keep the last 10 message pairs (20 messages) to avoid hitting the
  context window.  For a POC this is more than enough.
"""

from datetime import datetime

import google.generativeai as genai

from app.core.config import settings

# ------------------------------------------------------------------ #
# Configure the Google AI client once at module load
# ------------------------------------------------------------------ #
genai.configure(api_key=settings.GOOGLE_API_KEY)

# ------------------------------------------------------------------ #
# System instruction
# ------------------------------------------------------------------ #
SYSTEM_INSTRUCTION = (
    "You are a precise assistant for child welfare caseworkers. "
    "You are given excerpts from case notes for a specific case and date window. "
    "Use ONLY the provided case note excerpts to answer questions.\n\n"

    "CITATION RULE: Each excerpt is labelled [YYYY-MM-DD, note-type, Caseworker Name]. "
    "Always cite using that exact label — for example: "
    "'[2025-03-05, in-person, Robert Hayes]'. "
    "NEVER use numbered references like 'Note 1' or 'Note 2' — "
    "those numbers change with every query and will confuse the user.\n\n"

    "STRICT SCOPE RULE: Answer only what was explicitly asked. "
    "Do NOT treat related but distinct concepts as equivalent. "
    "For example: if asked about 'drug abuse', alcohol use is NOT a match unless "
    "the notes explicitly label it as drug abuse or substance abuse. "
    "If the notes contain something adjacent but not the same thing, "
    "first state clearly that the specific thing asked about was NOT documented, "
    "then — in a separate sentence — you may note what related information was found, "
    "clearly labelled as different.\n\n"

    "If the answer cannot be found at all in the provided notes, say so clearly — "
    "do not make up information. "
    "Keep your answers concise, factual, and professional."
)

# ------------------------------------------------------------------ #
# Model instance (singleton — instantiated once at module load)
# ------------------------------------------------------------------ #
_model = genai.GenerativeModel(
    model_name="gemini-2.5-flash",
    system_instruction=SYSTEM_INSTRUCTION,
)

# Maximum number of past conversation turns to include in the prompt.
# A "turn" = one user message + one assistant message = 2 Content items.
MAX_HISTORY_TURNS = 10


# ------------------------------------------------------------------ #
# Public function
# ------------------------------------------------------------------ #
async def generate_answer(
    user_question: str,
    retrieved_notes: list[dict],
    prior_messages: list[dict],
) -> str:
    """
    Call Gemini 2.5 Flash with context notes + conversation history.

    Args:
        user_question:   The raw question string from the user.
        retrieved_notes: List of chunk dicts from vector_search.find_similar_chunks().
                         Each has keys: chunk_text, created_at, note_type,
                         caseworker_name, chunk_index, similarity.
        prior_messages:  All previous ChatMessage rows for this session,
                         each as {"role": "user"|"assistant", "content": "..."}.
                         The current user message should NOT be included here —
                         it is passed via user_question.

    Returns:
        The assistant's answer as a plain string.
    """

    # ---- 1. Build the context block -------------------------------- #
    if retrieved_notes:
        context_lines = ["**Relevant case note excerpts:**\n"]
        for note in retrieved_notes:
            # Label uses the stable date+type+caseworker identifier so the LLM
            # (and the user) can reference it unambiguously across multiple turns.
            # We deliberately omit a sequential "Note N" number — that number
            # resets every query and creates confusion when users refer back to it.
            ts: datetime = note["created_at"]
            date_str = ts.strftime("%Y-%m-%d")
            note_type = note.get("note_type") or "unknown"
            cw = note.get("caseworker_name") or "unknown caseworker"
            context_lines.append(
                f"[{date_str}, {note_type}, {cw}]:\n{note['chunk_text']}\n"
            )
        context_block = "\n".join(context_lines)
    else:
        context_block = (
            "No case note excerpts were found for this question within the "
            "selected date window."
        )

    # ---- 2. Build the full user message for this turn -------------- #
    full_user_message = f"{context_block}\n\n**Question:** {user_question}"

    # ---- 3. Format conversation history for Gemini ----------------- #
    # google-generativeai uses "model" (not "assistant") as the role name.
    # We keep only the last MAX_HISTORY_TURNS turns to control token usage.
    history_messages = prior_messages[-(MAX_HISTORY_TURNS * 2):]

    history = []
    for msg in history_messages:
        gemini_role = "model" if msg["role"] == "assistant" else "user"
        history.append({"role": gemini_role, "parts": [msg["content"]]})

    # ---- 4. Call Gemini -------------------------------------------- #
    # generate_content() with history= simulates a multi-turn conversation
    # without needing a stateful ChatSession object (simpler for async use).
    response = _model.generate_content(
        contents=history + [{"role": "user", "parts": [full_user_message]}],
    )

    # Extract the text from the first candidate's first part
    return response.text
