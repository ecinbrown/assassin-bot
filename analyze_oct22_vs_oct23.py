import sys
from collections import defaultdict

sys.stdout.reconfigure(encoding='utf-8')

with open('full_deploy_trades.txt', 'r', encoding='utf-8') as f:
    lines = [l.strip() for l in f.readlines()]

settlements = [l for l in lines if '[BG-SETTLER]' in l]

stats = {
    '2026-10-22': defaultdict(lambda: {'W': 0, 'L': 0}),
    '2026-10-23': defaultdict(lambda: {'W': 0, 'L': 0})
}

dir_stats = {
    '2026-10-22': defaultdict(lambda: {'W': 0, 'L': 0}),
    '2026-10-23': defaultdict(lambda: {'W': 0, 'L': 0})
}

trade_details = {'2026-10-22': [], '2026-10-23': []}

for s in settlements:
    day = '2026-10-22' if '2026-10-22' in s else '2026-10-23'
    result = 'W' if 'WIN' in s else 'L'
    parts = s.split('[BG-SETTLER]')[1].strip().split()
    outcome = parts[0]
    symbol = parts[1]
    direction = parts[2]
    stats[day][symbol][result] += 1
    dir_stats[day][direction][result] += 1
    trade_details[day].append((s[:30], symbol, direction, outcome, s))

print('=====================================================')
print('        OCT 22 vs OCT 23 (TODAY) DETAILED AUDIT      ')
print('=====================================================')

for day in ['2026-10-22', '2026-10-23']:
    print(f"\n--- {day} ---")
    tot_w = sum(d['W'] for d in stats[day].values())
    tot_l = sum(d['L'] for d in stats[day].values())
    total = tot_w + tot_l
    wr = tot_w / total * 100 if total else 0
    print(f"Overall: {tot_w}W - {tot_l}L | Win Rate: {wr:.1f}% ({total} trades)")
    
    print("\nBy Symbol:")
    for sym, d in sorted(stats[day].items()):
        t = d['W'] + d['L']
        r = d['W'] / t * 100 if t else 0
        print(f"  {sym:8s}: {d['W']}W - {d['L']}L ({r:.1f}%) [Total: {t}]")

    print("\nBy Direction:")
    for dr, d in sorted(dir_stats[day].items()):
        t = d['W'] + d['L']
        r = d['W'] / t * 100 if t else 0
        print(f"  {dr:5s}: {d['W']}W - {d['L']}L ({r:.1f}%) [Total: {t}]")

print('\n=====================================================')
print('                OCT 23 LOSS ANALYSIS                 ')
print('=====================================================')
for ts, sym, dr, outcome, raw in trade_details['2026-10-23']:
    if outcome == 'LOSS':
        print(f"LOSS: {ts} | {sym:8s} {dr:4s} | {raw}")
