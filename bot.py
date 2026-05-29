import requests, hmac, hashlib, time, json, os
from datetime import date

KEY    = "afr1UynKRx9xZiwOLlioGEqQAP4qTxÀ"
SECRET = "0EIc661e8iXKOgi3EqLbZCKVK82BMXSaBsCg8JiJT8VwaLOa90utgEFKA85c"
URL    = "https://cdn-ind.testnet.deltaex.org"

LEVERAGE   = 5
MAX_SL     = 3
SL_PTS     = 150
TP1_PTS    = 300    # 2x SL
TP2_PTS    = 450    # 3x SL
TP3_PTS    = 600    # 4x SL
TRAIL_STEP = 150    # हर 150 pts पर trail

sl_count = 0
today    = date.today()

# ============================================================
# HELPERS
# ============================================================

def hdrs(m, p, b=""):
    t = str(int(time.time()))
    s = hmac.new(SECRET.encode(),
                 (m + t + p + b).encode(),
                 hashlib.sha256).hexdigest()
    return {"api-key": KEY, "timestamp": t,
            "signature": s, "Content-Type": "application/json"}

def price():
    try:
        r = requests.get(URL + "/v2/tickers", timeout=10)
        for x in r.json()["result"]:
            if x["symbol"] == "BTCUSD":
                p = float(x.get("mark_price") or x["close"])
                print(f"💲 Price:{p}")
                return p
    except Exception as e:
        print(f"❌ Price error: {e}")
        return None

def get_balance():
    try:
        h = hdrs("GET", "/v2/wallet/balances", "")
        r = requests.get(URL + "/v2/wallet/balances",
                         headers=h, timeout=10)
        data = r.json().get("result", [])
        for x in data:
            sym = x.get("asset_symbol", "")
            if sym in ["USD", "USDT", "USDC", "BTC"]:
                bal = float(x.get("available_balance", 0))
                print(f"✅ Balance: ${bal}")
                return bal
        if data:
            bal = float(data[0].get("available_balance", 0))
            return bal
    except Exception as e:
        print(f"❌ Balance error: {e}")
    return None

def calc_size(btc_price):
    balance = get_balance()
    if not balance or balance <= 0:
        print("❌ Balance नहीं मिला!")
        return None
    position_usd = balance * LEVERAGE
    size         = position_usd / btc_price
    size         = round(size, 6)
    size         = max(size, 0.001)
    print(f"💰 Balance:${balance:.4f} × {LEVERAGE}x"
          f" = ${position_usd:.4f}")
    print(f"📦 Size:{size} BTC")
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
                print(f"✅ Actual Entry: {ep}")
                return ep
    except Exception as e:
        print(f"❌ Entry error: {e}")
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
    for c in closes[1:]:
        e = c * k + e * (1 - k)
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

def macd(closes, fast=12, slow=26):
    e_fast = ema(closes[-slow*2:], fast)
    e_slow = ema(closes[-slow*2:], slow)
    return e_fast - e_slow

def volume_ok(candle_data, multiplier=1.0):
    vols = [float(c["volume"]) for c in candle_data]
    avg  = sum(vols[-20:]) / 20
    cur  = vols[-1]
    ok   = cur > avg * multiplier
    print(f"📊 Vol:{cur:.0f} Avg:{avg:.0f} OK:{ok}")
    return ok

# ============================================================
# SIGNAL — EMA9 × EMA50 CROSSOVER
# ============================================================

def signal(candle_data):
    closes = [float(c["close"]) for c in candle_data]
    opens  = [float(c["open"])  for c in candle_data]

    # Current EMA
    curr_e9  = ema(closes, 9)
    curr_e50 = ema(closes, 50)

    # Previous candle EMA
    prev_e9  = ema(closes[:-1], 9)
    prev_e50 = ema(closes[:-1], 50)

    r = rsi(closes)
    m = macd(closes)
    p = closes[-1]
    o = opens[-1]

    green = p > o
    red   = p < o
    vol_good = volume_ok(candle_data)

    print(f"📈 E9:{curr_e9:.0f} E50:{curr_e50:.0f} "
          f"PrevE9:{prev_e9:.0f} PrevE50:{prev_e50:.0f} "
          f"RSI:{r:.1f} MACD:{m:.1f}")

    # ✅ BUY — EMA9 ने EMA50 को नीचे से ऊपर cross किया
    if (prev_e9 < prev_e50 and curr_e9 > curr_e50
            and r >= 40 and m > 0 and green and vol_good):
        print("🟢 BUY CROSS DETECTED!")
        return "BUY"

    # ✅ SELL — EMA9 ने EMA50 को ऊपर से नीचे cross किया
    elif (prev_e9 > prev_e50 and curr_e9 < curr_e50
            and r <= 60 and m < 0 and red and vol_good):
        print("🔴 SELL CROSS DETECTED!")
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
        requests.delete(URL + "/v2/orders",
                        headers=h, data=b, timeout=10)
        print("🗑️ Cancelled")
    except Exception as e:
        print(f"Cancel error: {e}")

def place_order(pid, side, order_type, size,
                price_val=None, stop_price=None, stop_type=None):
    body = {"product_id": pid, "size": size,
            "side": side, "order_type": order_type}
    if price_val:
        body["limit_price"]     = str(round(price_val, 1))
    if stop_price:
        body["stop_price"]      = str(round(stop_price, 1))
    if stop_type:
        body["stop_order_type"] = stop_type
    b = json.dumps(body)
    h = hdrs("POST", "/v2/orders", b)
    r = requests.post(URL + "/v2/orders",
                      headers=h, data=b, timeout=10)
    return r.json()

# ============================================================
# TRAIL MONITOR — 2x 3x 4x TP
# ============================================================

def trail_monitor(pid, side, entry, size):
    global sl_count

    close_side  = "sell" if side == "buy" else "buy"
    current_sl  = round(entry - SL_PTS, 1) if side == "buy" \
                  else round(entry + SL_PTS, 1)
    trail_count = 0

    # TP levels
    tp1 = round(entry + TP1_PTS, 1) if side == "buy" \
          else round(entry - TP1_PTS, 1)
    tp2 = round(entry + TP2_PTS, 1) if side == "buy" \
          else round(entry - TP2_PTS, 1)
    tp3 = round(entry + TP3_PTS, 1) if side == "buy" \
          else round(entry - TP3_PTS, 1)

    tp1_hit = False
    tp2_hit = False
    tp3_hit = False

    print(f"🔄 Entry:{entry} | SL:{current_sl}")
    print(f"🎯 TP1(2x):{tp1} TP2(3x):{tp2} TP3(4x):{tp3}")

    for _ in range(1000):
        time.sleep(60)
        cp = price()
        if not cp:
            continue

        profit_pts = round(cp - entry, 1) if side == "buy" \
                     else round(entry - cp, 1)
        print(f"💹 CP:{cp} | P&L:{profit_pts:+.0f} | SL:{current_sl}")

        # ── BUY LOGIC ────────────────────────────────
        if side == "buy":

            # TP1 hit — 2x — Breakeven
            if not tp1_hit and cp >= tp1:
                tp1_hit    = True
                current_sl = entry + 10
                cancel_all_orders(pid)
                place_order(pid, close_side, "limit_order",
                            size, current_sl, current_sl,
                            "stop_loss_order")
                print(f"✅ TP1 (2x) Hit! SL→Breakeven:{current_sl}")

            # TP2 hit — 3x — Lock 300 pts
            elif tp1_hit and not tp2_hit and cp >= tp2:
                tp2_hit    = True
                current_sl = entry + TP1_PTS
                cancel_all_orders(pid)
                place_order(pid, close_side, "limit_order",
                            size, current_sl, current_sl,
                            "stop_loss_order")
                print(f"🚀 TP2 (3x) Hit! SL→+{TP1_PTS}:{current_sl}")

            # TP3 hit — 4x — Lock 450 pts
            elif tp2_hit and not tp3_hit and cp >= tp3:
                tp3_hit    = True
                current_sl = entry + TP2_PTS
                cancel_all_orders(pid)
                place_order(pid, close_side, "limit_order",
                            size, current_sl, current_sl,
                            "stop_loss_order")
                print(f"🔥 TP3 (4x) Hit! SL→+{TP2_PTS}:{current_sl}")

            # TP3 के बाद — हर 150 pts पर trail
            elif tp3_hit:
                trail_count += 1
                new_sl = round(cp - TRAIL_STEP, 1)
                if new_sl > current_sl:
                    current_sl = new_sl
                    cancel_all_orders(pid)
                    place_order(pid, close_side, "limit_order",
                                size, current_sl, current_sl,
                                "stop_loss_order")
                    print(f"🚀 Trail#{trail_count} SL:{current_sl}")

            # SL Hit
            if cp <= current_sl:
                cancel_all_orders(pid)
                if tp1_hit:
                    profit = round(cp - entry, 1)
                    print(f"🎯 Exit Profit! +{profit} pts 🔥")
                else:
                    print(f"🛑 SL Hit! -150 pts")
                    sl_count += 1
                break

        # ── SELL LOGIC ───────────────────────────────
        else:

            # TP1 — 2x — Breakeven
            if not tp1_hit and cp <= tp1:
                tp1_hit    = True
                current_sl = entry - 10
                cancel_all_orders(pid)
                place_order(pid, close_side, "limit_order",
                            size, current_sl, current_sl,
                            "stop_loss_order")
                print(f"✅ TP1 (2x) Hit! SL→Breakeven:{current_sl}")

            # TP2 — 3x — Lock 300 pts
            elif tp1_hit and not tp2_hit and cp <= tp2:
                tp2_hit    = True
                current_sl = entry - TP1_PTS
                cancel_all_orders(pid)
                place_order(pid, close_side, "limit_order",
                            size, current_sl, current_sl,
                            "stop_loss_order")
                print(f"🚀 TP2 (3x) Hit! SL→+{TP1_PTS}:{current_sl}")

            # TP3 — 4x — Lock 450 pts
            elif tp2_hit and not tp3_hit and cp <= tp3:
                tp3_hit    = True
                current_sl = entry - TP2_PTS
                cancel_all_orders(pid)
                place_order(pid, close_side, "limit_order",
                            size, current_sl, current_sl,
                            "stop_loss_order")
                print(f"🔥 TP3 (4x) Hit! SL→+{TP2_PTS}:{current_sl}")

            # TP3 के बाद trail
            elif tp3_hit:
                trail_count += 1
                new_sl = round(cp + TRAIL_STEP, 1)
                if new_sl < current_sl:
                    current_sl = new_sl
                    cancel_all_orders(pid)
                    place_order(pid, close_side, "limit_order",
                                size, current_sl, current_sl,
                                "stop_loss_order")
                    print(f"🚀 Trail#{trail_count} SL:{current_sl}")

            # SL Hit
            if cp >= current_sl:
                cancel_all_orders(pid)
                if tp1_hit:
                    profit = round(entry - cp, 1)
                    print(f"🎯 Exit Profit! +{profit} pts 🔥")
                else:
                    print(f"🛑 SL Hit! -150 pts")
                    sl_count += 1
                break

    print(f"✅ Trade Done! SL:{sl_count}/{MAX_SL}")

# ============================================================
# MAIN ORDER
# ============================================================

def order(side):
    try:
        pid = get_pid()
        if not pid:
            print("❌ Product नहीं मिला")
            return

        cp = price()
        if not cp:
            print("❌ Price नहीं मिला")
            return

        size = calc_size(cp)
        if not size:
            print("❌ Size नहीं मिला")
            return

        close_side = "sell" if side == "buy" else "buy"

        res = place_order(pid, side, "market_order", size)
        print(f"📌 {side.upper()} | Price:{cp} | Size:{size} BTC")

        if not res.get("success"):
            print(f"❌ Failed: {res.get('error')}")
            return

        entry = get_actual_entry(pid) or cp
        print(f"📍 Entry: {entry}")

        sl = round(entry - SL_PTS, 1) if side == "buy" \
             else round(entry + SL_PTS, 1)
        sl_res = place_order(pid, close_side, "limit_order",
                             size, sl, sl, "stop_loss_order")
        print(f"🛡️ SL:{sl} OK:{sl_res.get('success')}")

        trail_monitor(pid, side, entry, size)

    except Exception as e:
        print(f"❌ Order Error: {e}")

# ============================================================
# MAIN LOOP
# ============================================================

def run():
    global sl_count, today
    last_signal = "HOLD"
    cooldown    = 0

    print("🚀 Sniper Bot v4.0")
    print(f"⚙️  SL:150 | TP1:2x | TP2:3x | TP3:4x | Trail:∞")
    print(f"📊 Strategy: EMA9 × EMA50 Crossover")

    while True:
        if date.today() != today:
            today       = date.today()
            sl_count    = 0
            last_signal = "HOLD"
            print("🌅 नया दिन! Reset.")

        if sl_count >= MAX_SL:
            print(f"🚫 {MAX_SL} SL hit! बंद 🔒")
            time.sleep(3600)
            continue

        if cooldown > 0:
            print(f"⏳ Cooldown:{cooldown} बाकी")
            cooldown -= 1
            time.sleep(900)
            continue

        cp = price()
        c  = candles()

        if cp and c and len(c) >= 55:
            s = signal(c)
            print(f"💰 Price:{cp} Signal:{s} SL:{sl_count}/{MAX_SL}")

            if s != "HOLD" and s != last_signal:
                print(f"✅ {s} — Trade!")
                order(s.lower())
                last_signal = s
                cooldown    = 3
            else:
                print("⏳ Wait...")
        else:
            print("⚠️ Data कम...")

        time.sleep(900)

run()
