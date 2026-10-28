import sys, re

sys.stdout.reconfigure(encoding='utf-8')

with open('full_deploy_trades.txt', 'r', encoding='utf-8') as f:
    lines = [l.strip() for l in f.readlines()]

trades = []
current_entry = None

# Pattern:
# [2026-10-23T17:40:00] 2026-10-23 17:40:00,136 [CRITICAL] AssassinBot: 🔥 [10] BNBUSDT CALL | $745.77 | TAKE_IT (82%) | Solid=3 Soft=0 | Regime=HYBRID_85PCT | BNB 10m HTF_30m_EMA20_RSI2_10.0_BB1.5 | 30mBull(C>745.9) | RSI2=8.6<=10.0 | BBz=-1.95<=-1.5 | Vol=1.8

for l in lines:
    if 'TAKE_IT' in l:
        # e.g. [2026-10-23T17:40:00] ... [10] BNBUSDT CALL | $745.77 | TAKE_IT (82%) | Solid=3 Soft=0 | Regime=HYBRID_85PCT | BNB 10m HTF_30m_EMA20_RSI2_10.0_BB1.5 | 30mBull(C>745.9) | RSI2=8.6<=10.0 | BBz=-1.95<=-1.5 | Vol=1.8
        parts = l.split('|')
        ts = l[:20]
        # find symbol and direction
        m = re.search(r'\[(\d+)\]\s+([A-Z0-9]+)\s+(CALL|PUT)', parts[0])
        if m:
            tf = m.group(1)
            sym = m.group(2)
            dr = m.group(3)
            price = parts[1].strip() if len(parts) > 1 else ''
            regime = parts[4].strip() if len(parts) > 4 else ''
            setup = parts[5].strip() if len(parts) > 5 else ''
            extra = '|'.join(parts[6:]).strip() if len(parts) > 6 else ''
            trades.append({
                'entry_time': ts,
                'tf': tf,
                'symbol': sym,
                'direction': dr,
                'price': price,
                'setup': setup,
                'extra': extra
            })

# Now match each trade with its settlement
for t in trades:
    sym = t.get('symbol', '')
    dr = t.get('direction', '')
    t_time = t.get('entry_time', '')
    t['outcome'] = 'PENDING'
    t['settle_time'] = ''
    t['profit_loss'] = ''
    for l in lines:
        if '[BG-SETTLER]' in l:
            # check if same symbol and direction and happened after entry_time
            if sym in l and dr in l:
                # check time
                s_time = l[:20]
                if s_time >= t_time:
                    outcome = 'WIN' if 'WIN' in l else 'LOSS'
                    t['outcome'] = outcome
                    t['settle_time'] = s_time
                    t['profit_loss'] = l.split('[BG-SETTLER]')[1].strip()
                    break

print("MATCHED TRADES:")
print(f"{'ENTRY TIME':20s} | {'SYM':8s} {'DIR':4s} {'TF':3s} | {'RES':4s} | {'SETUP':35s} | DETAILS")
print("-" * 120)
for t in trades:
    print(f"{t.get('entry_time',''):20s} | {t.get('symbol',''):8s} {t.get('direction',''):4s} {t.get('tf',''):3s} | {t.get('outcome',''):4s} | {t.get('setup',''):35s} | {t.get('extra','')}")
