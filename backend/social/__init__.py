"""
social/ -- Social discourse, standing & confrontation (design: "Simsland - Social Discourse, Standing & Confrontation
System", Draft 1.0).

Three layers, kept apart and joined by events:

  1. personal social state  -- what one character thinks and feels about another
       standing.py     how A regards B (directional, -100..100, resistant to small swings)
       frustration.py  how dissatisfied A is with B, in general and per issue (separate from standing)
       initiative.py   how much A is willing to invest in B: approach, repair, or avoid

  2. social discourse       -- what characters say and negotiate
       (the conversation itself lives in brain/conversations.py + systems/conversation_archive.py)
       discourse.py    what each line means socially (the speaker's own AI says it) and what a finished
                       conversation adds up to (the AI reads it afterwards)
       issues.py       the problems people have with each other: persistent, each side's own position
       confrontations.py  a structured attempt to address an issue, inside a conversation: type, sides,
                       escalation, resolution
       contracts.py    explicit agreements and implicit expectations, violations, renegotiation
       rumours.py      claims about people passed on, each listener's own interpretation

  3. social consequences    -- applied by the modules above when an event happens; nothing is recalculated globally.

The AI decides (what was said, what it meant, whether to escalate, whether to accept); this package validates what
it says and keeps the authoritative state.
"""
