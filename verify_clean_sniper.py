import json, re

clean = json.load(open('assassin_strategy/nogale_sniper_clean_config.json'))

with open('full_deploy_trades.txt', 'r', encoding='utf-8') as f:
    lines = [l.strip() for l in f.readlines()]

trades = []
for l in lines:
    if 'TAKE_IT' in l:
        parts = l.split('|')
        ts = l[:20]
        m = re.search(r'\[(\d+)\]\s+([A-Z0-9]+)\s+(CALL|PUT)', parts[0])
        if m:
            tf = int(m.group(1))
            sym = m.group(2)
            dr = m.group(3)
            setup = parts[5].strip() if len(parts) > 5 else ''
            trades.append({'entry_time': ts, 'tf': tf, 'sym': sym, 'dr': dr, 'setup': setup})

for t in trades:
    sym = t['sym']
    dr = t['dr']
    t_time = t['entry_time']
    t['outcome'] = 'UNKNOWN'
    for l in lines:
        if '[BG-SETTLER]' in l and sym in l and dr in l:
            if l[:20] >= t_time:
                t['outcome'] = 'WIN' if 'WIN' in l else 'LOSS'
                break

oct22_23 = [t for t in trades if t['outcome'] in ('WIN', 'LOSS')]

clean_trades = []
for t in oct22_23:
    if 'WILLR' in t['setup']: continue
    if '_BB' not in t['setup']: continue
    try:
        bb = float(t['setup'].split('_BB')[-1].split()[0])
        if bb >= 2.0:
            clean_trades.append(t)
    except:
        pass

wins = sum(1 for t in clean_trades if t['outcome'] == 'WIN')
losses = len(clean_trades) - wins
print(f"Matched Sniper Clean Trades: {wins}W - {losses}L ({wins/len(clean_trades)*100:.1f}%) [Total: {len(clean_trades)}]")
for t in clean_trades:
    print(f"  {t['entry_time']} | {t['sym']} {t['dr']} {t['tf']}m | {t['outcome']} | {t['setup']}")
