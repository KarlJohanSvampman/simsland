# SIMSLAND ARCHITECTURE MAP

---

# AUTHORITATIVE SYSTEMS

These systems are the single source of truth.

Other systems must delegate to them.

---

# COGNITION

Authoritative:
- llm_brain.py
- context_builder.py

Responsibilities:
- subjective reasoning
- emotional cognition
- strategy selection
- conversation decisions
- intention interpretation

NOT responsible for:
- movement
- animation
- pathfinding
- interaction timing

---

# INTENTIONS

Authoritative:
- active_intentions

Responsibilities:
- bodily pressures
- schedules
- social drives
- goals
- urgency arbitration

Sources:
- body systems
- schedules
- relationships
- emotions
- events

Deprecated:
- intentions.py
- intention.py
- scheduling.py intention queues

---

# ACTIVITIES

Authoritative:
- activities.py

Responsibilities:
- embodied execution
- phase transitions
- reservations
- interaction lifecycle
- timing
- completion

Phases:
- start
- walking
- arriving
- using
- finishing
- complete

Deprecated:
- activity_runtime.py
- activity_state

---

# MOVEMENT

Authoritative:
- movement.py

Responsibilities:
- route traversal
- interpolation
- segment switching
- arrival detection

NOT responsible for:
- choosing destinations
- activities
- cognition

---

# NAVIGATION

Authoritative:
- navigation.py
- world_pathfinding.py

Responsibilities:
- route generation
- room connectivity
- outdoor navigation
- multi-building paths

---

# TRANSFORMS

Authoritative:
- transforms.py

Responsibilities:
- local/world conversion
- rotation
- footprint projection
- anchor projection

No other system should implement rotation math.

---

# ANCHORS

Authoritative:
- anchors.py

Responsibilities:
- runtime anchor projection
- anchor positioning
- interaction points

Anchors are:
- local-space in templates
- world-space at runtime

---

# OCCUPANCY

Authoritative:
- occupancy.py

Responsibilities:
- reservations
- queues
- occupancy release
- interaction ownership

---

# AFFORDANCES

Authoritative:
- affordances.py

Responsibilities:
- capability discovery
- interaction filtering
- usable props

---

# HOUSEHOLDS

Authoritative:
- households.py
- household_resources.py

Responsibilities:
- shared resources
- bills
- upkeep
- domestic economy

---

# OFFGRID

Authoritative:
- offgrid.py

Responsibilities:
- work abstraction
- shopping abstraction
- commuting abstraction

---

# DEPRECATED SYSTEMS

These should gradually disappear.

- intention.py
- intentions.py
- activity_runtime.py
- planner.py heuristic planning
- schedule.py legacy intentions

Do NOT delete immediately.
Migrate gradually.