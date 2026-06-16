import random
from datetime import datetime

WEEKDAYS = [
    "monday","tuesday","wednesday","thursday",
    "friday","saturday","sunday"
]


def generate_week_schedule(c, world):

    schedule = {"week": {}, "last_generated": world["calendar"]["timestamp"]}

    wage = c.get("hourly_wage", 10)
    ambition = 1.2 if "ambitious" in c.get("traits", []) else 1.0
    laziness = 0.8 if "lazy" in c.get("traits", []) else 1.0

    # 🧠 compute target work hours
    base_hours = 40

    if wage < 10:
        base_hours += 10
    elif wage > 25:
        base_hours -= 10

    base_hours *= ambition
    base_hours *= laziness

    weekly_hours = max(10, int(base_hours))

    hours_per_day = weekly_hours // 5

    for day in WEEKDAYS:

        day_plan = []

        # 🛌 sleep
        day_plan.append({
            "start": "23:00",
            "end": "07:00",
            "activity": "sleep"
        })

        # 💼 work weekdays only
        if day in WEEKDAYS[:5]:
            start_hour = random.choice([8, 9, 10])

            day_plan.append({
                "start": f"{start_hour:02d}:00",
                "end": f"{start_hour + hours_per_day:02d}:00",
                "activity": "work"
            })

        # 🍽️ meals
        day_plan.append({"start": "12:00", "end": "13:00", "activity": "eat"})
        day_plan.append({"start": "18:00", "end": "19:00", "activity": "eat"})

        # 🧘 leisure
        day_plan.append({"start": "19:00", "end": "22:00", "activity": "relax"})

        schedule["week"][day] = day_plan

    return schedule

def adjust_for_household(c, world):

    hid = c.get("household_id")
    if not hid:
        return

    members = [
        x for x in world["characters"].values()
        if x.get("household_id") == hid
    ]

    # stagger work start times
    offset = members.index(c) % 2

    for day, blocks in c["schedule"]["week"].items():
        for b in blocks:
            if b["activity"] == "work":
                hour = int(b["start"][:2])
                hour += offset
                b["start"] = f"{hour:02d}:00"

def get_current_activity(c, world):

    cal = world["calendar"]

    day = cal["weekday"].lower()
    time_str = f"{cal['hour']:02d}:{cal['minute']:02d}"

    schedule = c.get("schedule", {}).get("week", {})
    day_plan = schedule.get(day, [])

    for block in day_plan:
        if block["start"] <= time_str <= block["end"]:
            return block["activity"]

    return None