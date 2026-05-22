"""
OPUS JUICE EXTRACTOR — Maximum Edge Discovery
================================================
Multi-dimensional tick analysis combining:
1. Terminal velocity (last N seconds)
2. Tick density anomalies (ticks/sec spikes)
3. Price acceleration curves
4. Candle body-to-range ratio
5. Multi-candle momentum sequences
6. Micro-structure: bid clustering
7. Combined filter stacking (AND logic)
ALL SYMBOLS tested.
"""
import sqlite3
import pandas as pd
import numpy as np
from collections import defaultdict

def juice_it():
    conn = sqlite3.connect("trading_data.db")
    symbols = pd.read_sql_query("SELECT DISTINCT symbol FROM ticks", conn)['symbol'].tolist()
    print(f"Symbols: {symbols}")
    
    for symbol in symbols:
        print(f"\n{'='*80}")
        print(f" JUICING: {symbol}")
        print(f"{'='*80}")
        
        df = pd.read_sql_query(
            f"SELECT timestamp, price FROM ticks WHERE symbol='{symbol}' AND timestamp > 0 ORDER BY timestamp ASC", 
            conn
        )
        if len(df) < 1000:
            print(f"  Skipping, only {len(df)} ticks.")
            continue
            
        print(f"  Ticks: {len(df)}")
        
        # === BUILD MINUTE CANDLES WITH TICK MICROSTRUCTURE ===
        df['minute_ts'] = (df['timestamp'] // 60) * 60
        minutes = df.groupby('minute_ts')
        
        candle_data = []
        for minute, ticks in minutes:
            if len(ticks) < 5: continue
            ticks = ticks.sort_values('timestamp')
            prices = ticks['price'].values
            times = ticks['timestamp'].values
            
            o, h, l, c = prices[0], prices.max(), prices.min(), prices[-1]
            body = c - o
            rng = h - l
            if rng == 0: rng = 0.00001
            
            # Tick density
            duration = times[-1] - times[0]
            if duration == 0: duration = 1
            tick_density = len(ticks) / duration
            
            # Last 3 seconds
            t3_mask = times >= (times[-1] - 3.0)
            t3_prices = prices[t3_mask]
            t3_move = t3_prices[-1] - t3_prices[0] if len(t3_prices) >= 2 else 0
            t3_ticks = len(t3_prices)
            
            # Last 5 seconds
            t5_mask = times >= (times[-1] - 5.0)
            t5_prices = prices[t5_mask]
            t5_move = t5_prices[-1] - t5_prices[0] if len(t5_prices) >= 2 else 0
            t5_ticks = len(t5_prices)
            
            # Last 10 seconds
            t10_mask = times >= (times[-1] - 10.0)
            t10_prices = prices[t10_mask]
            t10_move = t10_prices[-1] - t10_prices[0] if len(t10_prices) >= 2 else 0
            t10_ticks = len(t10_prices)
            
            # First 10 seconds
            f10_mask = times <= (times[0] + 10.0)
            f10_prices = prices[f10_mask]
            f10_move = f10_prices[-1] - f10_prices[0] if len(f10_prices) >= 2 else 0
            
            # Tick-to-tick diffs
            diffs = np.diff(prices)
            pos_ticks = (diffs > 0).sum()
            neg_ticks = (diffs < 0).sum()
            zero_ticks = (diffs == 0).sum()
            
            # Straight-line detection (all diffs same sign in last 3s)
            t3_diffs = np.diff(t3_prices) if len(t3_prices) >= 3 else np.array([])
            straight_up_3 = len(t3_diffs) >= 3 and (t3_diffs > 0).all()
            straight_down_3 = len(t3_diffs) >= 3 and (t3_diffs < 0).all()
            
            # Body ratio (how much of range is body)
            body_ratio = abs(body) / rng
            
            # Upper/Lower wick
            upper_wick = h - max(o, c)
            lower_wick = min(o, c) - l
            
            # Acceleration: is last 5s faster than first 10s?
            t5_speed = abs(t5_move) / max(t5_ticks, 1)
            f10_speed = abs(f10_move) / max(len(f10_prices), 1)
            accel_ratio = t5_speed / max(f10_speed, 0.00001)
            
            candle_data.append({
                'minute': minute,
                'open': o, 'high': h, 'low': l, 'close': c,
                'body': body, 'body_abs': abs(body), 'range': rng,
                'body_ratio': body_ratio,
                'upper_wick': upper_wick, 'lower_wick': lower_wick,
                'tick_count': len(ticks),
                'tick_density': tick_density,
                't3_move': t3_move, 't3_ticks': t3_ticks,
                't5_move': t5_move, 't5_ticks': t5_ticks,
                't10_move': t10_move, 't10_ticks': t10_ticks,
                'f10_move': f10_move,
                'pos_ticks': pos_ticks, 'neg_ticks': neg_ticks,
                'zero_ticks': zero_ticks,
                'straight_up_3': straight_up_3,
                'straight_down_3': straight_down_3,
                'accel_ratio': accel_ratio,
                'diffs_std': np.std(diffs) if len(diffs) > 0 else 0,
            })
        
        cdf = pd.DataFrame(candle_data).sort_values('minute').reset_index(drop=True)
        cdf['next_close'] = cdf['close'].shift(-1)
        cdf['next_dir'] = np.where(cdf['next_close'] > cdf['close'], 1, 0)
        
        # Previous candle features
        cdf['prev_body'] = cdf['body'].shift(1)
        cdf['prev_body_ratio'] = cdf['body_ratio'].shift(1)
        cdf['prev_t5_move'] = cdf['t5_move'].shift(1)
        
        # 3-candle momentum
        cdf['body_3sum'] = cdf['body'].rolling(3).sum()
        
        # Stats for thresholds
        body_mean = cdf['body_abs'].mean()
        body_std = cdf['body_abs'].std()
        t5_mean = cdf['t5_move'].abs().mean()
        t5_std = cdf['t5_move'].abs().std()
        t3_mean = cdf['t3_move'].abs().mean()
        t3_std = cdf['t3_move'].abs().std()
        density_mean = cdf['tick_density'].mean()
        density_std = cdf['tick_density'].std()
        accel_mean = cdf['accel_ratio'].mean()
        accel_std = cdf['accel_ratio'].std()
        
        results = []
        
        # ============================================================
        # DIMENSION 1: Terminal Velocity + Body Ratio combos
        # ============================================================
        for t5m in [1.0, 1.5, 2.0]:
            t5_thresh = t5_mean + t5m * t5_std
            for br_min in [0.7, 0.8, 0.9]:
                # Full-body candle + fast terminal = continuation
                up = (cdf['t5_move'] > t5_thresh) & (cdf['body'] > 0) & (cdf['body_ratio'] >= br_min)
                dn = (cdf['t5_move'] < -t5_thresh) & (cdf['body'] < 0) & (cdf['body_ratio'] >= br_min)
                
                w_up = up.sum() and cdf[up]['next_dir'].sum() or 0
                w_dn = dn.sum() and (len(cdf[dn]) - cdf[dn]['next_dir'].sum()) or 0
                tot = up.sum() + dn.sum()
                if tot >= 8:
                    results.append(("CONT FullBody+T5", f"T5>{t5m} BR>{br_min}", tot, (w_up+w_dn)/tot*100))
                
                # Reversal
                w_up_r = up.sum() and (len(cdf[up]) - cdf[up]['next_dir'].sum()) or 0
                w_dn_r = dn.sum() and cdf[dn]['next_dir'].sum() or 0
                if tot >= 8:
                    results.append(("REV FullBody+T5", f"T5>{t5m} BR>{br_min}", tot, (w_up_r+w_dn_r)/tot*100))
        
        # ============================================================
        # DIMENSION 2: Tick Density Anomaly (algo manipulation)
        # ============================================================
        for dm in [1.0, 1.5, 2.0]:
            d_thresh = density_mean + dm * density_std
            for bm in [1.0, 1.5, 2.0]:
                b_thresh = body_mean + bm * body_std
                
                up = (cdf['tick_density'] > d_thresh) & (cdf['body'] > b_thresh)
                dn = (cdf['tick_density'] > d_thresh) & (cdf['body'] < -b_thresh)
                
                w_cont = (up.sum() and cdf[up]['next_dir'].sum() or 0) + \
                         (dn.sum() and (len(cdf[dn]) - cdf[dn]['next_dir'].sum()) or 0)
                w_rev = (up.sum() and (len(cdf[up]) - cdf[up]['next_dir'].sum()) or 0) + \
                        (dn.sum() and cdf[dn]['next_dir'].sum() or 0)
                tot = up.sum() + dn.sum()
                if tot >= 8:
                    results.append(("CONT Density+Body", f"D>{dm} B>{bm}", tot, w_cont/tot*100))
                    results.append(("REV Density+Body", f"D>{dm} B>{bm}", tot, w_rev/tot*100))
        
        # ============================================================
        # DIMENSION 3: Acceleration Spike (last 5s WAY faster than first 10s)
        # ============================================================
        for am in [1.5, 2.0, 3.0]:
            a_thresh = accel_mean + am * accel_std
            
            up = (cdf['accel_ratio'] > a_thresh) & (cdf['t5_move'] > 0)
            dn = (cdf['accel_ratio'] > a_thresh) & (cdf['t5_move'] < 0)
            
            w_cont = (up.sum() and cdf[up]['next_dir'].sum() or 0) + \
                     (dn.sum() and (len(cdf[dn]) - cdf[dn]['next_dir'].sum()) or 0)
            w_rev = (up.sum() and (len(cdf[up]) - cdf[up]['next_dir'].sum()) or 0) + \
                    (dn.sum() and cdf[dn]['next_dir'].sum() or 0)
            tot = up.sum() + dn.sum()
            if tot >= 8:
                results.append(("CONT Accel", f"A>{am}", tot, w_cont/tot*100))
                results.append(("REV Accel", f"A>{am}", tot, w_rev/tot*100))
        
        # ============================================================
        # DIMENSION 4: Tick imbalance (way more up ticks than down or vice versa)
        # ============================================================
        for imb_thresh in [0.7, 0.75, 0.8, 0.85]:
            total_dir_ticks = cdf['pos_ticks'] + cdf['neg_ticks']
            total_dir_ticks = total_dir_ticks.replace(0, 1)
            
            up_imb = cdf['pos_ticks'] / total_dir_ticks
            dn_imb = cdf['neg_ticks'] / total_dir_ticks
            
            up = up_imb >= imb_thresh
            dn = dn_imb >= imb_thresh
            
            w_cont = (up.sum() and cdf[up]['next_dir'].sum() or 0) + \
                     (dn.sum() and (len(cdf[dn]) - cdf[dn]['next_dir'].sum()) or 0)
            w_rev = (up.sum() and (len(cdf[up]) - cdf[up]['next_dir'].sum()) or 0) + \
                    (dn.sum() and cdf[dn]['next_dir'].sum() or 0)
            tot = up.sum() + dn.sum()
            if tot >= 8:
                results.append(("CONT TickImbalance", f"IMB>{imb_thresh}", tot, w_cont/tot*100))
                results.append(("REV TickImbalance", f"IMB>{imb_thresh}", tot, w_rev/tot*100))
        
        # ============================================================
        # DIMENSION 5: Wick trap (huge wick, tiny body = manipulation)
        # ============================================================
        for br_max in [0.1, 0.15, 0.2]:
            for wm in [1.5, 2.0]:
                wick_thresh = cdf['range'].mean() * wm
                
                # Big lower wick, tiny body = BUY trap
                up = (cdf['lower_wick'] > wick_thresh) & (cdf['body_ratio'] < br_max)
                dn = (cdf['upper_wick'] > wick_thresh) & (cdf['body_ratio'] < br_max)
                
                # Continuation (wick direction = next direction)
                w_cont = (up.sum() and cdf[up]['next_dir'].sum() or 0) + \
                         (dn.sum() and (len(cdf[dn]) - cdf[dn]['next_dir'].sum()) or 0)
                w_rev = (up.sum() and (len(cdf[up]) - cdf[up]['next_dir'].sum()) or 0) + \
                        (dn.sum() and cdf[dn]['next_dir'].sum() or 0)
                tot = up.sum() + dn.sum()
                if tot >= 5:
                    results.append(("CONT WickTrap", f"BR<{br_max} W>{wm}", tot, w_cont/tot*100))
                    results.append(("REV WickTrap", f"BR<{br_max} W>{wm}", tot, w_rev/tot*100))
        
        # ============================================================
        # DIMENSION 6: TRIPLE STACK (Velocity + Density + Imbalance)
        # ============================================================
        total_dir_ticks = (cdf['pos_ticks'] + cdf['neg_ticks']).replace(0, 1)
        up_imb = cdf['pos_ticks'] / total_dir_ticks
        dn_imb = cdf['neg_ticks'] / total_dir_ticks
        
        for t5m in [1.0, 1.5]:
            t5_thresh = t5_mean + t5m * t5_std
            for dm in [1.0, 1.5]:
                d_thresh = density_mean + dm * density_std
                for imb in [0.65, 0.7]:
                    up = (cdf['t5_move'] > t5_thresh) & (cdf['tick_density'] > d_thresh) & (up_imb >= imb)
                    dn = (cdf['t5_move'] < -t5_thresh) & (cdf['tick_density'] > d_thresh) & (dn_imb >= imb)
                    
                    w_cont = (up.sum() and cdf[up]['next_dir'].sum() or 0) + \
                             (dn.sum() and (len(cdf[dn]) - cdf[dn]['next_dir'].sum()) or 0)
                    w_rev = (up.sum() and (len(cdf[up]) - cdf[up]['next_dir'].sum()) or 0) + \
                            (dn.sum() and cdf[dn]['next_dir'].sum() or 0)
                    tot = up.sum() + dn.sum()
                    if tot >= 5:
                        results.append(("CONT TRIPLE", f"T5>{t5m} D>{dm} I>{imb}", tot, w_cont/tot*100))
                        results.append(("REV TRIPLE", f"T5>{t5m} D>{dm} I>{imb}", tot, w_rev/tot*100))
        
        # ============================================================
        # DIMENSION 7: 3-Candle Momentum Burst
        # ============================================================
        for bm in [1.5, 2.0, 2.5]:
            b3_thresh = cdf['body_3sum'].abs().mean() + bm * cdf['body_3sum'].abs().std()
            
            up = cdf['body_3sum'] > b3_thresh
            dn = cdf['body_3sum'] < -b3_thresh
            
            w_cont = (up.sum() and cdf[up]['next_dir'].sum() or 0) + \
                     (dn.sum() and (len(cdf[dn]) - cdf[dn]['next_dir'].sum()) or 0)
            w_rev = (up.sum() and (len(cdf[up]) - cdf[up]['next_dir'].sum()) or 0) + \
                    (dn.sum() and cdf[dn]['next_dir'].sum() or 0)
            tot = up.sum() + dn.sum()
            if tot >= 8:
                results.append(("CONT 3Candle", f"B3>{bm}", tot, w_cont/tot*100))
                results.append(("REV 3Candle", f"B3>{bm}", tot, w_rev/tot*100))

        # ============================================================
        # DIMENSION 8: Doji Reversal (body_ratio < 0.1 after strong move)
        # ============================================================
        for bm in [1.0, 1.5, 2.0]:
            b_thresh = body_mean + bm * body_std
            doji = cdf['body_ratio'] < 0.15
            prev_strong_up = cdf['prev_body'] > b_thresh
            prev_strong_dn = cdf['prev_body'] < -b_thresh
            
            up = doji & prev_strong_dn  # Doji after big red = buy
            dn = doji & prev_strong_up  # Doji after big green = sell
            
            w = (up.sum() and cdf[up]['next_dir'].sum() or 0) + \
                (dn.sum() and (len(cdf[dn]) - cdf[dn]['next_dir'].sum()) or 0)
            tot = up.sum() + dn.sum()
            if tot >= 5:
                results.append(("Doji Reversal", f"PrevB>{bm}", tot, w/tot*100))

        # Sort and display
        results.sort(key=lambda x: x[3], reverse=True)
        
        print(f"\n  TOP 25 EDGES:")
        print(f"  {'Strategy':<22} | {'Params':<25} | {'Trades':<6} | {'WR%':<6}")
        print(f"  {'-'*65}")
        for r in results[:25]:
            marker = " <== FIRE" if r[3] >= 75 else (" <== GOOD" if r[3] >= 65 else "")
            print(f"  {r[0]:<22} | {r[1]:<25} | {r[2]:<6} | {r[3]:.1f}%{marker}")
    
    conn.close()

if __name__ == "__main__":
    juice_it()
