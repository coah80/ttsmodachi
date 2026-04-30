from __future__ import annotations

import re
import unicodedata


CUSTOM_EMOJI_RE = re.compile(r"<a?:([^:<>]+):\d+>")
CODE_BLOCK_RE = re.compile(r"```.*?```", re.DOTALL)
INLINE_CODE_RE = re.compile(r"`[^`]*`")
SPOILER_RE = re.compile(r"\|\|.*?\|\|", re.DOTALL)
URL_RE = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
MENTION_RE = re.compile(r"<[@#&]!?\d+>")
REPEATED_WHITESPACE_RE = re.compile(r"\s+")


ACRONYMS = {
    "iirc": "if I recall correctly",
    "afaik": "as far as I know",
    "wdym": "what do you mean",
    "imo": "in my opinion",
    "brb": "be right back",
    "btw": "by the way",
    "irl": "in real life",
    "jk": "just kidding",
    "gtg": "got to go",
    "rn": "right now",
    "ppl": "people",
    "rly": "really",
}


def clamp_repeated_characters(text: str, limit: int | None) -> str:
    if not limit or limit < 1:
        return text
    out: list[str] = []
    previous = ""
    count = 0
    for char in text:
        if char == previous:
            count += 1
        else:
            previous = char
            count = 1
        if count <= limit:
            out.append(char)
    return "".join(out)


def expand_acronyms(text: str) -> str:
    words = text.split(" ")
    return " ".join(ACRONYMS.get(word.lower(), word) for word in words)


def apply_replacements(text: str, replacements: list[tuple[str, str]] | None) -> str:
    if not replacements:
        return text
    for source, replacement in sorted(replacements, key=lambda item: len(item[0]), reverse=True):
        if not source:
            continue
        if source.replace(" ", "").isalnum():
            pattern = re.compile(rf"(?<!\w){re.escape(source)}(?!\w)", re.IGNORECASE)
            text = pattern.sub(replacement, text)
        else:
            text = re.sub(re.escape(source), replacement, text, flags=re.IGNORECASE)
    return text


def is_unicode_emoji(char: str) -> bool:
    codepoint = ord(char)
    return (
        0x1F000 <= codepoint <= 0x1FAFF
        or 0x2600 <= codepoint <= 0x27BF
        or 0xFE00 <= codepoint <= 0xFE0F
    )


def replace_unicode_emoji(text: str, *, skip_emoji: bool) -> str:
    out: list[str] = []
    for char in text:
        if not is_unicode_emoji(char):
            out.append(char)
            continue
        if skip_emoji:
            continue
        name = unicodedata.name(char, "emoji").lower()
        if name.startswith("variation selector") or name.startswith("emoji modifier"):
            continue
        name = name.replace("emoji modifier", "").replace("variation selector", "")
        name = REPEATED_WHITESPACE_RE.sub(" ", name).strip()
        if name:
            out.append(f" emoji {name} ")
    return "".join(out)


def clean_message(
    text: str,
    *,
    attachments: list[str] | None = None,
    skip_emoji: bool = False,
    repeated_chars: int | None = 8,
    required_prefix: str | None = None,
    announce_name: str | None = None,
    replacements: list[tuple[str, str]] | None = None,
) -> str:
    text = text.strip()
    if required_prefix:
        if not text.startswith(required_prefix):
            return ""
        text = text[len(required_prefix) :].strip()

    text = SPOILER_RE.sub(" spoiler avoided ", text)
    text = CODE_BLOCK_RE.sub(" code block ", text)
    text = INLINE_CODE_RE.sub(" code snippet ", text)
    text = URL_RE.sub(" link ", text)
    text = MENTION_RE.sub(" mention ", text)
    if skip_emoji:
        text = CUSTOM_EMOJI_RE.sub("", text)
    else:
        text = CUSTOM_EMOJI_RE.sub(lambda m: f" emoji {m.group(1)} ", text)
    text = replace_unicode_emoji(text, skip_emoji=skip_emoji)

    if attachments:
        attachment_text = "multiple files" if len(attachments) > 1 else describe_attachment(attachments[0])
        text = f"{text} with {attachment_text}".strip()

    text = apply_replacements(text.lower(), replacements)
    text = expand_acronyms(text)
    text = clamp_repeated_characters(text, repeated_chars)
    text = REPEATED_WHITESPACE_RE.sub(" ", text).strip()

    if announce_name and text:
        text = f"{announce_name} said {text}"

    if not any(char.isalnum() for char in text):
        return ""
    return text


def describe_attachment(filename: str) -> str:
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if extension in {"bmp", "gif", "ico", "png", "psd", "svg", "jpg", "jpeg", "webp"}:
        return "an image file"
    if extension in {"mid", "midi", "mp3", "ogg", "wav", "wma", "flac"}:
        return "an audio file"
    if extension in {"avi", "mp4", "wmv", "m4v", "mpg", "mpeg", "mov"}:
        return "a video file"
    if extension in {"zip", "7z", "rar", "gz", "xz", "tar"}:
        return "a compressed file"
    if extension in {"doc", "docx", "txt", "odt", "rtf", "pdf"}:
        return "a document"
    return "a file"
