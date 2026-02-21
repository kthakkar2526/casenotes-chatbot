"""
chunking.py — Smart sentence-aware text chunking with character-measured overlap.

WHY NOT FIXED-SENTENCE OVERLAP?
  "Take the last 3 sentences as overlap" breaks when sentences are tiny
  ("Yes.", "Okay.", "He agreed.") — those 3 sentences together might be
  only 20 characters and carry almost no context into the next chunk.

OUR APPROACH — CHARACTER-FLOOR OVERLAP:
  After building each chunk, we walk BACKWARDS through its sentences and
  collect sentences until we have accumulated >= min_overlap_chars of text.
  We stop early only if the next sentence would push us over max_overlap_chars.
  We ALWAYS take complete sentences — never cut mid-sentence.

  Result: the overlap is always a semantically coherent block of text that's
  large enough to carry real context, regardless of individual sentence length.

CHUNK BUILDING:
  Sentences are accumulated greedily from left to right until the next sentence
  would push the chunk over max_chars.  The chunk_start_idx of the NEXT chunk
  is set to overlap_start — the first sentence of the overlap block — so the
  overlap sentences appear naturally at the beginning of the next chunk.

PARAMETERS (all tunable via call site):
  max_chars         1200  ≈ 300 tokens for bge-large-en-v1.5 (512-token limit)
  min_overlap_chars  200  ≈ 40 words — enough for genuine context carry-over
  max_overlap_chars  400  ≈ 1/3 of max_chars — overlap can't dominate the chunk

EXAMPLE:
  Chunk N ends with sentences [... s5, s6, s7, s8] (s6+s7+s8 = 310 chars ≥ 200)
  → overlap_start = index of s6
  → Chunk N+1 begins: [s6, s7, s8, s9, s10, ...]
  All three sentences are complete; no mid-sentence cuts anywhere.
"""

import nltk

# punkt_tab is the sentence tokenizer model required by NLTK ≥ 3.8.
# quiet=True suppresses the "already downloaded" message on subsequent calls.
# This runs at import time so the model is ready before any request comes in.
nltk.download("punkt_tab", quiet=True)

from nltk.tokenize import sent_tokenize  # noqa: E402 (import after download)


def chunk_text(
    text: str,
    max_chars: int = 1200,
    min_overlap_chars: int = 200,
    max_overlap_chars: int = 400,
) -> list[str]:
    """
    Split `text` into overlapping chunks of at most `max_chars` characters.

    Each chunk boundary falls on a sentence boundary — never mid-sentence.
    The overlap between consecutive chunks is at least `min_overlap_chars`
    and at most `max_overlap_chars` worth of complete sentences.

    Args:
        text:              Raw note text to split.
        max_chars:         Hard upper limit on chunk length (characters).
        min_overlap_chars: Keep collecting sentences backwards until this
                           many characters of overlap are accumulated.
        max_overlap_chars: Stop collecting overlap sentences if this cap
                           would be exceeded by adding the next sentence.

    Returns:
        List of chunk strings.  A note shorter than max_chars returns a
        single-element list containing the original text.
    """

    # Tokenise into sentences first — all splitting respects sentence boundaries
    sentences = sent_tokenize(text)

    if not sentences:
        return [text.strip()] if text.strip() else []

    # Short text: fits in one chunk, no splitting needed
    if len(text) <= max_chars:
        return [text]

    chunks: list[str] = []
    # Index of the first sentence in the chunk we are currently building.
    # The overlap from the previous chunk causes this to start BEFORE the
    # first *new* sentence — that's intentional and is exactly the overlap.
    chunk_start_idx: int = 0

    while chunk_start_idx < len(sentences):

        # ---------------------------------------------------------------- #
        # Step 1: Build the current chunk
        # Greedily add sentences until the next one would exceed max_chars.
        # ---------------------------------------------------------------- #
        chunk_sents: list[str] = []
        char_count: int = 0
        j: int = chunk_start_idx

        while j < len(sentences):
            s = sentences[j]
            # Inter-sentence space adds 1 character (except for the very first)
            separator = 1 if chunk_sents else 0

            if char_count + separator + len(s) > max_chars and chunk_sents:
                # This sentence would overflow — stop BEFORE adding it.
                # We check `and chunk_sents` to guarantee at least one sentence
                # always enters the chunk (handles sentences > max_chars).
                break

            chunk_sents.append(s)
            char_count += separator + len(s)
            j += 1

        # Edge case: the very first sentence of this chunk is longer than
        # max_chars (e.g. a section header that runs on for 1 500 chars).
        # We must still include it to make forward progress — otherwise we'd
        # loop forever.
        if not chunk_sents:
            chunk_sents = [sentences[chunk_start_idx]]
            j = chunk_start_idx + 1

        chunks.append(" ".join(chunk_sents))

        # All sentences consumed — we are done
        if j >= len(sentences):
            break

        # ---------------------------------------------------------------- #
        # Step 2: Determine the overlap for the next chunk
        # Walk BACKWARDS from j (the first sentence NOT in this chunk),
        # collecting complete sentences until we have >= min_overlap_chars.
        # Stop early if the next candidate would push us over max_overlap_chars.
        # ---------------------------------------------------------------- #
        overlap_char_count: int = 0
        overlap_start: int = j  # will move left (backwards) as we collect

        while overlap_start > chunk_start_idx:
            candidate_idx = overlap_start - 1
            candidate_text = sentences[candidate_idx]

            # When this sentence is prepended to the overlap block, a space
            # separates it from the sentence currently at overlap_start
            # (unless candidate_idx == j-1, i.e. this is the first/last
            # sentence we're adding and it's at the very end of the chunk).
            space = 1 if overlap_start < j else 0
            addition = len(candidate_text) + space

            # Cap check: don't let overlap grow too large
            if overlap_char_count + addition > max_overlap_chars:
                # Including this sentence would exceed the cap — stop here.
                # We do NOT include it, so overlap_start stays as-is.
                break

            # Accept this sentence into the overlap
            overlap_start = candidate_idx
            overlap_char_count += addition

            # Floor check: do we have enough context now?
            if overlap_char_count >= min_overlap_chars:
                # Yes — stop collecting; we have sufficient context.
                break

        # Safety: overlap_start must be STRICTLY greater than chunk_start_idx
        # to guarantee forward progress.  If the entire chunk is shorter than
        # min_overlap_chars (e.g. one very short sentence), we just advance by
        # one sentence and carry whatever little overlap we have.
        if overlap_start <= chunk_start_idx:
            overlap_start = chunk_start_idx + 1

        # The next chunk begins at the first sentence of the overlap block.
        # Those sentences will appear at the start of the next chunk, giving
        # it the context it needs from the previous chunk.
        chunk_start_idx = overlap_start

    return chunks
