import re, sys
sys.stdout.reconfigure(encoding='utf-8')

files = ['all_trade_events.txt', 'trades_oct3_to_now.txt', 'trade_full_results.txt']
all_lines = []
seen = set()
for f in files:
    try:
        for line in open(f, 'r', encoding='utf-8'):
            line = line.strip()
            if line and line not in seen:
                seen.add(line)
                all_lines.append(line)
    except:
        pass

wins = []
losses = []
for line in all_lines:
    if '[BG-SETTLER] WIN' in line:
        m = re.search(r'WIN (\w+) (\w+) (\w+).*Profit: ([+\-\d.]+).*Bal: ([\d.]+)', line)
        if m:
            wins.append(dict(sym=m.group(1), action=m.group(2), profit=float(m.group(4)), bal=float(m.group(5))))
    elif '[BG-SETTLER]' in line and ('LOSS' in line or 'Lost' in line):
        m = re.search(r'(?:SEQ )?LOSS (\w+) (\w+).*Lost: ([\d.]+)', line)
        if m:
            losses.append(dict(sym=m.group(1), action=m.group(2), lost=float(m.group(3))))

total = len(wins) + len(losses)
print("=== FULL TRADE TALLY (All Saved Logs) ===")
print(f"Total Trades: {total}")
print(f"Wins:   {len(wins)}")
print(f"Losses: {len(losses)}")
if total > 0:
    print(f"Win Rate: {len(wins)/total*100:.1f}%")
print()

print("--- WINS ---")
for w in wins:
    print(f"  {w['sym']} {w['action']} | Profit: {w['profit']:+.4f} | Bal: {w['bal']:.4f}")
print()
print("--- LOSSES ---")
for l in losses:
    print(f"  {l['sym']} {l['action']} | Lost: {l['lost']:.4f}")
print()

from collections import Counter
pair_w = Counter(w['sym'] for w in wins)
pair_l = Counter(l['sym'] for l in losses)
all_pairs = set(list(pair_w.keys()) + list(pair_l.keys()))
print("--- BY PAIR ---")
for p in sorted(all_pairs):
    pw = pair_w.get(p, 0)
    pl = pair_l.get(p, 0)
    pt = pw + pl
    wr = pw / pt * 100 if pt else 0
    print(f"  {p}: {pw}W / {pl}L = {wr:.0f}% WR ({pt} trades)")

print()
total_profit = sum(w['profit'] for w in wins)
total_lost = sum(l['lost'] for l in losses)
print(f"--- P&L ---")
print(f"Total Won:  +{total_profit:.4f}")
print(f"Total Lost: -{total_lost:.4f}")
print(f"Net P&L:    {total_profit - total_lost:+.4f}")
if wins:
    print(f"Final Balance (last win): {wins[-1]['bal']:.4f}")
