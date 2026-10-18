# Relationship impact system — plan

Status: proposal (nothing here is built yet except the conversation floor, which
emits `conversation_ignored` — the first producer this system will consume).

## 1. Goal

Every intentional thing one character does *to or about* another — said, done,
posted, or merely implied — becomes a small **impact entry** on the pair's
relationship. The recipient (or observer) decides whether it even registered and
how strongly; only what registers counts. Scores, ratios, grudges and the
"standing" penalty all derive from those entries, so there is one source of
truth instead of the ad-hoc `+15 hostility / -20 trust` constants now scattered
through `hostile_actions.py`, `conversation_analysis.py`, `target_reactions.py`.

## 2. Data model

One **ledger per pair** (`world["relationship_ledgers"]["idA|idB"]`, ids sorted),
because the relationship object *is* the pair.

```
entry = {
  id, tick,
  source,            # who did/said it
  target,            # who it was aimed at (None = general / one-way expression)
  layer,             # "intent" (source's POV) | "perceived" (recipient's POV)
  polarity,          # +1 / -1
  kind,              # taxonomy id, see §3
  magnitude,         # intent: M (1-10).  perceived: final value V
  discretion,        # 0.0-1.0, set on intent entries
  channel,           # speech | action | post | observed | learned_secondhand | expression
  ref,               # {type: conversation|speech|action|post|event, id, line}
  origin,            # for perceived entries: id of the intent entry
  memory_refs,       # ids of memories the source drew on (positive "I remember you" acts)
  registered,        # intent entries: did it land? (set by the evaluation)
  checks_passed, checks_total,   # audit trail from the evaluation ladder
}
```

Only **perceived** entries move scores. Intent entries are kept so we can show
"meant vs received" and so a missed insult can still surface later (someone
tells you what was said about you → re-evaluate through the *learned* path).

`summary` stored beside the entries, updated incrementally (O(1) per write):

| field | meaning |
|---|---|
| `pos_total`, `neg_total` | sum of perceived V by polarity |
| `engagement` | Σ \|V\| over all perceived entries (plus resolved-grudge scores) — "how much these two matter to each other" |
| `balance` | Σ signed V |
| `by_char[X].pos_caused / neg_caused / net_caused` | perceived entries where X is the source |
| `neg_ratio_pair` | neg_total / (pos_total + neg_total) in % |
| `by_char[X].neg_ratio` | X's neg_caused / (pos_caused + neg_caused) in % |
| `by_char[X].share_pos / share_neg` | X's slice of the pair's positive / negative total in % |

Entries are a bounded ring (e.g. last 400 per pair); older ones are folded into
per-kind counters in the summary so persistence stays small. The two characters'
existing `relationships[other]` dicts get cheap derived fields (`impact_balance`,
`neg_ratio`, `active_grudge`) and the existing scalars (trust, resentment,
hostility, respect, friendship, fear) are nudged by a per-kind table — replacing
the scattered constants.

## 3. Kinds, polarity and cost of deciding it

`definitions.json → impact_kinds`: `{id: {polarity, base, scalar_deltas}}`.

- **Positive:** apology, concession, altruism, solidarity, compliment, favor,
  generosity, encouragement, pride, love, kindness, congratulation,
  personal_acknowledgement (references the other's hobbies/preferences/past —
  memory-backed), forgiveness.
- **Negative:** insult, ignored (ignored_heard worse), avoidance, disrespect,
  humiliation, harassment, meanness, hate, shaming, trust_breach, unfair_treatment,
  objectification, patronizing, provocation, threat, intimidation, manipulation,
  controlling, exclusion, exposure, suspected_theft, suspected_gossip, lie,
  slander/frame.

Deciding the kind/polarity, cheapest first — LLM is never in the hot path:

1. **Declared intent.** Add an optional `intent` to the speech/action decision
   schema (`hurt | help | deceive | neutral`, optional `discretion`). The speaker's
   own model already knows what it meant.
2. **Structured lookup.** `speech_act` and action ids map straight to a kind
   (`insult`, `threaten`, `punch`, `steal_from`, `apologize`, `thank`, ...).
3. **Existing analysis.** `conversation_analysis.analyze_message` already scores
   tone/speech-act; reuse its output instead of re-parsing text.
4. **Lexicon fallback** for free text when 1–3 are silent.
5. **Async LLM classification** (via `systems/bg_llm.py`, off the tick thread) only
   for long, ambiguous lines — optional, budgeted.

## 4. Discretion

A 0–1 number on the intent entry: how covert the act is. Default derived from
traits (subtle/sly/calm → high; impulsive/hot-tempered → low), volume, audience
(bystanders), medium (a text is deliberate), intoxication; the LLM can override
via `intent.discretion`.

## 5. Does it register? The evaluation ladder

Run for the recipient (or, for neutral actions, the observer). Cheap boolean
checks in order; stop at the first failure and keep the count of passes `n`:

1. **Perceivable** — in range / audible at that volume / line of sight / awake and
   attending / message actually read.
2. **Recognisable as aimed at me** — named, addressed, only person present, or (for
   third-party mentions) I actually learned of it.
3. **Intelligible** — age/comprehension can parse it (a 4-year-old misses sarcasm;
   uses `child_worldview`), language, not too garbled.
4. **Fits what I know of the source** — relationship priming: resentment, hostility,
   an active grudge make hostile readings pass; low trust makes kindness fail
   ("what do they want?").
5. **Survives my own evidence** — a lie/slander I can disprove from memory registers
   as an *attempted* lie, not the intended harm; a compliment that rings false
   fails.
6. **Sensitivity** — temperament and current mood (stressed/tired/proud) vs the
   magnitude.
7. *(optional, async)* an interpretive check for the genuinely ambiguous case.

Threshold `T = 3 + ceil(3·discretion)` — the more covert the act, the more
checks must pass before it's read as intended.

- `n < T` → **not registered.** The intent entry is kept with `registered=false`.
- `n ≥ T` → **registered.** Value
  `V = M·(1 + 0.25·n) − discretion·(M/2)`; a perceived entry with value `V` is
  written on the pair, `origin` pointing at the intent entry. (`V ≤ 0` also means
  not registered. Given `T ≥ 3` this only matters if the constants are retuned, but
  it matches the "reduce by discretion × half the unmodified score" rule.)

All constants live in `definitions.json` so they can be tuned without code.

## 6. Pathways into the ledger

| Pathway | Entry pair | Notes |
|---|---|---|
| **Directed** (conversation line, action on me) | (source, target) | Ladder evaluated for the target at hearing/seeing time. |
| **Mentioned to a third party** (gossip, slander, framing, a lie about someone) | (source, subject) intent entry; plus (listener, subject) perceived entry *if the listener believes it* (credibility = trust in source, `child_cognition.source_credibility`) | The subject only gets an entry once they **learn** of it (told, overheard, post read) — the *learned* channel, same ladder, step 2 = "I learned of it". |
| **Online** (posts/comments) | same as above, `channel=post` | Registers when the subject reads it; fan-out to readers like gossip. |
| **Observed, neutral target** (A does something to or near X; observer O) | (O, A) | Cheap pre-filter: only evaluated for observers with a strained relationship to A (resentment/hostility/active grudge) or when the act is salient/odd. Step 2 becomes "assume it's aimed at me?": anomalies in appearance, timing, place, proximity to O push it through; threshold relaxes with strain. Result is flagged `misattributed` (can be wrong and later corrected) and valued at half. A neutral observer who merely sees A mistreat X also records an entry on (O, A), scaled by closeness to X and O's values. |
| **One-way expressions** (see §8) | (speaker, each audible character) | No conversation, no ball. |
| **Conversation floor** | (speaker, ignorer) | `conversation_ignored` → kind `ignored` / `ignored_heard`. Exists today as an event. |

## 7. Grudges, expectations, resolution (built on the ledger)

- A grudge opens when a registered negative entry crosses a value threshold or
  repeats within a window. `grudge = {id, holder, offender, origin_entry,
  created, short_term_until, long_term_retention, priority, refreshes, status}`.
- **Refresh** (another negative entry while open): extends short-term, adds to
  long-term retention, raises priority.
- **Expectation:** while a grudge is open the holder expects an apology;
  surfaced in their context ("you're waiting for X to apologise").
- **Behaviour while open:** interactions with the offender are cold; the holder
  tends to mirror the original behaviour; temperament picks the expression
  (hurtful remarks, jabs at belongings, throwing things, walking out, crying,
  poking/pushing, escalation to a conflict via `target_reactions` weights).
- **Resolution:** an apology entry clears the short-term grudge and shortens
  long-term retention; further apologies / altruistic acts / concessions shorten
  it more. At zero retention it is replaced by one aggregated long-term memory
  (how it began, how it ended). Its **score** =
  `ceil((resolved_tick − created_tick) × retention_at_creation)`, added to the pair's
  `engagement`.
- The standing penalty is derived from open grudges + the negative ratio.

## 8. One-way verbal expressions (to build before the ledger producers)

Exclaims, remarks, shouts, vents, mutters: speech that does **not** open a
conversation. Today `apply_speech` with no resolvable listener just wakes up to
four nearby people. Plan: a small `systems/expressions.py` — an expression
record (speaker, text, volume, optional target, `directed` flag, audible set from
the perception volume tiers) that each audible character processes through
ladder steps 1–2 only. Undirected remarks reach the ledger only for hearers who
have reason to take them personally (strained relationship) or when explicitly
targeted. No floor, no ball, no timers.

## 9. Positive acts that reference memory (underlining)

When the conversation prompt retrieves memories about the listener, give each an
id; the speaker's output may list `uses_memories: [ids]`. Validated ids produce a
`personal_acknowledgement` impact (positive) with `memory_refs`, and the log/UI
underlines those phrases with a link back to the memory.

## 10. Cost / performance

- No LLM on the hot path; kinds come from intent tags and tables.
- The ladder is pure Python booleans, stops at first failure.
- Ledger writes happen only for intentional acts (a handful per minute);
  observers are filtered before evaluation.
- Summary is maintained incrementally; entries are a bounded ring.
- Optional LLM steps run through `bg_llm` so they never block a tick.

## 11. Build order

1. `systems/relationship_ledger.py`: data model, kind table, `log_intent()`,
   `evaluate_and_register()`, summary maths, percentages; unit tests with the
   worked numbers below. Hook `conversation_ignored` as the first producer.
2. Perception ladder module + producers: speech (intent tag + lookup), hostile
   actions, `conversation_analysis` relationship effects routed through it.
3. Grudges, expectations, apology/resolution, escalation hooks, score.
4. Third-party / learned / slander / online / observer pathways.
5. One-way expressions subsystem (§8).
6. Memory-reference acknowledgement + frontend: pair panel (scores, ratios), floor
   cue ("thinking…"), underlined memory references.

(Expressions could move ahead of step 2 if you want remarks handled first.)

## 12. Worked example

Marcus makes a sly dig at Theo while Theo is across the room: `M = 6`,
`discretion = 0.8` → `T = 3 + ceil(2.4) = 6`.

- Theo is 8 m away, speech at normal volume: step 1 passes. Step 2 (named, I'm
  the only other person here) passes. Step 3 passes, 4 passes (open grudge),
  5 passes, 6 fails → `n = 5 < T`. **Not registered**; the intent entry stays
  `registered=false`.
- Same dig, Theo 2 m away and already resentful, `discretion` 0.4 → `T = 5`;
  all six checks pass, `n = 6`.
  `V = 6·(1 + 0.25·6) − 0.4·3 = 15 − 1.2 = 13.8` → perceived `insult` entry on the
  pair, Marcus's `neg_caused` +13.8, grudge threshold crossed → grudge opens.

## 13. Decisions needed

1. Retention/grudge times are in **sim ticks** (1 tick = 1 sim second at 1×). OK to
   store sim time and add a global scale knob?
2. Magnitude scale (1–10 base) and the rule `V = M·(1 + 0.25n) − d·M/2` — OK as
   the single combined formula?
3. `engagement` as the **sum of absolute values** (hostility counts as
   engagement) with signed `balance` kept separately — agreed?
4. Order: ledger first, or one-way expressions first?
