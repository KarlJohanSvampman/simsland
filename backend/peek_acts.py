import db
w = db.load_world('default')
cal = w['calendar']
print(cal['weekday'], cal['hour'], cal['minute'], 'tick', w['tick'])
n = 0
for c in w['characters'].values():
    recs = [m for m in (c.get('short_term_memory') or c.get('memories') or []) if m.get('kind') == 'activity']
    old = [m for m in (c.get('short_term_memory') or c.get('memories') or []) if m.get('kind') == 'debug_event' and 'Activity' in m.get('text', '') and m.get('tick', 0) > w['tick'] - 1800]
    a = c.get('activity') or {}
    print(c['name'].split()[0], '| now:', a.get('type'), a.get('phase'), '| posture', c.get('posture'), '| records', len(recs), '| new debug lines', len(old))
    for m in recs[-3:]:
        print('    ', m['text'])
        n += 1
print('total shown', n)
