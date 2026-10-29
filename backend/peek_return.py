import db
w=db.load_world('default'); cal=w['calendar']
print(f"{cal['weekday']} {cal['hour']:02d}:{cal['minute']:02d} tick {w['tick']}")
for c in w['characters'].values():
    if c['age']<18:
        arc=c.get('off_grid_story_arc') or []
        st=arc[-1] if arc else {}
        b=c.get('body') or {}
        print(f"  {c['name'].split()[0]:<6}{c['age']:>3} act={(c.get('activity') or {}).get('type')!s:<9} off={c.get('off_grid')!s:<5} {c.get('off_grid_reason')!s:<7} fatigue={b.get('fatigue',0):.0f} energy={b.get('energy',0):.0f} bld={c.get('building_id')} story={st.get('summary')!r} tags={st.get('tags')} private={'private' in st}")
