# Food system redesign (design, not yet built)

Goal: simpler than today's two parallel systems (abstract `FOOD_*` counts + physical items), but detailed enough that
characters develop tastes, habits and bodies from what they eat.

## 1. Ingredients (physical items)

Categories: `carb`, `protein`, `vegetable`, `dairy`, `fruit`, `bread`, `none` (chips, cereal, takeout and other ready-made).
Every ingredient has `category`, `calories`, `fat_pct`, `price`.

* Eaten as they are: **fruit** and **bread** only.
* Everything else is an ingredient for cooking.
* **Spices** are a separate kind of ingredient: they add taste only, no nutrition worth counting.

## 2. Recipes are ratios

A recipe is a ratio of `protein : carb : vitamins (fruit + vegetable)` plus `spice`.

1. The character picks a recipe and a number of people it is for.
2. Units needed per category = ratio x people. That is taken from the fridge / pantry stacks.
3. Spices do nothing for nutrition. They raise taste, capped.
4. **Dairy** counts as a protein-like extra (it can fill part of the protein share). **Bread** is never in a pot, pan or
   oven recipe; it only goes into sandwiches or is eaten as it is.

## 3. Cookware: pot, pan, oven (one mechanism)

Each has a built-in inventory.

1. **Load** ingredients (not allowed while it still has charges).
2. Choose to **begin cooking**. It takes a realistic time by recipe and cookware (pan ~10 min, pot ~15, oven 60-90).
   Nobody has to stand there.
3. When done the cookware holds **charges** (= portions) and a stored result: dish name, per-portion calories, fat %,
   health, taste, ingredients.
4. Someone takes a **plate**; that creates the plated dish item (one portion, the "ready dish") and the cookware loses one
   charge. At 0 charges the cookware is empty and dirty.
5. When a sim finishes eating, the plated dish is gone and what remains is a **dirty dish item** (a real item, left at the
   table). This replaces the household-wide counter in `systems/chores.py::add_dirty_dishes`, which `body.py` calls on every
   finished food item today; washing up then deals with the actual items.

**Sandwich:** a bread item on a counter has an inventory. Ingredients go in and the contents become a sandwich. One
portion, no cooking time.

### Serving window, plates, leftovers

* When cooking finishes the food stays **served for 1-2 hours** (random per dish). The cook gets a reminder to find out
  whether the others are home and, if so, go and tell them dinner is served.
* Carbs are often cooked or fried separately, so a plate need not follow the intended ratio. The eater can take **more meat or
  fewer carbs**, driven by personal **weaknesses to fat, calories and meat** (per character). The portion's calories stay
  about the same; the mix on the plate shifts, and health / taste are scored on the mix actually eaten.
* After the window ends, the cook returns and deals with the dishes, **unless** a social contract says one cooks and another
  does the dishes. Leftovers are either put in a **container** and stored in the fridge, or **thrown in the trash**.

## 4. Scoring a ready dish

* `health` 0..1 (unhealthy -> nutritional): rewards a spread of categories, vegetables and fruit most; penalises high
  fat % and high calorie density.
* `taste` falls as health rises (simplifying assumption): roughly `taste = 1 - 0.6 * health^2`, plus spice bonus (capped).
* `addictive` rises as health falls: roughly `(1 - health)^2`.
* Honest reactions: low health -> "great", medium -> "good / great", very nutritional -> "bland / not good". Characters
  never lie about it.
* Ready-made / processed items are scored the same way, which is why they land low on health and high on taste.

## 5. Calories and fat drive weight

`calories_today` and `fat_cal_today` replace `nutrients_today`. `settle_nutrition_day` compares calories with each
character's daily need (age, sex, height, weight, activity). About 7700 kcal surplus/deficit = 1 kg. Fat share above
~35% nudges weight up further. Hunger and energy gained come from calories. BMI bands, traits, diseases, hazards and toilet
load stay as they are.

## 6. Taste development

A liking per ingredient (-1..1) that drifts up when eaten and the character feels fine; a dish is judged by its
ingredients, with a weak bias per category.

## 7. Shopping

* Every ingredient has a price.
* A trip has a ratio and a total number of units to spend (a budget).
* They choose a recipe when they plan the trip; the plan goes on their **schedule with the recipe attached**.
* Stores also sell **processed food**: the same as takeout, complete ready-to-warm dishes, cheaper and lower health.
  Each instance carries `temperature: cold | warm`; cold ones need the microwave.

## 8. Habits and the dinner rota

* At dinner time the choice between cooking, processed food and takeout depends on current stress and the week's average
  stress.
* In the social contract, a household can propose a dinner rota ("I cook Monday, Wednesday and Friday", or "we take
  turns, one day each").

## Build status

**Phases 1 and 2 are built** (tests: `test_food_scoring.py`, `test_cookware.py`, `test_food_flow.py`).

* `data/ingredients.py` -- the ingredient items (group, calories, fat share of calories, price); merged into `ITEM_TEMPLATES`.
* `data/dishes.py` -- recipes as ratios per person, with cookware and cooking time.
* `systems/food_scoring.py` -- health / taste / addictive, the honest reaction word, the plate a person actually takes
  (`plate_from_dish`, shifted by their weaknesses).
* `systems/cookware.py` -- the household's pot, pan and oven (`household["cookware"]`): load from stock, begin, finish on a
  clock, charges, plates, the 1-2 hour serving window, announcement, close-out (leftovers or bin), washing.
* The household's food is still `household["storage"]["resources"]`, but each stack now names its ingredient
  (`template_id`); the `FOOD_*` resource types remain for the older code. Added `FOOD_DAIRY` and `FOOD_BREAD`.
* `systems/eating.py` -- a meal is a named item, else a plate of what is served (then leftovers), else a ready-to-eat stack;
  `weakness_of(c)` gives each person fixed weaknesses for meat, fat and a big helping.
* `body.on_consume_complete` -- items with calories fill hunger by about 1 point per 8 kcal, add to `calories_today` /
  `fat_cal_today`; `nutrition.settle_nutrition_day` turns the day's calories against the person's own need
  (`daily_kcal_need`) into kilos (7700 kcal each, capped at 0.3 kg a day, fat above 35% of calories weighs a little more).

**Interim, to revisit:** the dirty dishes are still the household counter (`dirty_dishes`), not item objects; a dish is
dirty because it was served, not tracked per plate. `household["dish_duty"]` (a member id) is read for who washes up and is
ready for the social-contract rota to set.

## Build order (remaining)

3. Taste affinity per ingredient and stress-based dinner habits (cook, processed food, takeout).
4. Shopping by ratio and budget; the chosen recipe on the schedule.
5. Processed food with cold / warm and the microwave.
6. Dinner rota proposals in the social contract (sets `dish_duty` and who cooks which day).
7. Dirty plates as real items; showing the cooking / served state in the front end.
