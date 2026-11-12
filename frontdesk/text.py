"""Small text utilities shared by retrieval, routing, and answer composition."""

from __future__ import annotations

import re

STOPWORDS = {
    "a", "about", "after", "again", "all", "also", "am", "an", "and", "any", "are",
    "as", "at", "be", "because", "been", "before", "being", "between", "both", "but",
    "by", "can", "could", "did", "do", "does", "doing", "done", "for", "from", "get",
    "got", "had", "has", "have", "having", "he", "her", "here", "hers", "him", "his",
    "how", "i", "if", "in", "into", "is", "it", "its", "just", "know", "like", "me",
    "more", "most", "my", "need", "no", "not", "now", "of", "on", "one", "or", "our",
    "out", "please", "should", "so", "some", "tell", "than", "that", "the", "their",
    "them", "then", "there", "these", "they", "thing", "this", "those", "to", "too",
    "up", "us", "use", "very", "was", "we", "were", "what", "when", "where", "which",
    "who", "why", "will", "with", "would", "you", "your", "yours", "help", "thanks",
    "thank", "hi", "hello", "hey", "question", "want", "wanted", "looking", "find",
    "available", "availability", "possible", "able", "someone", "anyone", "team",
}

GENERIC_REPO_WORDS = {
    "info", "website", "admin", "template", "docs", "github", "org", "mirror",
    "test", "api", "web", "ui", "app", "mobile", "backend", "frontend", "contracts",
}


def tokenize(value: str, min_length: int = 3) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for token in re.findall(r"[a-z0-9]+", value.casefold()):
        if len(token) < min_length or token in STOPWORDS or token in seen:
            continue
        seen.add(token)
        result.append(token)
    return result


def token_set(value: str, min_length: int = 3) -> set[str]:
    return set(tokenize(value, min_length))


def coverage(query_terms: set[str], text_terms: set[str]) -> float:
    if not query_terms:
        return 0.0
    return len(query_terms & text_terms) / len(query_terms)


def score_text(
    query: str,
    text: str,
    *,
    title: str = "",
    tags: str = "",
    description: str = "",
) -> tuple[float, float]:
    """Return a weighted relevance score and query-term coverage."""
    query_norm = " ".join(query.casefold().split())
    query_terms = token_set(query)
    text_terms = token_set(" ".join((text, title, tags, description)))
    if not query_terms:
        return 0.0, 0.0
    matched = query_terms & text_terms
    score = float(len(matched))
    title_terms = token_set(title)
    tag_terms = token_set(tags)
    score += 2.0 * len(matched & title_terms)
    score += 1.5 * len(matched & tag_terms)
    # A phrase match in the title or text is a strong signal.
    for phrase in (title, text[:600]):
        phrase_norm = " ".join(phrase.casefold().split())
        if query_norm and query_norm in phrase_norm:
            score += 5.0
    return score, coverage(query_terms, text_terms)


def excerpt(value: str, limit: int = 700) -> str:
    cleaned = re.sub(r"\r\n?", "\n", value).strip()
    if len(cleaned) <= limit:
        return cleaned
    cut = cleaned[:limit]
    boundary = max(cut.rfind("\n\n"), cut.rfind(". "))
    if boundary > limit // 2:
        cut = cut[:boundary]
    return cut.rstrip() + "…"


def split_message(value: str, limit: int = 1900) -> list[str]:
    """Split a message into Discord-safe chunks without cutting code fences."""
    text = value.strip()
    if not text:
        return [""]
    chunks: list[str] = []
    while len(text) > limit:
        window = text[:limit]
        cut = max(window.rfind("\n\n"), window.rfind("\n"), window.rfind(". "))
        if cut < limit // 2:
            cut = limit
        chunk = text[:cut].rstrip()
        if chunk:
            chunks.append(chunk)
        text = text[cut:].lstrip()
    if text:
        chunks.append(text)
    return chunks


def looks_like_greeting(value: str) -> bool:
    text = re.sub(r"[^\w\s]", " ", value.casefold()).strip()
    return text in {"hi", "hello", "hey", "hey there", "hello there", "good morning", "good afternoon", "good evening", "yo"}


def looks_like_thanks(value: str) -> bool:
    text = value.casefold()
    return any(
        phrase in text
        for phrase in ("thanks", "thank you", "thx", "appreciate it", "that helps", "perfect", "great, thanks")
    )


def looks_like_dissatisfaction(value: str) -> bool:
    text = value.casefold()
    return any(
        phrase in text
        for phrase in (
            "that's wrong",
            "that is wrong",
            "incorrect",
            "not correct",
            "not right",
            "not helpful",
            "unhelpful",
            "doesn't answer",
            "does not answer",
            "didn't answer",
            "did not answer",
            "still confused",
            "not clear",
            "unclear",
            "that's not what i asked",
            "that is not what i asked",
            "wrong answer",
            "bad answer",
            "not satisfied",
            "i already tried",
        )
    )


def looks_urgent(value: str) -> bool:
    text = value.casefold()
    return any(
        phrase in text
        for phrase in (
            "urgent", "emergency", "immediately", "asap", "fraud", "scam", "security issue",
            "data breach", "harassment", "abuse", "threat", "compromised", "critical",
        )
    )


def looks_like_human_request(value: str) -> bool:
    text = value.casefold()
    return any(
        phrase in text
        for phrase in (
            "human", "real person", "maintainer", "moderator", "someone from the team",
            "talk to someone", "speak to someone", "staff member", "escalate", "complaint",
            "speak to a person", "talk to a person",
        )
    )


def looks_like_codebase_change_request(value: str) -> bool:
    """Detect requests that could lead to an issue or pull request."""
    text = value.casefold()
    return bool(re.search(r"\b(issue|bug report|pull request|pull-request|pr|feature request|submit|contribute|contribution)\b", text))
