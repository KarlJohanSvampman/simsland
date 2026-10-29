import db
w=db.load_world('default'); cal=w['calendar']
print(f"{cal['weekday']} {cal['hour']:02d}:{cal['minute']:02d} tick {w['tick']}")
for c in w['characters'].values():
    if c['age']<18:
        print(f"  {c['name'].split()[0]:<6}{c['age']:>3} act={(c.get('activity') or {}).get('type')!s:<10} off_grid={c.get('off_grid')!s:<5} reason={c.get('off_grid_reason')!s:<8} school_day={c.get('_school_day')} return_in={(c.get('return_tick') or 0) - w['tick'] if c.get('off_grid') else '-'}")
for c in w['characters'].values():
    if c['age']>=18:
        e=(c.get('expectations') or {}).get('get_kids_to_school')
        if e: print(f"  parent {c['name'].split()[0]:<6} get_kids_to_school={ {k:e.get(k) for k in ('status','last_satisfied_tick')} } act={(c.get('activity') or {}).get('type')} off={c.get('off_grid')} {c.get('off_grid_reason')}")
