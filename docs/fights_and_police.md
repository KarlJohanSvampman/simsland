# Fights and the police

**What a fight is about.** A conflict (`systems/conflict_pipeline.py`) carries the grievances brought to the table as its `topic`
("the noise at night and the mess left lying around"); one-off outbursts (impulse, gang war, sports and romantic rivalry, revenge)
carry a reason from their `context`. `systems/fights.py` keeps `world["fight_log"]`: who, the aggressor, the topic, how far it got,
how it ended, where, who was there, the incident and the police report. Each person in it remembers it in words
("Had a fight with Lena about the noise at night that turned physical. Karim threw the first punch."), which is what the
character's Events list shows. A quarrel that was swallowed (`suppressed`) is not logged as a fight; the one who backed down
remembers wanting to bring it up and the other only senses tension.

**Who is the offender.** For a physical fight the one readier to escalate (ties to whoever started it) is the offender, the other the
victim; the incident has both (`offender_id`, `victim_id`, `topic`, `conflict_id`).

**Who calls.** Never the offender (the old 15% self-report, and the `call_911` action, are gone for them). The victim is tried first, then
whoever was within four tiles; off-grid characters and children are not callers. The call says "Karim just attacked Lena."

**When the police arrive** (`systems/police_report.py`) they file one report per incident and interview everyone: the offender admits,
plays it down or denies (by their own resolve); the victim makes a complaint, declines to press charges (likelier at home or with someone
they like) or is too frightened to say much; witnesses saw it, only heard it, or look the other way for someone they like; the caller
explains the call. Each person keeps a memory of what they said. The report carries `evidence` (admission +0.40, each witness who saw it
+0.12 up to 0.24, a complaint +0.10, a victim who declines -0.30, one too frightened -0.15, a denial -0.05).

**Arrest and trial** (`systems/law.py`). An assault or disturbance waits for the report; the evidence is added to the solve rate for the
arrest, an arrested offender is interrogated again at the station (shown the others' statements they may crack and admit it), and half
the evidence moves the guilty verdict. An unarrested report says why ("the complainant would not go on with it").

Read them at `GET /admin/police_reports` and `GET /admin/fights` (through nginx at port 8000).

**Not done:** a UI panel for the reports (they show up in the characters' Events), interviews for children, witnesses outside the
room, and reports for the career-crime incidents (burglary and the rest from `systems/crime.py`).
