import json
with open(r'c:\Users\DELL\Documents\anti web\assassin-bot\assassin_strategy\oos_validated_85pct_config.json') as f:
    cfg = json.load(f)
print(f'Total setups: {len(cfg)}')
types = set(s["type"] for s in cfg)
print(f'Types: {types}')
vols = set(s["params"].get("min_vol", "MISSING") for s in cfg)
print(f'min_vol values: {vols}')
trends = set(s["params"].get("trend","") for s in cfg)
print(f'Trends: {trends}')
print()
for s in cfg[:5]:
    print(f'{s["pair"]} TF:{s["tf"]} {s["type"]} WR:{s["wr"]}% | params: {s["params"]}')
