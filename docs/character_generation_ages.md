# Age-appropriate generation (`systems/age_rules.py`, used by `systems/character_gen.py`)

- **Jobs.** Nobody under 18 has a job, is employed, or is `job_searching`; a `job` supplied by a template or override is
  ignored for a minor. Under-18s go to school instead.
- **School and grade.** Grade = age - 5: age 5 kindergarten (a preschool template), grades 1-5 primary (ages 6-10), 6-8
  middle school (11-13), 9-12 high school (14-17); ages 3-4 preschool without a grade; under 3 none. A general school of the
  right `education_level` whose `age_range` fits is picked (the specialist school, Oakdale, never at random). `school_grade`
  is stored on the character and the prompt says "You are in 4th grade at Riverside Primary School." Brothers and sisters go
  to the same school 85% of the time when it takes their age.
- **Education** of a child is what they have *completed*: none below 6, preschool in grades 1-5, primary in 6-8, middle school
  in 9-12 (adults unchanged).
- **Hobbies.** Every hobby has a minimum age (`HOBBY_MIN_AGE`; a hobby entry's own `min_age`/`max_age` in the definitions wins).
  Gambling is 18+, hunting/shooting 16+, etc. Applied to random picks, hobbies inherited through relative generation and
  hobbies from templates (the disallowed ones are dropped; if none are left an appropriate one is picked). Under 6 gets one
  hobby, and a three-year-old may have none.
- **Problems, body quirks, fetishes.** Children get only mild problems (aggressive, manipulative, pathological liar,
  self-destructive, unsanitary, kleptomania), none of the sexual/adult entries of `abnormal_traits_registry`, and no fetishes.
- **Adding a house.** `POST /admin/add_building {template, x, y, address?}` places another building of a floorplan template
  (footprint must fit and not overlap), builds its geometry and furniture, and saves. The World Editor's save rejects the whole
  world over clearance violations in the existing houses, so use this instead.

Tests: `tests/test_character_age_rules.py` (1056 generated characters, ages 3-90, checked against the real definitions).
