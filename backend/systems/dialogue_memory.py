"""
systems/dialogue_memory.py

Per the user's explicit ask: every spoken exchange -- what a character
says AND what they hear -- gets committed to real memory (store_memory),
tagged with lightweight keywords extracted from the utterance so a later
recall/search can actually surface "that conversation about X" instead of
only ever matching a memory's exact original wording.

No NLP library involved -- a plain stopword-filtered token list, same
spirit as this codebase's existing keyword-bucket approach (see
llm_brain.py's speech-cue regex, stories.py's CATEGORY_KEYWORDS).
Deliberately low importance (0.2) -- store_memory()'s importance/recency-
scored 150-cap (brain/memory.py::prune_memories) then naturally lets
these fade out first once the cap fills, rather than crowding out a
character's genuinely notable memories with routine chatter.
"""

import re

_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "if", "then", "so", "of", "to", "in", "on",
    "at", "for", "with", "as", "is", "are", "was", "were", "be", "been", "being",
    "i", "you", "he", "she", "it", "we", "they", "me", "him", "her", "us", "them",
    "my", "your", "his", "its", "our", "their", "this", "that", "these", "those",
    "do", "does", "did", "have", "has", "had", "will", "would", "can", "could",
    "should", "not", "no", "yes", "just", "really", "very", "about", "up", "out",
    "get", "got", "going", "go", "think", "know", "like", "well", "okay", "ok",
    "there", "here", "what", "when", "where", "who", "why", "how", "some", "any",
}

_WORD_RE = re.compile(r"[A-Za-z']+")


def extract_keywords(text, limit=5):
    """Cheap, deterministic keyword pull: real (non-stopword) tokens,
    with a mid-sentence capitalized word (very likely a name/proper noun
    -- the most useful thing to later search by) prioritized first, then
    other content words, capped at `limit`."""
    if not text:
        return []
    words = _WORD_RE.findall(text)
    seen = set()
    proper, other = [], []
    for i, w in enumerate(words):
        lw = w.lower()
        if lw in _STOPWORDS or len(lw) < 3 or lw in seen:
            continue
        seen.add(lw)
        if w[0].isupper() and i > 0:
            proper.append(lw)
        else:
            other.append(lw)
    return (proper + other)[:limit]


def remember_dialogue(speaker, listener, utterance, world, speech_act=None, conversation_type=None):
    """Stores the exchange into BOTH participants' own memory, each from
    their own perspective -- the speaker remembers what they said, the
    listener remembers what they heard -- tagged with keywords so either
    can later recall it by subject.

    Per the user's explicit ask: real memory is imperfect, and what
    makes less impression should be remembered in vaguer terms. A
    routine exchange is kept only as "the gist" (a topic keyword, not
    the verbatim line); a salient one (a threat, an argument, someone
    clearly upset) is kept as the real, exact words -- and keeps more of
    its keyword tags too, same randomized-detail spirit as sightings."""
    from brain.memory import store_memory
    from systems.memory_detail import compute_salience, select_details, relationship_closeness

    tick = world.get("tick", 0)
    keywords = extract_keywords(utterance)
    speaker_name = speaker.get("name", "Someone")
    listener_name = listener.get("name", "someone") if listener else "someone"

    high_salience = compute_salience(
        conversation_type=conversation_type,
        emotion=speaker.get("emotion"),
        other_emotion=listener.get("emotion") if listener else None,
    )

    # Each side's own closeness to the OTHER person -- the speaker
    # remembers more detail about someone they're close to, and
    # separately so does the listener, not necessarily the same amount.
    speaker_closeness = relationship_closeness(speaker, listener["id"] if listener else None)
    listener_closeness = relationship_closeness(listener, speaker["id"]) if listener else 0.0

    kept_keywords = list(select_details({k: k for k in keywords}, high_salience,
                                         closeness=max(speaker_closeness, listener_closeness)).keys())
    topic = ", ".join(kept_keywords) if kept_keywords else "something"

    if high_salience:
        said_text = f'You told {listener_name}, "{utterance}"'
        heard_text = f'{speaker_name} told you, "{utterance}"'
    else:
        said_text = f"You told {listener_name} something about {topic}."
        heard_text = f"{speaker_name} told you something about {topic}."

    from systems.memory_detail import compute_drop_probability

    store_memory(
        speaker,
        said_text,
        importance=0.4 if high_salience else 0.2,
        tags=["dialogue", "said"] + kept_keywords,
        kind="dialogue",
        tick=tick,
        people=[listener["id"]] if listener else [],
        # A salient exchange (a threat, an argument, ...) is important
        # enough to skip the hourly blur-into-a-summary pass entirely and
        # move to long-term memory word for word -- see memory_
        # consolidation.py's aggregate handling.
        aggregate=not high_salience,
        drop_probability=compute_drop_probability(high_salience, speaker_closeness),
    )

    if listener:
        store_memory(
            listener,
            heard_text,
            importance=0.4 if high_salience else 0.2,
            tags=["dialogue", "heard"] + kept_keywords,
            kind="dialogue",
            tick=tick,
            aggregate=not high_salience,
            drop_probability=compute_drop_probability(high_salience, listener_closeness),
            people=[speaker["id"]],
        )
