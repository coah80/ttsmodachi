from __future__ import annotations

import re


REPEATED_WHITESPACE_RE = re.compile(r"\s+")
SENTENCE_PUNCTUATION = ".!?"
CLOSING_PUNCTUATION = "\"')]}"
OPENING_PUNCTUATION = "\"'([{"
MAX_GRAMMAR_PAUSES = 24
COMMA_PAUSE_MS = 280
CLAUSE_PAUSE_MS = 410
SENTENCE_PAUSE_MS = 680
QUESTION_EXCLAMATION_PAUSE_MS = 780
ELLIPSIS_PAUSE_MS = 980
COMMON_ABBREVIATIONS = {
    "dr",
    "jr",
    "mr",
    "mrs",
    "ms",
    "mx",
    "prof",
    "sr",
    "st",
    "vs",
}


def _pause_command(length_ms: int) -> str:
    return f"\x1b\\pause=0\\\x1b\\mrk=21{int(length_ms):>07}\\"


def _word_before(text: str, index: int) -> str:
    before = text[:index].rstrip()
    if not before:
        return ""
    return re.split(r"\s+", before)[-1].strip(OPENING_PUNCTUATION)


def _has_next_word(text: str, index: int) -> bool:
    while index < len(text) and text[index].isspace():
        index += 1
    while index < len(text) and text[index] in OPENING_PUNCTUATION:
        index += 1
    return index < len(text) and text[index].isalnum()


def _should_pause_after_sentence(text: str, start: int, end: int, mark: str) -> bool:
    if not _has_next_word(text, end + 1):
        return False
    if mark == ".":
        previous = text[start - 1] if start > 0 else ""
        next_char = text[end + 1] if end + 1 < len(text) else ""
        if previous.isdigit() and next_char.isdigit():
            return False
        word = _word_before(text, start).lower().rstrip(".")
        if word in COMMON_ABBREVIATIONS or len(word) == 1:
            return False
    return True


def add_grammar_pauses(text: str) -> str:
    """Add native Talkmodachi pause commands after sentence-like punctuation."""
    text = REPEATED_WHITESPACE_RE.sub(" ", text).strip()
    if not text or "\x1b" in text:
        return text

    out: list[str] = []
    index = 0
    pause_count = 0
    while index < len(text):
        char = text[index]

        if char in SENTENCE_PUNCTUATION:
            start = index
            while index + 1 < len(text) and text[index + 1] in SENTENCE_PUNCTUATION:
                index += 1
            mark = text[start : index + 1]
            out.append(mark)
            while index + 1 < len(text) and text[index + 1] in CLOSING_PUNCTUATION:
                index += 1
                out.append(text[index])
            if pause_count < MAX_GRAMMAR_PAUSES and _should_pause_after_sentence(text, start, index, mark):
                pause_ms = ELLIPSIS_PAUSE_MS if "..." in mark else SENTENCE_PAUSE_MS
                if "!" in mark or "?" in mark:
                    pause_ms = max(pause_ms, QUESTION_EXCLAMATION_PAUSE_MS)
                out.append(_pause_command(pause_ms))
                pause_count += 1
            index += 1
            continue

        if char in ",;:":
            out.append(char)
            next_char = text[index + 1] if index + 1 < len(text) else ""
            previous = text[index - 1] if index > 0 else ""
            if (
                pause_count < MAX_GRAMMAR_PAUSES
                and _has_next_word(text, index + 1)
                and not (char in ",:" and previous.isdigit() and next_char.isdigit())
            ):
                out.append(_pause_command(COMMA_PAUSE_MS if char == "," else CLAUSE_PAUSE_MS))
                pause_count += 1
            index += 1
            continue

        out.append(char)
        index += 1

    return "".join(out)
