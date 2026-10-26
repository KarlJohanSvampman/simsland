# Why intentions did not lead to anything (measured 2026-10-26)

## 1. The model server was the bottleneck
- `docker-compose.yml` points the sim at `llama3.1:latest` on the Ollama box (192.168.10.203). Measured there: reading a
  4,200-token prompt took 46 s (92 tokens/s) and writing 80 tokens took 32 s (2.5 tokens/s); the loaded model is only partly on
  the GPU (2.6 of 3.4 GB). A character's real decision prompt is about 1,450 tokens (359 system + 1,083 context) and the reply
  was uncapped, so one decision took 60-100 s. The gate gave up at 90 s, so most decisions were thrown away and asked for again
  (cognition log: 65 "call abandoned after 90.0s"). Rui's last decision was 8 hours old.
- Changes: the reply is capped (`DECISION_MAX_TOKENS`, default 220 -> `num_predict`), and the gate waits 170 s instead of 90
  (`LLM_CALL_MAX_WAIT_SECONDS`). The server itself (GPU offload, a faster model, `OLLAMA_NUM_PARALLEL`) is outside this repo.
- Probing with another model evicts `llama3.1` from the server's memory and costs a ~15-30 s reload for the sim.

## 2. 90% of intentions have no way to happen without the model
Of 195 intentions across the eight adults, 19 (10%) had an automatic strategy (`systems/strategy.py::resolve_strategy`): eat,
drink, nap, relieve worry, contact a person. The rest (34 expectations, `keep_up_with:*`, compliments, gossip, seek_romance,
exercise, feed/remind/check on child, ...) only happen if the model picks them from the menu, and each character gets a turn every
10+ minutes at best. A household has 30-40 intentions open at once.

## 3. What changed
- A parent's `feed_child_*` / `remind_child_*` is carried out by `systems/child_care.py::tend_child` from the agent loop, with no
  model in the loop (both parents' copies are cleared; a stale one is dropped).
- A generic intention that goes unanswered past its deadline records what the character was doing at that check-in
  (`doing_at_checkin`, last 5 in `checkins`, `systems/doing.py`), and while it is pressing the prompt says so and asks: "why am I not
  feeding X right now? What could be more important than this, and what is actually in the way?"
  (`brain/context_builder.py::_sec_pressing_intentions`; survival/health/child intentions or anything escalated twice, two at most).
- Households start with food (`systems/household_pantry.py`; they had none, so every hunger meant a shopping trip or takeout and
  children could only wait). A trip of three hours or more includes meals and drinks (a school day no longer ends with a child at
  hunger 83).

## 4. Still open
- Expectations (`make_dinner`, `family_dinner_together`, ...) and the long tail of lt_need intentions still depend on the model.
- The intention list itself (30-40 per person) is what the prompt has to choose from and is worth pruning.
