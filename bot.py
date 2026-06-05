import requests, hmac, hashlib, time, json, os
from datetime import date, datetime, timezone, timedelta

KEY    = "afr1UynKRx9xZiwOLlioGEqQAP4qTxÀ"
SECRET = "0EIc661e8iXKOgi3EqLbZCKVK82BMXSaBsCg8JiJT8VwaLOa90utgEFKA85c"
URL    = "https://api.india.delta.exchange"

LEVERAGE           = 5
INR_RATE           = 85
MAX_SL             = 3
MAX_CONSECUTIVE_SL = 2
DAILY_LOSS_LIMIT   = 200
ATR_TRAIL_MULT     = 2.0
ATR_SL_MULT        = 1.5
MIN_SL_PTS         = 150
MAX_SL_PTS         = 1000

sl_count       = 0
consecutive_sl = 0
daily_pnl_inr  = 0.0
today          = date.today()
last_signal    = "HOLD"

def hdrs(m, p, b=""):
    t = str(int(time.time()))
    s = hmac.new(SECRET.encode(),
                 (m + t + p + b).encode(),
                 hashlib.sha256).hexdigest()
    return {"api-key": KEY, "timestamp": t,
            "signature": s,
            "Content-Type": "application/json"}

def price():
    try:
        r = requests.get(URL + "/v2/tickers",
                         timeout=10)
        for x in r.json()["result"]:
            if x["symbol"] == "BTCUSD":
                p = float(x.get("mark_price")
                          or x["close"])
                print(f"💲 Price:{p}")
                return p
    except Exception as e:
        print(f"❌ Price:{e}")
        return None

def get_balance():
    try:
        h    = hdrs("GET", "/v2/wallet/balances", "")
        r    = requests.get(
                   URL + "/v2/wallet/balances",
                   headers=h, timeout=10)
        data = r.json().get("result", [])
        for x in data:
            print(f"💼 {x.get('asset_symbol')}:"
                  f"{x.get('available_balance')}")
        for x in data:
            sym = x.get("asset_symbol", "")
            if sym in ["USD", "USDT", "USDC", "BTC"]:
                bal = float(
                    x.get("available_balance", 0))
                print(f"✅ Balance:${bal}")
                return bal
        if data:
            return float(
                data[0].get("available_balance", 0))
    except Exception as e:
        print(f"❌ Balance:{e}")
    return None

def calc_size(btc_price):
    balance = get_balance()
    if not balance or balance <= 0:
        print("❌ Balance नहीं!")
        return None
    position_usd = balance * LEVERAGE
    size         = round(position_usd / btc_price, 6)
    size         = max(size, 0.001)
    print(f"💰 ${balance:.4f}×{LEVERAGE}x→{size} BTC")
    return size

def get_actual_entry(pid):
    try:
        time.sleep(3)
        h = hdrs("GET", "/v2/positions", "")
        r = requests.get(URL + "/v2/positions",
                         headers=h, timeout=10)
        for x in r.json().get("result", []):
            if x.get("product_id") == pid:
                ep = float(x.get("entry_price", 0))
                print(f"✅ Entry:{ep}")
                return ep
    except Exception as e:
        print(f"❌ Entry:{e}")
    return None

# ✅ 12hr — enough candles
def candles(resolution="15m", limit_hours=12):
    try:
        end   = int(time.time())
        start = end - (limit_hours * 3600)
        r     = requests.get(
                    URL + "/v2/history/candles",
                    params={"symbol":     "BTCUSD",
                            "resolution": resolution,
                            "start":      start,
                            "end":        end},
                    timeout=10)
        data  = r.json()["result"]
        if data:
            last_close = float(data[-1]["close"])
            print(f"📊 {resolution} "
                  f"Candles:{len(data)} "
                  f"Last:{last_close}")
        return data
    except Exception as e:
        print(f"❌ Candles:{e}")
        return None

def calc_rsi(closes, n=14):
    if len(closes) < n + 1:
        return 50
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i-1]
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    ag = sum(gains[-n:]) / n
    al = sum(losses[-n:]) / n
    if al == 0:
        return 100
    return round(100 - (100 / (1 + ag / al)), 2)

def calc_atr(candle_data, n=14):
    trs = []
    for i in range(1, len(candle_data)):
        h  = float(candle_data[i]["high"])
        l  = float(candle_data[i]["low"])
        pc = float(candle_data[i-1]["close"])
        tr = max(h - l,
                 abs(h - pc),
                 abs(l - pc))
        trs.append(tr)
    if len(trs) < n:
        return 200
    k = 2 / (n + 1)
    a = sum(trs[:n]) / n
    for t in trs[n:]:
        a = t * k + a * (1 - k)
    return round(a, 1)

def find_divergence(candle_data, live_price):
    if len(candle_data) < 20:
        print("⚠️ कम candles!")
        return "HOLD"

    closes = [float(c["close"]) for c in candle_data]
    highs  = [float(c["high"])  for c in candle_data]
    lows   = [float(c["low"])   for c in candle_data]

    last_close = closes[-1]
    if abs(last_close - live_price) > 1500:
        print(f"⚠️ Stale! "
              f"Last:{last_close:.0f} "
              f"Live:{live_price:.0f} "
              f"Diff:{abs(last_close-live_price):.0f}")
        return "HOLD"

    rsi_values = []
    for i in range(14, len(closes)):
        rsi_values.append(calc_rsi(closes[:i+1]))

    if len(rsi_values) < 10:
        return "HOLD"

    current_rsi  = rsi_values[-1]
    lookback     = 20
    recent_highs = highs[-lookback:]
    recent_lows  = lows[-lookback:]
    recent_rsi   = rsi_values[-lookback:]

    price_lows = []
    rsi_lows   = []
    for i in range(1, len(recent_lows)-1):
        if (recent_lows[i] < recent_lows[i-1]
                and recent_lows[i] < recent_lows[i+1]):
            price_lows.append((i, recent_lows[i]))
            if i < len(recent_rsi):
                rsi_lows.append((i, recent_rsi[i]))

    price_highs = []
    rsi_highs   = []
    for i in range(1, len(recent_highs)-1):
        if (recent_highs[i] > recent_highs[i-1]
                and recent_highs[i] > recent_highs[i+1]):
            price_highs.append((i, recent_highs[i]))
            if i < len(recent_rsi):
                rsi_highs.append((i, recent_rsi[i]))

    print(f"📊 RSI:{current_rsi:.1f} "
          f"Lows:{len(price_lows)} "
          f"Highs:{len(price_highs)} "
          f"Live:{live_price:.0f}")

    if len(price_lows) >= 2 and len(rsi_lows) >= 2:
        p_low1 = price_lows[-2][1]
        p_low2 = price_lows[-1][1]
        r_low1 = rsi_lows[-2][1]
        r_low2 = rsi_lows[-1][1]
        if (p_low2 < p_low1
                and r_low2 > r_low1
                and current_rsi < 45):
            print(f"🟢 BULLISH DIV! "
                  f"P:{p_low1:.0f}→{p_low2:.0f} "
                  f"RSI:{r_low1:.1f}→{r_low2:.1f}")
            return "BUY"

    if len(price_highs) >= 2 and len(rsi_highs) >= 2:
        p_hi1 = price_highs[-2][1]
        p_hi2 = price_highs[-1][1]
        r_hi1 = rsi_highs[-2][1]
        r_hi2 = rsi_highs[-1][1]
        if (p_hi2 > p_hi1
                and r_hi2 < r_hi1
                and current_rsi > 55):
            print(f"🔴 BEARISH DIV! "
                  f"P:{p_hi1:.0f}→{p_hi2:.0f} "
                  f"RSI:{r_hi1:.1f}→{r_hi2:.1f}")
            return "SELL"

    print(f"⏳ No Div RSI:{current_rsi:.1f}")
    return "HOLD"

def get_pid():
    try:
        r = requests.get(URL + "/v2/products",
                         timeout=10)
        for x in r.json().get("result", []):
            if x.get("symbol") == "BTCUSD":
                return x.get("id")
    except Exception as e:
        print(f"❌ PID:{e}")
    return None

def cancel_all_orders(pid):
    try:
        b = json.dumps({
            "product_id":          pid,
            "cancel_limit_orders": True,
            "cancel_stop_orders":  True})
        h = hdrs("DELETE", "/v2/orders", b)
        requests.delete(URL + "/v2/orders",
                        headers=h,
                        data=b,
                        timeout=10)
        print("🗑️ Cancelled")
    except Exception as e:
        print(f"Cancel:{e}")

def place_order(pid, side, order_type, size,
                price_val=None,
                stop_price=None,
                stop_type=None):
    body = {"product_id": pid,
            "size":        size,
            "side":        side,
            "order_type":  order_type}
    if price_val:
        body["limit_price"]     = str(round(price_val, 1))
    if stop_price:
        body["stop_price"]      = str(round(stop_price, 1))
    if stop_type:
        body["stop_order_type"] = stop_type
    b = json.dumps(body)
    h = hdrs("POST", "/v2/orders", b)
    r = requests.post(URL + "/v2/orders",
                      headers=h,
                      data=b,
                      timeout=10)
    return r.json()

def trail_monitor(pid, side, entry, size, init_sl):
    global sl_count, consecutive_sl
    global daily_pnl_inr, last_signal

    close_side = "sell" if side == "buy" else "buy"
    current_sl = init_sl
    best_price = entry
    trail_hits = 0

    print(f"🔄 Entry:{entry} SL:{current_sl}")
    print(f"♾️  No TP — ATR Trail")

    for _ in range(5000):
        time.sleep(60)
        cp = price()
        if not cp:
            continue

        c_data = candles()
        if c_data:
            fresh_atr  = calc_atr(c_data)
            trail_dist = round(
                fresh_atr * ATR_TRAIL_MULT, 1)
            trail_dist = max(trail_dist, MIN_SL_PTS)
            trail_dist = min(trail_dist, MAX_SL_PTS)
        else:
            trail_dist = 300

        profit_pts = round(cp - entry, 1) \
                     if side == "buy" \
                     else round(entry - cp, 1)
        profit_inr = round(
            profit_pts * size * INR_RATE, 1)

        print(f"💹 CP:{cp} "
              f"P&L:{profit_pts:+.0f}pts "
              f"₹{profit_inr:+.0f} | "
              f"SL:{current_sl} | "
              f"Trail:{trail_dist} | "
              f"Daily:₹{daily_pnl_inr:+.0f}")

        if side == "buy":
            if cp > best_price:
                best_price = cp
            new_sl = round(best_price - trail_dist, 1)
            if new_sl > current_sl:
                old_sl     = current_sl
                current_sl = new_sl
                trail_hits += 1
                cancel_all_orders(pid)
                place_order(pid, close_side,
                            "limit_order", size,
                            current_sl, current_sl,
                            "stop_loss_order")
                print(f"📈 Trail#{trail_hits} "
                      f"SL:{old_sl}→{current_sl}")

            if cp <= current_sl:
                cancel_all_orders(pid)
                final_pnl = round(
                    (current_sl - entry)
                    * size * INR_RATE, 1)
                daily_pnl_inr += final_pnl
                if profit_pts > 0:
                    print(f"🎯 Profit! "
                          f"+{profit_pts:.0f}pts "
                          f"₹{final_pnl:+.0f}🔥")
                    consecutive_sl = 0
                else:
                    print(f"🛑 SL! ₹{final_pnl:.0f}")
                    sl_count       += 1
                    consecutive_sl += 1
                break

        else:
            if cp < best_price:
                best_price = cp
            new_sl = round(best_price + trail_dist, 1)
            if new_sl < current_sl:
                old_sl     = current_sl
                current_sl = new_sl
                trail_hits += 1
                cancel_all_orders(pid)
                place_order(pid, close_side,
                            "limit_order", size,
                            current_sl, current_sl,
                            "stop_loss_order")
                print(f"📉 Trail#{trail_hits} "
                      f"SL:{old_sl}→{current_sl}")

            if cp >= current_sl:
                cancel_all_orders(pid)
                final_pnl = round(
                    (entry - current_sl)
                    * size * INR_RATE, 1)
                daily_pnl_inr += final_pnl
                if profit_pts > 0:
                    print(f"🎯 Profit! "
                          f"+{profit_pts:.0f}pts "
                          f"₹{final_pnl:+.0f}🔥")
                    consecutive_sl = 0
                else:
                    print(f"🛑 SL! ₹{final_pnl:.0f}")
                    sl_count       += 1
                    consecutive_sl += 1
                break

    last_signal = "HOLD"
    print(f"✅ Done! Trail:{trail_hits}x "
          f"SL:{sl_count}/{MAX_SL} "
          f"Daily:₹{daily_pnl_inr:+.0f}")

def order(side, candle_data):
    try:
        pid = get_pid()
        if not pid:
            print("❌ Product नहीं")
            return

        cp = price()
        if not cp:
            print("❌ Price नहीं")
            return

        size = calc_size(cp)
        if not size:
            print("❌ Size नहीं")
            return

        close_side = "sell" if side == "buy" \
                     else "buy"
        res        = place_order(pid, side,
                                 "market_order",
                                 size)
        print(f"📌 {side.upper()} "
              f"Price:{cp} Size:{size}")

        if not res.get("success"):
            print(f"❌ Failed:{res.get('error')}")
            return

        entry = get_actual_entry(pid) or cp

        current_atr = calc_atr(candle_data)
        sl_dist     = round(
            current_atr * ATR_SL_MULT, 1)
        sl_dist     = max(sl_dist, MIN_SL_PTS)
        sl_dist     = min(sl_dist, MAX_SL_PTS)

        sl = round(entry - sl_dist, 1) \
             if side == "buy" \
             else round(entry + sl_dist, 1)

        sl_res = place_order(pid, close_side,
                             "limit_order", size,
                             sl, sl,
                             "stop_loss_order")
        print(f"🛡️ SL:{sl} "
              f"Dist:{sl_dist}pts "
              f"OK:{sl_res.get('success')}")

        trail_monitor(pid, side, entry, size, sl)

    except Exception as e:
        print(f"❌ Order:{e}")

def run():
    global sl_count, consecutive_sl
    global daily_pnl_inr, today, last_signal

    cooldown = 0

    print("🚀 Sniper Bot v15.1")
    print("📊 RSI Divergence | ATR Trail | No TP")
    print(f"✅ Real: india.delta.exchange")
    print(f"🛡️ Loss:₹{DAILY_LOSS_LIMIT} "
          f"MaxSL:{MAX_SL} "
          f"ConsSL:{MAX_CONSECUTIVE_SL}")

    while True:

        if date.today() != today:
            today          = date.today()
            sl_count       = 0
            consecutive_sl = 0
            daily_pnl_inr  = 0.0
            last_signal    = "HOLD"
            print("🌅 नया दिन! Reset.")

        if daily_pnl_inr <= -DAILY_LOSS_LIMIT:
            print(f"🛑 Loss! ₹{daily_pnl_inr:.0f} बंद")
            time.sleep(3600)
            continue

        if sl_count >= MAX_SL:
            print(f"🚫 {MAX_SL} SL! बंद")
            time.sleep(3600)
            continue

        if consecutive_sl >= MAX_CONSECUTIVE_SL:
            print("⛔ Consecutive SL! 2hr Rest")
            consecutive_sl = 0
            time.sleep(7200)
            continue

        if cooldown > 0:
            print(f"⏳ Cooldown:{cooldown}")
            cooldown -= 1
            time.sleep(300)
            continue

        cp = price()
        c  = candles()

        if cp and c and len(c) >= 20:
            s = find_divergence(c, cp)
            print(f"💰 Price:{cp} "
                  f"Signal:{s} "
                  f"SL:{sl_count}/{MAX_SL} "
                  f"Daily:₹{daily_pnl_inr:+.0f}")

            if s != "HOLD" and s != last_signal:
                print(f"✅ {s} — Trade!")
                order(s.lower(), c)
                last_signal = s
                cooldown    = 3
            else:
                print("⏳ Wait...")
        else:
            print(f"⚠️ Data:{len(c) if c else 0}")

        time.sleep(300)

run()                                                
                
    
                          
