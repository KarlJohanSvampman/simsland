import db
w=db.load_world('default'); cal=w['calendar']; print(cal['weekday'],cal['hour'],cal['minute'])
for c in w['characters'].values():
    if c.get('off_grid'):
        d=c.get('off_grid_detail') or {}
        print(c['name'].split()[0], c['off_grid_reason'], '|', d.get('started_clock'), '->', d.get('returns_clock'), '|', d.get('where'), '|', d.get('why'))
