"""
systems/text_clean.py -- small text clean-ups shared by the speech and conversation-log paths.
"""

_QUOTES = '"“”„«»'


def clean_utterance(text):
    """A spoken line without the quotation marks wrapped around it. The model often writes its SAY in quotes, a retried or
    repeated line comes back with another pair around the first (""How's the morning?"" ...), and the log then shows them all.
    Leading and trailing runs of quote marks are removed when what is between them holds no quote mark of its own; a line that
    quotes someone inside it ("Hi," she said, "bye.") is left alone."""
    t = (text or "").strip()
    if not t:
        return t
    start = 0
    while start < len(t) and t[start] in _QUOTES:
        start += 1
    end = len(t)
    while end > start and t[end - 1] in _QUOTES:
        end -= 1
    inner = t[start:end].strip()
    if any(q in inner for q in _QUOTES):
        return t
    return inner
