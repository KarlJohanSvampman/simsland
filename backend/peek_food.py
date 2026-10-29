import db
w = db.load_world('default')
cal = w['calendar']
print(cal['weekday'], cal['hour'], cal['minute'], 'tick', w['tick'])
for hid, h in w['households'].items():
    ck = h.get('cookware') or []
    st = [(r.get('template_id') or r['resource_type'], r['quantity']) for r in h.get('storage', {}).get('resources', []) if str(r.get('resource_type','')).startswith('FOOD_')]
    print(hid, 'members', len(h.get('members', [])), 'stock', st[:8], 'dirty', h.get('dirty_dishes'))
    for v in ck:
        print('   ', v['kind'], v['state'], v.get('recipe_id'), 'charges', v.get('charges'))
for c in w['characters'].values():
    a = c.get('activity') or {}
    if a.get('type') in ('cook_recipe', 'eat', 'eat_meal', 'eat_snack') or c.get('last_meal'):
        print(c['name'].split()[0], a.get('type'), a.get('phase'), c.get('last_meal'))
