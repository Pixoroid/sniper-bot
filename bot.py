import requests, hmac, hashlib, time, json, os
from datetime import date, datetime, timezone, timedelta

KEY    = "afr1UynKRx9xZiwOLlioGEqQAP4qTxÀ"
SECRET = "0EIc661e8iXKOgi3EqLbZCKVK82BMXSaBsCg8JiJT8VwaLOa90utgEFKA85c"
URL    = "https://cdn-ind.testnet.deltaex.org"

LEVERAGE            = 5
MAX_SL              = 3
TP1_PTS             = 300
TP2_PTS             = 600
TP3_PTS             = 900
TRAIL_STEP          = 300
MAX_CONSECUTIVE_SL  = 2
DAILY_PROFIT_TARGET = 500
DAILY_LOSS_LIMIT    = 300
INR_RATE            = 85

TRADE_TIMES = [
    (9,  0, 12, 0),
    (19, 0, 23, 0),
]

sl_count       = 0
consecutive_sl = 0
daily_pnl_inr  = 0.0
today          = date.today()
last_signal    = "HOLD"

def is_trade_time():
    utc_now = datetime.now(timezone.utc)
    ist_now = utc_now + timedelta(hours=5, minutes=30)
    h = ist_now.hour
    m = ist_now.minute
    for (sh, sm, eh, em) in TRADE_TIMES:
        start = sh * 60 + sm
        end   = eh * 60 + em
        curr  = h  * 60 + m
        if start <= curr <= end:
            print(f"✅ Trade Time:{h:02d}:{m:02d} IST")
            return True
    print(f"⏰ Not Trade Time:{h:02d}:{m:02d} IST")
    return False

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
        r = requests.get(URL + "/v2/tickers", timeout=10)
        for x in r.json()["result"]:
            if x["symbol"] == "BTCUSD":
                p = float(x.get("mark_price") or x["close"])
                print(f"💲 Price:{p}")
                return p
    except Exception as e:
        print(f"❌ Price error:{e}")
        return None

def get_balance():
    try:
        h    = hdrs("GET", "/v2/wallet/balances", "")
        r    = requests.get(URL + "/v2/wallet/balances",
                            headers=h, timeout=10)
        data = r.json().get("result", [])
        for x in data:
            sym = x.get("asset_symbol", "")
            if sym in ["USD", "USDT", "USDC", "BTC"]:
                bal = float(x.get("available_balance", 0))
                print(f"✅ Balance:${bal}")
                return bal
        if data:
            return float(data[0].get("available_balance", 0))
    except Exception as e:
        print(f"❌ Balance error:{e}")
    return None

def calc_size(btc_price):
    balance = get_balance()
    if not balance or balance <= 0:
        print("❌ Balance नहीं मिला!")
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
        print(f"❌ Entry error:{e}")
    return None

def candles(resolution="15m", limit_hours=72):
    try:
        end   = int(time.time())
        start = end - (limit_hours * 3600)
        r     = requests.get(URL + "/v2/history/candles",
                    params={"symbol": "BTCUSD",
                            "resolution": resolution,
                            "start": start,
                            "end": end},
                    timeout=10)
        data  = r.json()["result"]
        print(f"📊 {resolution} Candles:{len(data)}")
        return data
    except Exception as e:
        print(f"❌ Candles error:{e}")
        return None

def ema(closes, n):
    if len(closes) < n:
        return closes[-1]
    k = 2 / (n + 1)
    e = sum(closes[:n]) / n
    for c in closes[n:]:
        e = c * k + e * (1 - k)
    return e

def atr(candle_data, n=14):
    trs = []
    for i in range(1, len(candle_data)):
        h  = float(candle_data[i]["high"])
        l  = float(candle_data[i]["low"])
        pc = float(candle_data[i-1]["close"])
        tr = max(h - l, abs(h - pc), abs(l - pc))
        trs.append(tr)
    if len(trs) < n:
        return 200
    return sum(trs[-n:]) / n

def volume_ok(candle_data, multiplier=2.0):
    vols = [float(c["volume"]) for c in candle_data]
    avg  = sum(vols[-20:]) / 20
    cur  = vols[-1]
    ok   = cur > avg * multiplier
    print(f"📊 Vol:{cur:.0f} Avg:{avg:.0f} OK:{ok}")
    return ok

def hourly_trend():
    try:
        c1h = candles(resolution="1h", limit_hours=200)
        if not c1h or len(c1h) < 50:
            return "NEUTRAL"
        closes = [float(c["close"]) for c in c1h]
        e9     = ema(closes, 9)
        e50    = ema(closes, 50)
        if e9 > e50:
            print(f"📅 1hr:BULL E9:{e9:.0f} E50:{e50:.0f}")
            return "BULL"
        else:
            print(f"📅 1hr:BEAR E9:{e9:.0f} E50:{e50:.0f}")
            return "BEAR"
    except Exception as e:
        print(f"❌ 1hr error:{e}")
        return "NEUTRAL"

def signal(candle_data):
    if len(candle_data) < 60:
        print("⚠️ कम candles!")
        return "HOLD", 300

    closes = [float(c["close"]) for c in candle_data]
    opens  = [float(c["open"])  for c in candle_data]

    curr_e9  = ema(closes, 9)
    curr_e50 = ema(closes, 50)
    prev_e9  = ema(closes[:-1], 9)
    prev_e50 = ema(closes[:-1], 50)

    p     = closes[-1]
    o     = opens[-1]
    green = p > o
    red   = p < o

    vol_good    = volume_ok(candle_data)
    trend_1h    = hourly_trend()
    current_atr = atr(candle_data)
    dynamic_sl  = round(current_atr * 1.5, 1)

    print(f"📈 E9:{curr_e9:.1f} E50:{curr_e50:.1f} "
          f"PrevE9:{prev_e9:.1f} PrevE50:{prev_e50:.1f}")
    print(f"🕯️ P:{p:.1f} G:{green} R:{red} "
          f"Vol:{vol_good} 1hr:{trend_1h} "
          f"ATR:{current_atr:.1f} DSL:{dynamic_sl}")

    buy_cross  = prev_e9 < prev_e50 and curr_e9 > curr_e50
    sell_cross = prev_e9 > prev_e50 and curr_e9 < curr_e50

    if (buy_cross and green
            and vol_good and trend_1h == "BULL"):
        print("🟢 BUY CONFIRMED!")
        return "BUY", dynamic_sl

    elif (sell_cross and red
            and vol_good and trend_1h == "BEAR"):
        print("🔴 SELL CONFIRMED!")
        return "SELL", dynamic_sl

    return "HOLD", dynamic_sl

def get_pid():
    try:
        r = requests.get(URL + "/v2/products", timeout=10)
        for x in r.json().get("result", []):
            if x.get("symbol") == "BTCUSD":
                return x.get("id")
    except Exception as e:
        print(f"❌ PID error:{e}")
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
        print(f"Cancel error:{e}")

def place_order(pid, side, order_type, size,
                price_val=None, stop_price=None,
                stop_type=None):
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

def trail_monitor(pid, side, entry, size, sl_pts):
    global sl_count, consecutive_sl, daily_pnl_inr

    close_side = "sell" if side == "buy" else "buy"
    current_sl = round(entry - sl_pts, 1) if side == "buy" \
                 else round(entry + sl_pts, 1)

    tp1 = round(entry + TP1_PTS, 1) if side == "buy" \
          else round(entry - TP1_PTS, 1)
    tp2 = round(entry + TP2_PTS, 1) if side == "buy" \
          else round(entry - TP2_PTS, 1)
    tp3 = round(entry + TP3_PTS, 1) if side == "buy" \
          else round(entry - TP3_PTS, 1)

    tp1_hit   = False
    tp2_hit   = False
    tp3_hit   = False
    remaining = size
    s1        = round(size * 0.25, 6)
    s2        = round(size * 0.25, 6)
    s3        = round(size * 0.25, 6)

    print(f"🔄 Entry:{entry} SL:{current_sl}")
    print(f"🎯 TP1:{tp1} TP2:{tp2} TP3:{tp3}")
    print(f"📦 Size:{size} 25%:{s1}")

    for _ in range(2000):
        time.sleep(60)
        cp = price()
        if not cp:
            continue

        profit_pts = round(cp - entry, 1) if side == "buy" \
                     else round(entry - cp, 1)
        profit_inr = round(profit_pts * remaining
                           * INR_RATE, 1)
        print(f"💹 CP:{cp} P&L:{profit_pts:+.0f}pts "
              f"₹{profit_inr:+.0f} SL:{current_sl} "
              f"Rem:{remaining}")

        if side == "buy":

            if not tp1_hit and cp >= tp1:
                tp1_hit   = True
                remaining = round(remaining - s1, 6)
                place_order(pid, close_side,
                            "market_order", s1)
                current_sl = entry + 10
                cancel_all_orders(pid)
                if remaining > 0:
                    place_order(pid, close_side,
                                "limit_order", remaining,
                                current_sl, current_sl,
                                "stop_loss_order")
                pnl = round(TP1_PTS * s1 * INR_RATE, 1)
                daily_pnl_inr += pnl
                print(f"✅ TP1! +₹{pnl} "
                      f"BE:{current_sl} Rem:{remaining}")

            elif tp1_hit and not tp2_hit and cp >= tp2:
                tp2_hit   = True
                remaining = round(remaining - s2, 6)
                place_order(pid, close_side,
                            "market_order", s2)
                current_sl = entry + TP1_PTS
                cancel_all_orders(pid)
                if remaining > 0:
                    place_order(pid, close_side,
                                "limit_order", remaining,
                                current_sl, current_sl,
                                "stop_loss_order")
                pnl = round(TP2_PTS * s2 * INR_RATE, 1)
                daily_pnl_inr += pnl
                print(f"🚀 TP2! +₹{pnl} "
                      f"Lock:{current_sl} Rem:{remaining}")

            elif tp2_hit and not tp3_hit and cp >= tp3:
                tp3_hit   = True
                remaining = round(remaining - s3, 6)
                place_order(pid, close_side,
                            "market_order", s3)
                current_sl = entry + TP2_PTS
                cancel_all_orders(pid)
                if remaining > 0:
                    place_order(pid, close_side,
                                "limit_order", remaining,
                                current_sl, current_sl,
                                "stop_loss_order")
                pnl = round(TP3_PTS * s3 * INR_RATE, 1)
                daily_pnl_inr += pnl
                print(f"🔥 TP3! +₹{pnl} "
                      f"Lock:{current_sl} Rem:{remaining}")

            elif tp3_hit and remaining > 0:
                new_sl = round(cp - TRAIL_STEP, 1)
                if new_sl > current_sl:
                    current_sl = new_sl
                    cancel_all_orders(pid)
                    place_order(pid, close_side,
                                "limit_order", remaining,
                                current_sl, current_sl,
                                "stop_loss_order")
                    print(f"🚀 Trail SL:{current_sl}")

            if cp <= current_sl and remaining > 0:
                cancel_all_orders(pid)
                pnl = round(profit_pts * remaining
                            * INR_RATE, 1)
                daily_pnl_inr += pnl
                if tp1_hit:
                    print(f"🎯 Exit! "
                          f"+{profit_pts}pts ₹{pnl:+.0f}🔥")
                    consecutive_sl = 0
                else:
                    print(f"🛑 SL Hit! ₹{pnl:.0f}")
                    sl_count       += 1
                    consecutive_sl += 1
                break

        else:

            if not tp1_hit and cp <= tp1:
                tp1_hit   = True
                remaining = round(remaining - s1, 6)
                place_order(pid, close_side,
                            "market_order", s1)
                current_sl = entry - 10
                cancel_all_orders(pid)
                if remaining > 0:
                    place_order(pid, close_side,
                                "limit_order", remaining,
                                current_sl, current_sl,
                                "stop_loss_order")
                pnl = round(TP1_PTS * s1 * INR_RATE, 1)
                daily_pnl_inr += pnl
                print(f"✅ TP1! +₹{pnl} "
                      f"BE:{current_sl} Rem:{remaining}")

            elif tp1_hit and not tp2_hit and cp <= tp2:
                tp2_hit   = True
                remaining = round(remaining - s2, 6)
                place_order(pid, close_side,
                            "market_order", s2)
                current_sl = entry - TP1_PTS
                cancel_all_orders(pid)
                if remaining > 0:
                    place_order(pid, close_side,
                                "limit_order", remaining,
                                current_sl, current_sl,
                                "stop_loss_order")
                pnl = round(TP2_PTS * s2 * INR_RATE, 1)
                daily_pnl_inr += pnl
                print(f"🚀 TP2! +₹{pnl} "
                      f"Lock:{current_sl} Rem:{remaining}")

            elif tp2_hit and not tp3_hit and cp <= tp3:
                tp3_hit   = True
                remaining = round(remaining - s3, 6)
                place_order(pid, close_side,
                            "market_order", s3)
                current_sl = entry - TP2_PTS
                cancel_all_orders(pid)
                if remaining > 0:
                    place_order(pid, close_side,
                                "limit_order", remaining,
                                current_sl, current_sl,
                                "stop_loss_order")
                pnl = round(TP3_PTS * s3 * INR_RATE, 1)
                daily_pnl_inr += pnl
                print(f"🔥 TP3! +₹{pnl} "
                      f"Lock:{current_sl} Rem:{remaining}")

            elif tp3_hit and remaining > 0:
                new_sl = round(cp + TRAIL_STEP, 1)
                if new_sl < current_sl:
                    current_sl = new_sl
                    cancel_all_orders(pid)
                    place_order(pid, close_side,
                                "limit_order", remaining,
                                current_sl, current_sl,
                                "stop_loss_order")
                    print(f"🚀 Trail SL:{current_sl}")

            if cp >= current_sl and remaining > 0:
                cancel_all_orders(pid)
                pnl = round(profit_pts * remaining
                            * INR_RATE, 1)
                daily_pnl_inr += pnl
                if tp1_hit:
                    print(f"🎯 Exit! "
                          f"+{profit_pts}pts ₹{pnl:+.0f}🔥")
                    consecutive_sl = 0
                else:
                    print(f"🛑 SL Hit! ₹{pnl:.0f}")
                    sl_count       += 1
                    consecutive_sl += 1
                break

    print(f"✅ Done! SL:{sl_count}/{MAX_SL} "
          f"Daily:₹{daily_pnl_inr:+.0f}")

def order(side, dynamic_sl):
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
        res        = place_order(pid, side,
                                 "market_order", size)
        print(f"📌 {side.upper()} Price:{cp} Size:{size}")

        if not res.get("success"):
            print(f"❌ Failed:{res.get('error')}")
            return

        entry = get_actual_entry(pid) or cp
        print(f"📍 Entry:{entry}")

        sl = round(entry - dynamic_sl, 1) if side == "buy" \
             else round(entry + dynamic_sl, 1)
        sl_res = place_order(pid, close_side,
                             "limit_order", size,
                             sl, sl, "stop_loss_order")
        print(f"🛡️ SL:{sl} OK:{sl_res.get('success')}")

        trail_monitor(pid, side, entry, size, dynamic_sl)

    except Exception as e:
        print(f"❌ Order Error:{e}")

def run():
    global sl_count, consecutive_sl
    global daily_pnl_inr, today, last_signal

    cooldown = 0

    print("🚀 Sniper Bot v7.0 — PROFESSIONAL")
    print("⚙️  Time+Partial+ConsSL+DailyPnL")

    while True:

        if date.today() != today:
            today          = date.today()
            sl_count       = 0
            consecutive_sl = 0
            daily_pnl_inr  = 0.0
            last_signal    = "HOLD"
            print("🌅 नया दिन! Reset.")

        if daily_pnl_inr >= DAILY_PROFIT_TARGET:
            print(f"🎯 Target! ₹{daily_pnl_inr:.0f} बंद")
            time.sleep(3600)
            continue

        if daily_pnl_inr <= -DAILY_LOSS_LIMIT:
            print(f"🛑 Loss! ₹{daily_pnl_inr:.0f} बंद")
            time.sleep(3600)
            continue

        if sl_count >= MAX_SL:
            print(f"🚫 {MAX_SL} SL! बंद 🔒")
            time.sleep(3600)
            continue

        if consecutive_sl >= MAX_CONSECUTIVE_SL:
            print(f"⛔ Consecutive SL! 2hr Rest")
            consecutive_sl = 0
            time.sleep(7200)
            continue

        if cooldown > 0:
            print(f"⏳ Cooldown:{cooldown} बाकी")
            cooldown -= 1
            time.sleep(300)
            continue

        if not is_trade_time():
            time.sleep(300)
            continue

        cp = price()
        c  = candles()

        if cp and c and len(c) >= 60:
            s, dsl = signal(c)
            print(f"💰 Price:{cp} Signal:{s} "
                  f"SL:{sl_count}/{MAX_SL} "
                  f"Daily:₹{daily_pnl_inr:+.0f}")

            if s != "HOLD" and s != last_signal:
                print(f"✅ {s} — Trade!")
                order(s.lower(), dsl)
                last_signal = s
                cooldown    = 3
            else:
                print("⏳ Wait...")
        else:
            print(f"⚠️ Data:{len(c) if c else 0}")

        time.sleep(300)

run()
