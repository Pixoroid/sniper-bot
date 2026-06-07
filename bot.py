import requests, hmac, hashlib, time, json, os
from datetime import date

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

# ✅ Balance Fix — सब try करो
def get_balance():
    try:
        h    = hdrs("GET", "/v2/wallet/balances", "")
        r    = requests.get(
                   URL + "/v2/wallet/balances",
                   headers=h, timeout=10)
        resp = r.json()
        print(f"💼 Raw Balance API: {resp}")

        data = resp.get("result", [])
        if not data:
            print("❌ Balance data empty!")
            return 0.0

        # सब print करो
        for x in data:
            print(f"💼 Asset:{x.get('asset_symbol')} "
                  f"Bal:{x.get('available_balance')} "
                  f"Total:{x.get('balance')}")

        # INR
        for x in data:
            sym = x.get("asset_symbol", "")
            bal = float(x.get("available_balance")
                        or x.get("balance") or 0)
            if sym == "INR" and bal > 0:
                usd = round(bal / INR_RATE, 4)
                print(f"✅ INR:₹{bal:.0f} = ${usd}")
                return usd

        # USD/USDT
        for x in data:
            sym = x.get("asset_symbol", "")
            bal = float(x.get("available_balance")
                        or x.get("balance") or 0)
            if sym in ["USD", "USDT", "USDC"] \
                    and bal > 0:
                print(f"✅ {sym}:${bal}")
                return bal

        # BTC
        for x in data:
            sym = x.get("asset_symbol", "")
            bal = float(x.get("available_balance")
                        or x.get("balance") or 0)
            if sym == "BTC" and bal > 0:
                cp  = price() or 60000
                usd = round(bal * cp, 4)
                print(f"✅ BTC:{bal} = ${usd}")
                return usd

        # कोई भी पहला non-zero
        for x in data:
            bal = float(x.get("available_balance")
                        or x.get("balance") or 0)
            if bal > 0:
                sym = x.get("asset_symbol", "")
                print(f"✅ {sym}:{bal}")
                return bal

        print("❌ सब assets zero हैं!")
        return 0.0

    except Exception as e:
        print(f"❌ Balance Error:{e}")
        return 0.0

def calc_size(btc_price, balance_usd):
    position_usd = balance_usd * LEVERAGE
    size         = round(position_usd / btc_price, 6)
    size         = max(size, 0.001)
    print(f"💰 ${balance_usd:.4f}×{LEVERAGE}x"
          f"→{size} BTC")
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

def volume_ok(candle_data, multiplier=1.2):
    vols = [float(c["volume"]) for c in candle_data]
    avg  = sum(vols[-20:]) / 20
    cur  = vols[-1]
    ok   = cur > avg * multiplier
    print(f"📊 Vol:{cur:.0f} Avg:{avg:.0f} OK:{ok}")
    return ok

# ✅ Signal Fix — Trend mode strict किया
def find_divergence(candle_data):
    if len(candle_data) < 20:
        print("⚠️ कम candles!")
        return "HOLD"

    closes = [float(c["close"]) for c in candle_data]
    opens  = [float(c["open"])  for c in candle_data]
    highs  = [float(c["high"])  for c in candle_data]
    lows   = [float(c["low"])   for c in candle_data]

    rsi_values = []
    for i in range(14, len(closes)):
        rsi_values.append(calc_rsi(closes[:i+1]))

    if len(rsi_values) < 10:
        return "HOLD"

    current_rsi = rsi_values[-1]
    vol_good    = volume_ok(candle_data)
    green       = closes[-1] > opens[-1]
    red         = closes[-1] < opens[-1]

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
          f"Vol:{vol_good} G:{green} R:{red}")

    # Bullish Divergence
    if len(price_lows) >= 2 and len(rsi_lows) >= 2:
        p_low1     = price_lows[-2][1]
        p_low2     = price_lows[-1][1]
        r_low1     = rsi_lows[-2][1]
        r_low2     = rsi_lows[-1][1]
        swing_size = abs(p_low1 - p_low2)
        if (p_low2 < p_low1
                and r_low2 > r_low1
                and current_rsi < 45
                and vol_good and green
                and swing_size >= 500):
            print(f"🟢 BULLISH DIV! "
                  f"Swing:{swing_size:.0f}")
            return "BUY"

    # Bearish Divergence
    if len(price_highs) >= 2 and len(rsi_highs) >= 2:
        p_hi1      = price_highs[-2][1]
        p_hi2      = price_highs[-1][1]
        r_hi1      = rsi_highs[-2][1]
        r_hi2      = rsi_highs[-1][1]
        swing_size = abs(p_hi2 - p_hi1)
        if (p_hi2 > p_hi1
                and r_hi2 < r_hi1
                and current_rsi > 55
                and vol_good and red
                and swing_size >= 500):
            print(f"🔴 BEARISH DIV! "
                  f"Swing:{swing_size:.0f}")
            return "SELL"

    # ✅ Trend Mode — strict rules
    curr = closes[-1]
    prev = closes[-5] if len(closes) >= 5 \
           else closes[0]
    move = (prev - curr) / prev * 100

    # SELL: price नीचे गई + RSI < 45 + Red
    if (move > 1.5
            and current_rsi < 45
            and red
            and vol_good):
        print(f"🔴 TREND SELL! "
              f"Move:{move:.1f}% RSI:{current_rsi:.1f}")
        return "SELL"

    # BUY: price ऊपर गई + RSI > 55 + Green
    if (move < -1.5
            and current_rsi > 55
            and green
            and vol_good):
        print(f"🟢 TREND BUY! "
              f"Move:{move:.1f}% RSI:{current_rsi:.1f}")
        return "BUY"

    print(f"⏳ No Signal RSI:{current_rsi:.1f} "
          f"Move:{move:.1f}%")
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

def trade_monitor(pid, side, entry, sl,
                  size, has_balance):
    global sl_count, consecutive_sl
    global daily_pnl_inr, last_signal

    close_side = "sell" if side == "buy" else "buy"
    current_sl = sl
    best_price = entry
    trail_hits = 0
    sl_dist    = abs(entry - sl)

    tp1 = round(entry + 300, 1) if side == "buy" \
          else round(entry - 300, 1)
    tp2 = round(entry + 600, 1) if side == "buy" \
          else round(entry - 600, 1)
    tp3 = round(entry + 900, 1) if side == "buy" \
          else round(entry - 900, 1)

    tp1_hit = False
    tp2_hit = False
    tp3_hit = False
    mode    = "💰 REAL" if has_balance \
              else "👁️ TRACKING"

    print(f"\n{'='*45}")
    print(f"{mode} TRADE")
    print(f"{'='*45}")
    print(f"📌 Side:   {side.upper()}")
    print(f"💲 Entry:  {entry}")
    print(f"🛡️  SL:     {current_sl} "
          f"({sl_dist:.0f} pts)")
    print(f"🎯 TP1:    {tp1} (+300) R:R 1:1")
    print(f"🎯 TP2:    {tp2} (+600) R:R 1:2")
    print(f"🎯 TP3:    {tp3} (+900) R:R 1:3")
    print(f"♾️  Trail:  ATR×{ATR_TRAIL_MULT}")
    print(f"{'='*45}\n")

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
        rr = round(profit_pts / sl_dist, 2) \
             if sl_dist > 0 else 0

        print(f"{'💰' if has_balance else '👁️'} "
              f"CP:{cp:.0f} | "
              f"P&L:{profit_pts:+.0f}pts | "
              f"R:R 1:{rr:.1f} | "
              f"SL:{current_sl:.0f} | "
              f"Trail:{trail_dist:.0f}")

        if side == "buy":

            if not tp1_hit and cp >= tp1:
                tp1_hit    = True
                current_sl = entry + 10
                if has_balance and pid:
                    cancel_all_orders(pid)
                    place_order(pid, close_side,
                                "limit_order", size,
                                current_sl, current_sl,
                                "stop_loss_order")
                print(f"\n{'✅'*8}")
                print(f"TP1 HIT! +300pts R:R 1:1")
                print(f"SL→Breakeven:{current_sl:.0f}")
                print(f"{'✅'*8}\n")

            elif tp1_hit and not tp2_hit \
                    and cp >= tp2:
                tp2_hit    = True
                current_sl = entry + 300
                if has_balance and pid:
                    cancel_all_orders(pid)
                    place_order(pid, close_side,
                                "limit_order", size,
                                current_sl, current_sl,
                                "stop_loss_order")
                print(f"\n{'🚀'*8}")
                print(f"TP2 HIT! +600pts R:R 1:2")
                print(f"SL→+300:{current_sl:.0f}")
                print(f"{'🚀'*8}\n")

            elif tp2_hit and not tp3_hit \
                    and cp >= tp3:
                tp3_hit    = True
                current_sl = entry + 600
                if has_balance and pid:
                    cancel_all_orders(pid)
                    place_order(pid, close_side,
                                "limit_order", size,
                                current_sl, current_sl,
                                "stop_loss_order")
                print(f"\n{'🔥'*8}")
                print(f"TP3 HIT! +900pts R:R 1:3")
                print(f"SL→+600:{current_sl:.0f}")
                print(f"{'🔥'*8}\n")

            elif tp3_hit:
                if cp > best_price:
                    best_price = cp
                new_sl = round(
                    best_price - trail_dist, 1)
                if new_sl > current_sl:
                    old_sl     = current_sl
                    current_sl = new_sl
                    trail_hits += 1
                    if has_balance and pid:
                        cancel_all_orders(pid)
                        place_order(pid, close_side,
                                    "limit_order", size,
                                    current_sl, current_sl,
                                    "stop_loss_order")
                    print(f"🚀 Trail#{trail_hits} "
                          f"SL:{old_sl:.0f}→"
                          f"{current_sl:.0f}")

            if cp <= current_sl:
                if has_balance and pid:
                    cancel_all_orders(pid)
                final_pts = round(
                    current_sl - entry, 1)
                daily_pnl_inr += final_pts * 0.001
                rr_f = round(
                    final_pts / sl_dist, 2) \
                    if sl_dist > 0 else 0
                print(f"\n{'='*45}")
                print(f"{'🎯 PROFIT EXIT!' if final_pts > 0 else '🛑 SL HIT!'} {mode}")
                print(f"{'='*45}")
                print(f"📌 Side:   BUY")
                print(f"💲 Entry:  {entry}")
                print(f"💲 Exit:   {current_sl:.0f}")
                print(f"📈 P&L:    {final_pts:+.0f} pts")
                print(f"📊 R:R:    1:{rr_f:.1f}")
                print(f"✅ TP1:    {'HIT ✅' if tp1_hit else 'Miss ❌'}")
                print(f"✅ TP2:    {'HIT ✅' if tp2_hit else 'Miss ❌'}")
                print(f"✅ TP3:    {'HIT ✅' if tp3_hit else 'Miss ❌'}")
                print(f"🔄 Trails: {trail_hits}")
                print(f"💰 Daily:  ₹{daily_pnl_inr:+.0f}")
                print(f"{'='*45}\n")
                if final_pts <= 0:
                    sl_count       += 1
                    consecutive_sl += 1
                else:
                    consecutive_sl = 0
                break

        else:

            if not tp1_hit and cp <= tp1:
                tp1_hit    = True
                current_sl = entry - 10
                if has_balance and pid:
                    cancel_all_orders(pid)
                    place_order(pid, close_side,
                                "limit_order", size,
                                current_sl, current_sl,
                                "stop_loss_order")
                print(f"\n{'✅'*8}")
                print(f"TP1 HIT! +300pts R:R 1:1")
                print(f"SL→Breakeven:{current_sl:.0f}")
                print(f"{'✅'*8}\n")

            elif tp1_hit and not tp2_hit \
                    and cp <= tp2:
                tp2_hit    = True
                current_sl = entry - 300
                if has_balance and pid:
                    cancel_all_orders(pid)
                    place_order(pid, close_side,
                                "limit_order", size,
                                current_sl, current_sl,
                                "stop_loss_order")
                print(f"\n{'🚀'*8}")
                print(f"TP2 HIT! +600pts R:R 1:2")
                print(f"SL→+300:{current_sl:.0f}")
                print(f"{'🚀'*8}\n")

            elif tp2_hit and not tp3_hit \
                    and cp <= tp3:
                tp3_hit    = True
                current_sl = entry - 600
                if has_balance and pid:
                    cancel_all_orders(pid)
                    place_order(pid, close_side,
                                "limit_order", size,
                                current_sl, current_sl,
                                "stop_loss_order")
                print(f"\n{'🔥'*8}")
                print(f"TP3 HIT! +900pts R:R 1:3")
                print(f"SL→+600:{current_sl:.0f}")
                print(f"{'🔥'*8}\n")

            elif tp3_hit:
                if cp < best_price:
                    best_price = cp
                new_sl = round(
                    best_price + trail_dist, 1)
                if new_sl < current_sl:
                    old_sl     = current_sl
                    current_sl = new_sl
                    trail_hits += 1
                    if has_balance and pid:
                        cancel_all_orders(pid)
                        place_order(pid, close_side,
                                    "limit_order", size,
                                    current_sl, current_sl,
                                    "stop_loss_order")
                    print(f"🚀 Trail#{trail_hits} "
                          f"SL:{old_sl:.0f}→"
                          f"{current_sl:.0f}")

            if cp >= current_sl:
                if has_balance and pid:
                    cancel_all_orders(pid)
                final_pts = round(
                    entry - current_sl, 1)
                daily_pnl_inr += final_pts * 0.001
                rr_f = round(
                    final_pts / sl_dist, 2) \
         

                    
