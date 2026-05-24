import requests, hmac, hashlib, time, json
from datetime import date

# ============================================================
# 🚀 SNIPER BOT v2.0 — IMPROVED
# Fixes: Trailing SL logic, Entry Signal, Volume Filter
# ============================================================

KEY    = "9ihv6wjSmxx5wbpG5BwjeV5aY8at9r"
SECRET = "qWGvfU1SWHDrOoEKMI1JWdBbWsg6CMx3iYBvu1icXwutzuUaN1tq64VVHKS9"
URL    = "https://cdn-ind.testnet.deltaex.org"

# ── Risk Settings ────────────────────────────────────────────
MAX_SL        = 3       # दिन में max SL
SL_PTS        = 100     # Stop Loss points
TRAIL_STEP    = 500     # हर 500 pts पर trail
LOCK_PTS      = 300     # Breakeven के बाद minimum lock profit (v2 NEW)
LOSS_PER_TRADE = 100    # ₹ max loss per trade
INR_RATE      = 85      # 1 USD = ₹85

# ── State ────────────────────────────────────────────────────
sl_count = 0
today    = date.today()

# ============================================================
# HELPERS
# ============================================================

def calc_size():
    loss_usd = LOSS_PER_TRADE / INR_RATE
    size = round(loss_usd / SL_PTS, 4)
    size = max(size, 0.001)
    print(f"📦 Size:{size} BTC (₹{LOSS_PER_TRADE} risk)")
    return size

def hdrs(m, p, b=""):
    t = str(int(time.time()))
    s = hmac.new(SECRET.encode(), (m + t + p + b).encode(), hashlib.sha256).hexdigest()
    return {"api-key": KEY, "timestamp": t, "signature": s, "Content-Type": "application/json"}

def price():
    try:
        r = requests.get(URL + "/v2/tickers", timeout=10)
        for x in r.json()["result"]:
            if x["symbol"] == "BTCUSD":
                return float(x["close"])
    except:
        return None

def candles(resolution="15m", limit_hours=30):
    try:
        end   = int(time.time())
        start = end - (limit_hours * 3600)
        r = requests.get(URL + "/v2/history/candles",
            params={"symbol": "BTCUSD", "resolution": resolution,
                    "start": start, "end": end}, timeout=10)
        return r.json()["result"]
    except:
        return None

# ============================================================
# INDICATORS
# ============================================================

def ema(closes, n):
    k = 2 / (n + 1)
    e = closes[0]
    for p in closes[1:]:
        e = p * k + e * (1 - k)
    return e

def rsi(closes, n=14):
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i-1]
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    ag = sum(gains[-n:]) / n
    al = sum(losses[-n:]) / n
    if al == 0:
        return 100
    return 100 - (100 / (1 + ag / al))

def macd(closes, fast=12, slow=26, sig=9):
    e_fast = ema(closes[-slow*2:], fast)
    e_slow = ema(closes[-slow*2:], slow)
    macd_line = e_fast - e_slow
    # Signal line (EMA of last MACD values — simplified)
    return macd_line

def volume_ok(candle_data, multiplier=1.3):
    """Volume surge check — current candle vs 20-candle average"""
    vols = [float(c["volume"]) for c in candle_data]
    avg  = sum(vols[-20:]) / 20
    cur  = vols[-1]
    print(f"📊 Volume:{cur:.0f} Avg:{avg:.0f} OK:{cur > avg * multiplier}")
    return cur > avg * multiplier

# ============================================================
# SIGNAL — v2 IMPROVED
# Adds: EMA50 trend filter + Volume confirmation + MACD direction
# ============================================================

def signal(candle_data):
    closes = [float(c["close"]) for c in candle_data]
    opens  = [float(c["open"])  for c in candle_data]
    highs  = [float(c["high"])  for c in candle_data]
    lows   = [float(c["low"])   for c in candle_data]

    e9   = ema(closes, 9)
    e21  = ema(closes, 21)
    e50  = ema(closes, 50)      # NEW: Trend filter
    r    = rsi(closes)
    m    = macd(closes)         # NEW: MACD direction
    p    = closes[-1]
    o    = opens[-1]
    prev_close = closes[-2]

    green = p > o
    red   = p < o

    # Volume
    vol_good = volume_ok(candle_data)

    # Trend alignment (NEW)
    bull_trend = e9 > e21 > e50
    bear_trend = e9 < e21 < e50

    print(f"📈 EMA9:{e9:.0f} EMA21:{e21:.0f} EMA50:{e50:.0f} RSI:{r:.1f} MACD:{m:.1f} Green:{green}")

    # BUY: Trend UP + RSI healthy + MACD positive + volume surge + green candle
    if bull_trend and r >= 40 and r <= 72 and m > 0 and green and vol_good:
        return "BUY"

    # SELL: Trend DOWN + RSI healthy + MACD negative + volume surge + red candle
    elif bear_trend and r >= 28 and r <= 60 and m < 0 and red and vol_good:
        return "SELL"

    return "HOLD"

# ============================================================
# ORDER HELPERS
# ============================================================

def get_pid():
    r = requests.get(URL + "/v2/products", timeout=10)
    for x in r.json().get("result", []):
        if x.get("symbol") == "BTCUSD":
            return x.get("id")
    return None

def cancel_all_orders(pid):
    try:
        b = json.dumps({"product_id": pid,
                        "cancel_limit_orders": True,
                        "cancel_stop_orders": True})
        h = hdrs("DELETE", "/v2/orders", b)
        requests.delete(URL + "/v2/orders", headers=h, data=b, timeout=10)
        print("🗑️ Orders cancelled")
    except Exception as e:
        print("Cancel error:", e)

def place_order(pid, side, order_type, size,
                price_val=None, stop_price=None, stop_type=None):
    body = {"product_id": pid, "size": size,
            "side": side, "order_type": order_type}
    if price_val:
        body["limit_price"]      = str(round(price_val, 1))
    if stop_price:
        body["stop_price"]       = str(round(stop_price, 1))
    if stop_type:
        body["stop_order_type"]  = stop_type
    b = json.dumps(body)
    h = hdrs("POST", "/v2/orders", b)
    r = requests.post(URL + "/v2/orders", headers=h, data=b, timeout=10)
    return r.json()

# ============================================================
# TRAILING LOGIC — v2 FIXED
# Fix: Trail check BEFORE SL hit check
# New: Lock-in profit after breakeven (LOCK_PTS)
# New: 60s trail check (was 300s = too slow)
# ============================================================

def trail_monitor(pid, side, entry, size):
    global sl_count

    close_side  = "sell" if side == "buy" else "buy"
    current_sl  = round(entry - SL_PTS, 1) if side == "buy" else round(entry + SL_PTS, 1)
    next_target = round(entry + TRAIL_STEP, 1) if side == "buy" else round(entry - TRAIL_STEP, 1)
    trail_count = 0
    breakeven   = False

    print(f"🔄 Trail Monitor | Entry:{entry} | SL:{current_sl} | Target:{next_target}")

    for _ in range(1000):
        time.sleep(60)   # ✅ 60s check (was 300s)
        cp = price()
        if not cp:
            continue

        profit_pts = round(cp - entry, 1) if side == "buy" else round(entry - cp, 1)
        print(f"💹 Price:{cp} | Profit:{profit_pts:+.0f} pts | SL:{current_sl} | Next:{next_target}")

        # ─── LONG LOGIC ──────────────────────────────────────
        if side == "buy":

            # ✅ Trail check FIRST (Fixed order)
            if cp >= next_target:
                trail_count += 1
                cancel_all_orders(pid)

                if not breakeven:
                    # First trail hit → move SL to breakeven
                    current_sl = entry + 10      # Slightly above entry = guaranteed profit
                    breakeven  = True
                    print(f"✅ +{TRAIL_STEP} pts! Breakeven! New SL:{current_sl}")
                else:
                    # Subsequent trail hits → lock in profit (LOCK_PTS below trail)
                    current_sl = round(next_target - LOCK_PTS, 1)
                    print(f"🚀 Trail #{trail_count}! +{TRAIL_STEP * trail_count} pts! Lock SL:{current_sl}")

                # Place new SL order
                sl_res = place_order(pid, close_side, "limit_order",
                                     size, current_sl, current_sl, "stop_loss_order")
                print(f"🔒 New SL placed: {current_sl} OK:{sl_res.get('success')}")

                next_target = round(next_target + TRAIL_STEP, 1)
                print(f"🎯 Next Target: {next_target}")

            # SL hit check AFTER trail check
            elif cp <= current_sl:
                cancel_all_orders(pid)
                if breakeven:
                    profit = round(cp - entry, 1)
                    print(f"🎯 Exit with Profit! +{profit} pts 🔥")
                else:
                    loss_inr = round(SL_PTS * size * INR_RATE, 1)
                    print(f"🛑 SL Hit! -₹{loss_inr}")
                    sl_count += 1
                break

        # ─── SHORT LOGIC ─────────────────────────────────────
        else:

            # Trail check FIRST
            if cp <= next_target:
                trail_count += 1
                cancel_all_orders(pid)

                if not breakeven:
                    current_sl = entry - 10      # Slightly below entry
                    breakeven  = True
                    print(f"✅ +{TRAIL_STEP} pts! Breakeven! New SL:{current_sl}")
                else:
                    current_sl = round(next_target + LOCK_PTS, 1)
                    print(f"🚀 Trail #{trail_count}! +{TRAIL_STEP * trail_count} pts! Lock SL:{current_sl}")

                sl_res = place_order(pid, close_side, "limit_order",
                                     size, current_sl, current_sl, "stop_loss_order")
                print(f"🔒 New SL placed: {current_sl} OK:{sl_res.get('success')}")

                next_target = round(next_target - TRAIL_STEP, 1)
                print(f"🎯 Next Target: {next_target}")

            # SL hit check AFTER
            elif cp >= current_sl:
                cancel_all_orders(pid)
                if breakeven:
                    profit = round(entry - cp, 1)
                    print(f"🎯 Exit with Profit! +{profit} pts 🔥")
                else:
                    loss_inr = round(SL_PTS * size * INR_RATE, 1)
                    print(f"🛑 SL Hit! -₹{loss_inr}")
                    sl_count += 1
                break

    print(f"✅ Trade Done! Daily SL:{sl_count}/{MAX_SL}")

# ============================================================
# MAIN ORDER FUNCTION
# ============================================================

def order(side):
    try:
        pid   = get_pid()
        if not pid:
            print("❌ Product नहीं मिला")
            return

        entry = price()
        size  = calc_size()
        close_side = "sell" if side == "buy" else "buy"

        # Place market entry
        res = place_order(pid, side, "market_order", size)
        print(f"📌 ORDER:{side.upper()} Entry:{entry} Size:{size}")
        print(f"✅ Success:{res.get('success')}")

        if not res.get("success"):
            print("❌ Error:", res.get("error"))
            return

        time.sleep(2)

        # Place initial SL
        sl = round(entry - SL_PTS, 1) if side == "buy" else round(entry + SL_PTS, 1)
        sl_res = place_order(pid, close_side, "limit_order",
                             size, sl, sl, "stop_loss_order")
        print(f"🛡️ Initial SL:{sl} OK:{sl_res.get('success')}")

        # Start trailing monitor
        trail_monitor(pid, side, entry, size)

    except Exception as e:
        print("❌ Order Error:", e)

# ============================================================
# MAIN LOOP
# ============================================================

def run():
    global sl_count, today
    last_signal = "HOLD"
    cooldown    = 0   # Candles to skip after a trade

    print("🚀 Sniper Bot v2.0 Started!")

    while True:
        # Daily reset
        if date.today() != today:
            today       = date.today()
            sl_count    = 0
            last_signal = "HOLD"
            print("🌅 नया दिन! SL count reset.")

        # Daily SL limit
        if sl_count >= MAX_SL:
            print(f"🚫 {MAX_SL} SL hit! आज trading बंद 🔒")
            time.sleep(3600)
            continue

        # Cooldown after trade
        if cooldown > 0:
            print(f"⏳ Cooldown: {cooldown} candles बाकी")
            cooldown -= 1
            time.sleep(900)
            continue

        p = price()
        c = candles()

        if p and c and len(c) >= 55:
            s = signal(c)
            print(f"💰 Price:{p} | Signal:{s} | SL:{sl_count}/{MAX_SL}")

            if s != "HOLD" and s != last_signal:
                print(f"✅ Confirmed: {s} — Entering trade...")
                order(s.lower())
                last_signal = s
                cooldown    = 3   # 3 candles (45 min) cooldown after trade
            else:
                print("⏳ Wait...")
        else:
            print("⚠️ Data कम है, wait कर रहे हैं...")

        time.sleep(900)   # 15 min candle

run()
      import requests, hmac, hashlib, time, json
from datetime import date

# ============================================================
# 🚀 SNIPER BOT v2.0 — IMPROVED
# Fixes: Trailing SL logic, Entry Signal, Volume Filter
# ============================================================

KEY    = "9ihv6wjSmxx5wbpG5BwjeV5aY8at9r"
SECRET = "qWGvfU1SWHDrOoEKMI1JWdBbWsg6CMx3iYBvu1icXwutzuUaN1tq64VVHKS9"
URL    = "https://cdn-ind.testnet.deltaex.org"

# ── Risk Settings ────────────────────────────────────────────
MAX_SL        = 3       # दिन में max SL
SL_PTS        = 100     # Stop Loss points
TRAIL_STEP    = 500     # हर 500 pts पर trail
LOCK_PTS      = 300     # Breakeven के बाद minimum lock profit (v2 NEW)
LOSS_PER_TRADE = 100    # ₹ max loss per trade
INR_RATE      = 85      # 1 USD = ₹85

# ── State ────────────────────────────────────────────────────
sl_count = 0
today    = date.today()

# ============================================================
# HELPERS
# ============================================================

def calc_size():
    loss_usd = LOSS_PER_TRADE / INR_RATE
    size = round(loss_usd / SL_PTS, 4)
    size = max(size, 0.001)
    print(f"📦 Size:{size} BTC (₹{LOSS_PER_TRADE} risk)")
    return size

def hdrs(m, p, b=""):
    t = str(int(time.time()))
    s = hmac.new(SECRET.encode(), (m + t + p + b).encode(), hashlib.sha256).hexdigest()
    return {"api-key": KEY, "timestamp": t, "signature": s, "Content-Type": "application/json"}

def price():
    try:
        r = requests.get(URL + "/v2/tickers", timeout=10)
        for x in r.json()["result"]:
            if x["symbol"] == "BTCUSD":
                return float(x["close"])
    except:
        return None

def candles(resolution="15m", limit_hours=30):
    try:
        end   = int(time.time())
        start = end - (limit_hours * 3600)
        r = requests.get(URL + "/v2/history/candles",
            params={"symbol": "BTCUSD", "resolution": resolution,
                    "start": start, "end": end}, timeout=10)
        return r.json()["result"]
    except:
        return None

# ============================================================
# INDICATORS
# ============================================================

def ema(closes, n):
    k = 2 / (n + 1)
    e = closes[0]
    for p in closes[1:]:
        e = p * k + e * (1 - k)
    return e

def rsi(closes, n=14):
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i-1]
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    ag = sum(gains[-n:]) / n
    al = sum(losses[-n:]) / n
    if al == 0:
        return 100
    return 100 - (100 / (1 + ag / al))

def macd(closes, fast=12, slow=26, sig=9):
    e_fast = ema(closes[-slow*2:], fast)
    e_slow = ema(closes[-slow*2:], slow)
    macd_line = e_fast - e_slow
    # Signal line (EMA of last MACD values — simplified)
    return macd_line

def volume_ok(candle_data, multiplier=1.3):
    """Volume surge check — current candle vs 20-candle average"""
    vols = [float(c["volume"]) for c in candle_data]
    avg  = sum(vols[-20:]) / 20
    cur  = vols[-1]
    print(f"📊 Volume:{cur:.0f} Avg:{avg:.0f} OK:{cur > avg * multiplier}")
    return cur > avg * multiplier

# ============================================================
# SIGNAL — v2 IMPROVED
# Adds: EMA50 trend filter + Volume confirmation + MACD direction
# ============================================================

def signal(candle_data):
    closes = [float(c["close"]) for c in candle_data]
    opens  = [float(c["open"])  for c in candle_data]
    highs  = [float(c["high"])  for c in candle_data]
    lows   = [float(c["low"])   for c in candle_data]

    e9   = ema(closes, 9)
    e21  = ema(closes, 21)
    e50  = ema(closes, 50)      # NEW: Trend filter
    r    = rsi(closes)
    m    = macd(closes)         # NEW: MACD direction
    p    = closes[-1]
    o    = opens[-1]
    prev_close = closes[-2]

    green = p > o
    red   = p < o

    # Volume
    vol_good = volume_ok(candle_data)

    # Trend alignment (NEW)
    bull_trend = e9 > e21 > e50
    bear_trend = e9 < e21 < e50

    print(f"📈 EMA9:{e9:.0f} EMA21:{e21:.0f} EMA50:{e50:.0f} RSI:{r:.1f} MACD:{m:.1f} Green:{green}")

    # BUY: Trend UP + RSI healthy + MACD positive + volume surge + green candle
    if bull_trend and r >= 40 and r <= 72 and m > 0 and green and vol_good:
        return "BUY"

    # SELL: Trend DOWN + RSI healthy + MACD negative + volume surge + red candle
    elif bear_trend and r >= 28 and r <= 60 and m < 0 and red and vol_good:
        return "SELL"

    return "HOLD"

# ============================================================
# ORDER HELPERS
# ============================================================

def get_pid():
    r = requests.get(URL + "/v2/products", timeout=10)
    for x in r.json().get("result", []):
        if x.get("symbol") == "BTCUSD":
            return x.get("id")
    return None

def cancel_all_orders(pid):
    try:
        b = json.dumps({"product_id": pid,
                        "cancel_limit_orders": True,
                        "cancel_stop_orders": True})
        h = hdrs("DELETE", "/v2/orders", b)
        requests.delete(URL + "/v2/orders", headers=h, data=b, timeout=10)
        print("🗑️ Orders cancelled")
    except Exception as e:
        print("Cancel error:", e)

def place_order(pid, side, order_type, size,
                price_val=None, stop_price=None, stop_type=None):
    body = {"product_id": pid, "size": size,
            "side": side, "order_type": order_type}
    if price_val:
        body["limit_price"]      = str(round(price_val, 1))
    if stop_price:
        body["stop_price"]       = str(round(stop_price, 1))
    if stop_type:
        body["stop_order_type"]  = stop_type
    b = json.dumps(body)
    h = hdrs("POST", "/v2/orders", b)
    r = requests.post(URL + "/v2/orders", headers=h, data=b, timeout=10)
    return r.json()

# ============================================================
# TRAILING LOGIC — v2 FIXED
# Fix: Trail check BEFORE SL hit check
# New: Lock-in profit after breakeven (LOCK_PTS)
# New: 60s trail check (was 300s = too slow)
# ============================================================

def trail_monitor(pid, side, entry, size):
    global sl_count

    close_side  = "sell" if side == "buy" else "buy"
    current_sl  = round(entry - SL_PTS, 1) if side == "buy" else round(entry + SL_PTS, 1)
    next_target = round(entry + TRAIL_STEP, 1) if side == "buy" else round(entry - TRAIL_STEP, 1)
    trail_count = 0
    breakeven   = False

    print(f"🔄 Trail Monitor | Entry:{entry} | SL:{current_sl} | Target:{next_target}")

    for _ in range(1000):
        time.sleep(60)   # ✅ 60s check (was 300s)
        cp = price()
        if not cp:
            continue

        profit_pts = round(cp - entry, 1) if side == "buy" else round(entry - cp, 1)
        print(f"💹 Price:{cp} | Profit:{profit_pts:+.0f} pts | SL:{current_sl} | Next:{next_target}")

        # ─── LONG LOGIC ──────────────────────────────────────
        if side == "buy":

            # ✅ Trail check FIRST (Fixed order)
            if cp >= next_target:
                trail_count += 1
                cancel_all_orders(pid)

                if not breakeven:
                    # First trail hit → move SL to breakeven
                    current_sl = entry + 10      # Slightly above entry = guaranteed profit
                    breakeven  = True
                    print(f"✅ +{TRAIL_STEP} pts! Breakeven! New SL:{current_sl}")
                else:
                    # Subsequent trail hits → lock in profit (LOCK_PTS below trail)
                    current_sl = round(next_target - LOCK_PTS, 1)
                    print(f"🚀 Trail #{trail_count}! +{TRAIL_STEP * trail_count} pts! Lock SL:{current_sl}")

                # Place new SL order
                sl_res = place_order(pid, close_side, "limit_order",
                                     size, current_sl, current_sl, "stop_loss_order")
                print(f"🔒 New SL placed: {current_sl} OK:{sl_res.get('success')}")

                next_target = round(next_target + TRAIL_STEP, 1)
                print(f"🎯 Next Target: {next_target}")

            # SL hit check AFTER trail check
            elif cp <= current_sl:
                cancel_all_orders(pid)
                if breakeven:
                    profit = round(cp - entry, 1)
                    print(f"🎯 Exit with Profit! +{profit} pts 🔥")
                else:
                    loss_inr = round(SL_PTS * size * INR_RATE, 1)
                    print(f"🛑 SL Hit! -₹{loss_inr}")
                    sl_count += 1
                break

        # ─── SHORT LOGIC ─────────────────────────────────────
        else:

            # Trail check FIRST
            if cp <= next_target:
                trail_count += 1
                cancel_all_orders(pid)

                if not breakeven:
                    current_sl = entry - 10      # Slightly below entry
                    breakeven  = True
                    print(f"✅ +{TRAIL_STEP} pts! Breakeven! New SL:{current_sl}")
                else:
                    current_sl = round(next_target + LOCK_PTS, 1)
                    print(f"🚀 Trail #{trail_count}! +{TRAIL_STEP * trail_count} pts! Lock SL:{current_sl}")

                sl_res = place_order(pid, close_side, "limit_order",
                                     size, current_sl, current_sl, "stop_loss_order")
                print(f"🔒 New SL placed: {current_sl} OK:{sl_res.get('success')}")

                next_target = round(next_target - TRAIL_STEP, 1)
                print(f"🎯 Next Target: {next_target}")

            # SL hit check AFTER
            elif cp >= current_sl:
                cancel_all_orders(pid)
                if breakeven:
                    profit = round(entry - cp, 1)
                    print(f"🎯 Exit with Profit! +{profit} pts 🔥")
                else:
                    loss_inr = round(SL_PTS * size * INR_RATE, 1)
                    print(f"🛑 SL Hit! -₹{loss_inr}")
                    sl_count += 1
                break

    print(f"✅ Trade Done! Daily SL:{sl_count}/{MAX_SL}")

# ============================================================
# MAIN ORDER FUNCTION
# ============================================================

def order(side):
    try:
        pid   = get_pid()
        if not pid:
            print("❌ Product नहीं मिला")
            return

        entry = price()
        size  = calc_size()
        close_side = "sell" if side == "buy" else "buy"

        # Place market entry
        res = place_order(pid, side, "market_order", size)
        print(f"📌 ORDER:{side.upper()} Entry:{entry} Size:{size}")
        print(f"✅ Success:{res.get('success')}")

        if not res.get("success"):
            print("❌ Error:", res.get("error"))
            return

        time.sleep(2)

        # Place initial SL
        sl = round(entry - SL_PTS, 1) if side == "buy" else round(entry + SL_PTS, 1)
        sl_res = place_order(pid, close_side, "limit_order",
                             size, sl, sl, "stop_loss_order")
        print(f"🛡️ Initial SL:{sl} OK:{sl_res.get('success')}")

        # Start trailing monitor
        trail_monitor(pid, side, entry, size)

    except Exception as e:
        print("❌ Order Error:", e)

# ============================================================
# MAIN LOOP
# ============================================================

def run():
    global sl_count, today
    last_signal = "HOLD"
    cooldown    = 0   # Candles to skip after a trade

    print("🚀 Sniper Bot v2.0 Started!")

    while True:
        # Daily reset
        if date.today() != today:
            today       = date.today()
            sl_count    = 0
            last_signal = "HOLD"
            print("🌅 नया दिन! SL count reset.")

        # Daily SL limit
        if sl_count >= MAX_SL:
            print(f"🚫 {MAX_SL} SL hit! आज trading बंद 🔒")
            time.sleep(3600)
            continue

        # Cooldown after trade
        if cooldown > 0:
            print(f"⏳ Cooldown: {cooldown} candles बाकी")
            cooldown -= 1
            time.sleep(900)
            continue

        p = price()
        c = candles()

        if p and c and len(c) >= 55:
            s = signal(c)
            print(f"💰 Price:{p} | Signal:{s} | SL:{sl_count}/{MAX_SL}")

            if s != "HOLD" and s != last_signal:
                print(f"✅ Confirmed: {s} — Entering trade...")
                order(s.lower())
                last_signal = s
                cooldown    = 3   # 3 candles (45 min) cooldown after trade
            else:
                print("⏳ Wait...")
        else:
            print("⚠️ Data कम है, wait कर रहे हैं...")

        time.sleep(900)   # 15 min candle

run()
                  
