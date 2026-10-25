"""
systems/age_rules.py -- what is age-appropriate when a character is generated.

Used by systems/character_gen.py so a child is not given a job, an adult hobby, an adult problem or an adult body quirk,
and so schooling follows the child's age:

  school        grade = age - 5 (age 6 = 1st grade, 17 = 12th). Ages 3-5 attend preschool/kindergarten (grade 0 at 5);
                grades 1-5 primary, 6-8 middle school, 9-12 high school. Under 3, no school. Specialist schools are never
                handed out at random.
  education     the highest level COMPLETED: nothing yet below 6, preschool for grades 1-5, primary for grades 6-8,
                middle school for grades 9-12 (adults: as before, from character_gen).
  jobs          none under 18 (character_gen).
  hobbies       each hobby has a minimum age (HOBBY_MIN_AGE; an entry's own `min_age` in hobby_templates wins if the
                definitions carry one). Gambling is 18+, shooting and hunting 16+, and so on; little children get the
                simple ones (drawing, football, board games, picture books).
  problems      children get only the mild ones (KID_PROBLEMS).
  body quirks   sexual or adult-only entries of abnormal_traits_registry are not for under-18s (ADULT_ONLY_ABNORMAL).
  fetishes      none under 18.
"""

ADULT_AGE = 18

# ---- school ---------------------------------------------------------------------------------------------------------------

GRADE_LABELS = {0: "kindergarten", 1: "1st grade", 2: "2nd grade", 3: "3rd grade"}


def grade_label(grade):
    if grade in GRADE_LABELS:
        return GRADE_LABELS[grade]
    return f"{grade}th grade"


def school_placement(age):
    """(education_level, grade) a child of this age is in, or (None, None) when not of school age. Grade 0 is kindergarten
    (age 5, at a preschool template); under 3 there is no school; 18+ is not handled here."""
    if age is None or age < 3 or age >= ADULT_AGE:
        return None, None
    if age < 6:
        return "preschool", (0 if age == 5 else None)
    grade = age - 5
    if grade <= 5:
        return "primary", grade
    if grade <= 8:
        return "middle_school", grade
    return "high_school", grade


def attained_education(age):
    """Highest level completed by a child of this age (None for adults: character_gen rolls those)."""
    if age >= ADULT_AGE:
        return None
    level, grade = school_placement(age)
    if level in (None, "preschool"):
        return "none"
    return {"primary": "preschool", "middle_school": "primary", "high_school": "middle_school"}[level]


def is_specialist_school(school_id, school):
    """A specialist school (for pupils who need it) is placed deliberately, never at random."""
    return "special_ed" in (school_id or "") or "specialist" in str((school or {}).get("name", "")).lower()


def pick_school_ids(schools, age):
    """Ids of the general schools a child of this age can attend (right level, age within the school's range)."""
    level, _ = school_placement(age)
    if level is None:
        return []
    return [k for k, s in (schools or {}).items()
            if s.get("education_level") == level and not is_specialist_school(k, s)
            and (s.get("age_range") or [0, 99])[0] <= age <= (s.get("age_range") or [0, 99])[1]]


# ---- hobbies --------------------------------------------------------------------------------------------------------------

HOBBY_MIN_AGE = {
    # art
    "painting": 4, "photography": 8, "graffiti_street_art": 13, "art_museums": 6, "art_festivals": 8,
    # music
    "guitar": 7, "piano": 5, "drums": 6, "violin": 5, "bass_guitar": 10, "singing_karaoke": 6, "music_events": 14,
    "music_festivals": 16, "trumpet": 8, "saxophone": 10, "flute": 6,
    # performing arts, film
    "theater": 6, "opera": 14, "movies": 5, "movie_making": 10, "podcasts": 12,
    # nature
    "hiking": 6, "camping": 8, "fishing": 6, "hunting": 16, "wildlife_photography": 10, "gardening": 5, "astronomy": 7,
    "mountain_climbing": 12,
    # exercise
    "weightlifting": 15, "crossfit": 16, "running": 6, "cycling": 5, "swimming": 4, "yoga": 8, "dance_fitness": 8,
    "martial_arts": 6,
    # collections
    "coin_collecting": 6, "stamp_collecting": 6, "trading_cards": 6, "comic_books": 6, "books": 5, "vinyl_records": 12,
    "video_game_collecting": 10, "action_figures": 4, "model_trains": 6,
    # sports
    "golf": 8, "ice_hockey": 6, "boxing": 12, "fencing": 8, "archery": 8, "snowboarding": 8, "surfing": 8,
    "shooting_sports": 16, "bowling": 5, "football_soccer": 4, "american_football": 7, "baseball": 5, "basketball": 5,
    "volleyball": 8, "tennis": 5, "horseback_riding": 6, "football_supporter": 6, "basketball_supporter": 6,
    "hockey_supporter": 6, "soccer_supporter": 6,
    # history
    "historical_reenactment": 10, "archaeology": 8, "museum_visits": 6, "historical_research": 14,
    "historical_writing": 14, "reading_biographies": 10,
    # gambling: adults only
    "poker": 18, "blackjack": 18, "roulette": 18, "slot_machines": 18, "sports_betting": 18, "horse_racing_betting": 18,
    "lottery": 18, "bingo": 18,
    # games
    "video_games": 5, "boardgames": 4, "pictionary": 5, "quiz_games": 6, "esports": 10,
    # culinary, literary
    "cooking": 7, "baking": 5, "reading": 5, "book_club": 12, "keep_a_diary": 8,
}
CATEGORY_MIN_AGE = {"gambling": 18}                  # for a hobby the table above does not name
DEFAULT_MIN_AGE = 12                                 # an unknown hobby is not for little children


def hobby_min_age(hobby_id, hobby_def=None):
    own = (hobby_def or {}).get("min_age")
    if own is not None:
        return own
    if hobby_id in HOBBY_MIN_AGE:
        return HOBBY_MIN_AGE[hobby_id]
    return CATEGORY_MIN_AGE.get((hobby_def or {}).get("category"), DEFAULT_MIN_AGE)


def hobby_ok(hobby_id, age, hobby_def=None):
    if age is None:
        return True
    return age >= hobby_min_age(hobby_id, hobby_def) and age <= ((hobby_def or {}).get("max_age") or 200)


def appropriate_hobbies(pool, age):
    """The ids in `pool` (a hobby_templates dict, or an iterable of ids) fit for someone of this age."""
    templates = pool if isinstance(pool, dict) else {}
    ids = [k for k in pool if not str(k).startswith("_")]
    return [k for k in ids if hobby_ok(k, age, templates.get(k) if isinstance(templates.get(k), dict) else None)]


# ---- problems, body quirks, fetishes -----------------------------------------------------------------------------------

KID_PROBLEMS = {"aggressive", "manipulative", "pathological_liar", "self_destructive_fearless", "self_destructive_careless",
                "extremely_unsanitary", "kleptomania"}
ADULT_ONLY_ABNORMAL = {"giant_penis", "micro_penis", "hyperactive_libido", "asexual"}


def problems_pool(registry, age):
    return [p for p in registry if age is None or age >= ADULT_AGE or p in KID_PROBLEMS]


def abnormal_pool(registry, age):
    return [a for a in registry if age is None or age >= ADULT_AGE or a not in ADULT_ONLY_ABNORMAL]
