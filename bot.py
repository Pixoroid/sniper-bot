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
    s = hmac.new(SECRET.encode(), (m + t + p + b).encode(), hashlib.sha256).hexdigest()
    return {
        "api-key": KEY,
        "timestamp": t,
        "signature": s,
        "Content-Type": "application/json"
    }


def price():
    try:
        r = requests.get(URL + "/v2/tickers", timeout=10)
        for x in r.json()["result"]:
            if x["symbol"] == "BTCUSD":
                p = float(x.get("mark_price") or x["close"])
                print("Price: " + str(p))
                return p
    except Exception as e:
        print("Price error: " + str(e))
    return None


def get_balance():
    try:
        h = hdrs("GET", "/v2/wallet/balances", "")
        r = requests.get(URL + "/v2/wallet/balances", headers=h, timeout=10)
        data = r.json().get("result", [])

        for x in data:
            print("Wallet " + str(x.get("asset_symbol")) + ": " + str(x.get("available_balance")))

        for x in data:
            sym = x.get("asset_symbol", "")
            bal = float(x.get("available_balance", 0))
            if sym == "INR" and bal > 0:
                usd = round(bal / INR_RATE, 4)
                print("INR balance: " + str(bal) + " = $" + str(usd))
                return usd

        for x in data:
            sym = x.get("asset_symbol", "")
            bal = float(x.get("available_balance", 0))
            if sym in ["USD", "USDT", "USDC"] and bal > 0:
                print("USD balance: " + str(bal))
                return bal

        for x in data:
            sym = x.get("asset_symbol", "")
            bal = float(x.get("available_balance", 0))
            if sym == "BTC" and bal > 0:
                cp  = price() or 60000
                usd = round(bal * cp, 4)
                print("BTC balance: " + str(bal) + " = $" + str(usd))
                return usd

        if data:
            bal = float(data[0].get("available_balance", 0))
            return bal

    except Exception as e:
        print("Balance error: " + str(e))
    return 0.0


def calc_size(btc_price, balance_usd):
    position_usd = balance_usd * LEVERAGE
    size = round(position_usd / btc_price, 6)
    size = max(size, 0.001)
    print("Size: $" + str(balance_usd) + " x " + str(LEVERAGE) + " = " + str(size) + " BTC")
    return size


def get_actual_entry(pid):
    try:
        time.sleep(3)
        h = hdrs("GET", "/v2/positions", "")
        r = requests.get(URL + "/v2/positions", headers=h, timeout=10)
        for x in r.json().get("result", []):
            if x.get("product_id") == pid:
                ep = float(x.get("entry_price", 0))
                print("Entry price: " + str(ep))
                return ep
    except Exception as e:
        print("Entry error: " + str(e))
    return None


def candles(resolution="15m", limit_hours=12):
    try:
        end   = int(time.time())
        start = end - (limit_hours * 3600)
        r = requests.get(
            URL + "/v2/history/candles",
            params={"symbol": "BTCUSD", "resolution": resolution, "start": start, "end": end},
            timeout=10
        )
        data = r.json()["result"]
        if data:
            print("Candles: " + str(len(data)) + " Last: " + str(data[-1]["close"]))
        return data
    except Exception as e:
        print("Candles error: " + str(e))
    return None


def calc_rsi(closes, n=14):
    if len(closes) < n + 1:
        return 50
    gains  = []
    losses = []
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
        tr = max(h - l, abs(h - pc), abs(l - pc))
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
    print("Volume: " + str(round(cur)) + " Avg: " + str(round(avg)) + " OK: " + str(ok))
    return ok


def find_divergence(candle_data):
    if len(candle_data) < 20:
        print("Not enough candles")
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
        if recent_lows[i] < recent_lows[i-1] and recent_lows[i] < recent_lows[i+1]:
            price_lows.append((i, recent_lows[i]))
            if i < len(recent_rsi):
                rsi_lows.append((i, recent_rsi[i]))

    price_highs = []
    rsi_highs   = []
    for i in range(1, len(recent_highs)-1):
        if recent_highs[i] > recent_highs[i-1] and recent_highs[i] > recent_highs[i+1]:
            price_highs.append((i, recent_highs[i]))
            if i < len(recent_rsi):
                rsi_highs.append((i, recent_rsi[i]))

    print("RSI: " + str(round(current_rsi, 1)) + " Lows: " + str(len(price_lows)) + " Highs: " + str(len(price_highs)))

    if len(price_lows) >= 2 and len(rsi_lows) >= 2:
        p_low1     = price_lows[-2][1]
        p_low2     = price_lows[-1][1]
        r_low1     = rsi_lows[-2][1]
        r_low2     = rsi_lows[-1][1]
        swing_size = abs(p_low1 - p_low2)
        if p_low2 < p_low1 and r_low2 > r_low1 and current_rsi < 45 and vol_good and green and swing_size >= 500:
            print("BULLISH DIVERGENCE! Swing: " + str(round(swing_size)))
            return "BUY"

    if len(price_highs) >= 2 and len(rsi_highs) >= 2:
        p_hi1      = price_highs[-2][1]
        p_hi2      = price_highs[-1][1]
        r_hi1      = rsi_highs[-2][1]
        r_hi2      = rsi_highs[-1][1]
        swing_size = abs(p_hi2 - p_hi1)
        if p_hi2 > p_hi1 and r_hi2 < r_hi1 and current_rsi > 55 and vol_good and red and swing_size >= 500:
            print("BEARISH DIVERGENCE! Swing: " + str(round(swing_size)))
            return "SELL"

    curr = closes[-1]
    prev = closes[-5] if len(closes) >= 5 else closes[0]
    move = (prev - curr) / prev * 100

    if move > 1.0 and current_rsi < 50 and red:
        print("TREND SELL! Move: " + str(round(move, 1)) + "%")
        return "SELL"

    if move < -1.0 and current_rsi > 50 and green:
        print("TREND BUY! Move: " + str(round(move, 1)) + "%")
        return "BUY"

    print("No Signal. RSI: " + str(round(current_rsi, 1)) + " Move: " + str(round(move, 1)) + "%")
    return "HOLD"


def get_pid():
    try:
        r = requests.get(URL + "/v2/products", timeout=10)
        for x in r.json().get("result", []):
            if x.get("symbol") == "BTCUSD":
                return x.get("id")
    except Exception as e:
        print("PID error: " + str(e))
    return None


def cancel_all_orders(pid):
    try:
        b = json.dumps({"product_id": pid, "cancel_limit_orders": True, "cancel_stop_orders": True})
        h = hdrs("DELETE", "/v2/orders", b)
        requests.delete(URL + "/v2/orders", headers=h, data=b, timeout=10)
        print("Orders cancelled")
    except Exception as e:
        print("Cancel error: " + str(e))


def place_order(pid, side, order_type, size, price_val=None, stop_price=None, stop_type=None):
    body = {"product_id": pid, "size": size, "side": side, "order_type": order_type}
    if price_val:
        body["limit_price"] = str(round(price_val, 1))
    if stop_price:
        body["stop_price"] = str(round(stop_price, 1))
    if stop_type:
        body["stop_order_type"] = stop_type
    b = json.dumps(body)
    h = hdrs("POST", "/v2/orders", b)
    r = requests.post(URL + "/v2/orders", headers=h, data=b, timeout=10)
    return r.json()


def trade_monitor(pid, side, entry, sl, size, has_balance):
    global sl_count, consecutive_sl, daily_pnl_inr

    close_side = "sell" if side == "buy" else "buy"
    current_sl = sl
    best_price = entry
    trail_hits = 0
    sl_dist    = abs(entry - sl)

    if side == "buy":
        tp1 = round(entry + 300, 1)
        tp2 = round(entry + 600, 1)
        tp3 = round(entry + 900, 1)
    else:
        tp1 = round(entry - 300, 1)
        tp2 = round(entry - 600, 1)
        tp3 = round(entry - 900, 1)

    tp1_hit = False
    tp2_hit = False
    tp3_hit = False
    mode    = "REAL" if has_balance else "TRACKING"

    print("=" * 45)
    print(mode + " TRADE")
    print("Side: " + side.upper())
    print("Entry: " + str(entry))
    print("SL: " + str(current_sl) + " (" + str(round(sl_dist)) + " pts)")
    print("TP1: " + str(tp1) + " (+300)")
    print("TP2: " + str(tp2) + " (+600)")
    print("TP3: " + str(tp3) + " (+900)")
    print("=" * 45)

    for _ in range(5000):
        time.sleep(60)
        cp = price()
        if not cp:
            continue

        c_data = candles()
        if c_data:
            fresh_atr  = calc_atr(c_data)
            trail_dist = round(fresh_atr * ATR_TRAIL_MULT, 1)
            trail_dist = max(trail_dist, MIN_SL_PTS)
            trail_dist = min(trail_dist, MAX_SL_PTS)
        else:
            trail_dist = 300

        if side == "buy":
            profit_pts = round(cp - entry, 1)
        else:
            profit_pts = round(entry - cp, 1)

        rr = round(profit_pts / sl_dist, 2) if sl_dist > 0 else 0
        print(mode + " CP:" + str(round(cp)) + " PnL:" + str(profit_pts) + "pts RR:1:" + str(rr) + " SL:" + str(round(current_sl)))

        if side == "buy":
            if not tp1_hit and cp >= tp1:
                tp1_hit    = True
                current_sl = entry + 10
                if has_balance and pid:
                    cancel_all_orders(pid)
                    place_order(pid, close_side, "limit_order", size, current_sl, current_sl, "stop_loss_order")
                print("TP1 HIT! +300pts | SL -> Breakeven: " + str(current_sl))

            elif tp1_hit and not tp2_hit and cp >= tp2:
                tp2_hit    = True
                current_sl = entry + 300
                if has_balance and pid:
                    cancel_all_orders(pid)
                    place_order(pid, close_side, "limit_order", size, current_sl, current_sl, "stop_loss_order")
                print("TP2 HIT! +600pts | SL -> +300: " + str(current_sl))

            elif tp2_hit and not tp3_hit and cp >= tp3:
                tp3_hit    = True
                current_sl = entry + 600
                if has_balance and pid:
                    cancel_all_orders(pid)
                    place_order(pid, close_side, "limit_order", size, current_sl, current_sl, "stop_loss_order")
                print("TP3 HIT! +900pts | SL -> +600: " + str(current_sl))

            elif tp3_hit:
                if cp > best_price:
                    best_price = cp
                new_sl = round(best_price - trail_dist, 1)
                if new_sl > current_sl:
                    old_sl     = current_sl
                    current_sl = new_sl
                    trail_hits += 1
                    if has_balance and pid:
                        cancel_all_orders(pid)
                        place_order(pid, close_side, "limit_order", size, current_sl, current_sl, "stop_loss_order")
                    print("Trail #" + str(trail_hits) + " SL: " + str(old_sl) + " -> " + str(current_sl))

            if cp <= current_sl:
                if has_balance and pid:
                    cancel_all_orders(pid)
                final_pts = round(current_sl - entry, 1)
                daily_pnl_inr += final_pts * 0.001
                rr_f = round(final_pts / sl_dist, 2) if sl_dist > 0 else 0
                result = "PROFIT EXIT" if final_pts > 0 else "SL HIT"
                print("=" * 45)
                print(result + " " + mode)
                print("Side: BUY | Entry: " + str(entry) + " | Exit: " + str(current_sl))
                print("PnL: " + str(final_pts) + " pts | RR: 1:" + str(rr_f))
                print("TP1: " + ("HIT" if tp1_hit else "Miss") + " TP2: " + ("HIT" if tp2_hit else "Miss") + " TP3: " + ("HIT" if tp3_hit else "Miss"))
                print("Trails: " + str(trail_hits) + " | Daily PnL: " + str(round(daily_pnl_inr)))
                print("=" * 45)
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
                    place_order(pid, close_side, "limit_order", size, current_sl, current_sl, "stop_loss_order")
                print("TP1 HIT! +300pts | SL -> Breakeven: " + str(current_sl))

            elif tp1_hit and not tp2_hit and cp <= tp2:
                tp2_hit    = True
                current_sl = entry - 300
                if has_balance and pid:
                    cancel_all_orders(pid)
                    place_order(pid, close_side, "limit_order", size, current_sl, current_sl, "stop_loss_order")
                print("TP2 HIT! +600pts | SL -> +300: " + str(current_sl))

            elif tp2_hit and not tp3_hit and cp <= tp3:
                tp3_hit    = True
                current_sl = entry - 600
                if has_balance and pid:
                    cancel_all_orders(pid)
                    place_order(pid, close_side, "limit_order", size, current_sl, current_sl, "stop_loss_order")
                print("TP3 HIT! +900pts | SL -> +600: " + str(current_sl))

            elif tp3_hit:
                if cp < best_price:
                    best_price = cp
                new_sl = round(best_price + trail_dist, 1)
                if new_sl < current_sl:
                    old_sl     = current_sl
                    current_sl = new_sl
                    trail_hits += 1
                    if has_balance and pid:
                        cancel_all_orders(pid)
                        place_order(pid, close_side, "limit_order", size, current_sl, current_sl, "stop_loss_order")
                    print("Trail #" + str(trail_hits) + " SL: " + str(old_sl) + " -> " + str(current_sl))

            if cp >= current_sl:
                if has_balance and pid:
                    cancel_all_orders(pid)
                final_pts = round(entry - current_sl, 1)
                daily_pnl_inr += final_pts * 0.001
                rr_f = round(final_pts / sl_dist, 2) if sl_dist > 0 else 0
                result = "PROFIT EXIT" if final_pts > 0 else "SL HIT"
                print("=" * 45)
                print(result + " " + mode)
                print("Side: SELL | Entry: " + str(entry) + " | Exit: " + str(current_sl))
                print("PnL: " + str(final_pts) + " pts | RR: 1:" + str(rr_f))
                print("TP1: " + ("HIT" if tp1_hit else "Miss") + " TP2: " + ("HIT" if tp2_hit else "Miss") + " TP3: " + ("HIT" if tp3_hit else "Miss"))
                print("Trails: " + str(trail_hits) + " | Daily PnL: " + str(round(daily_pnl_inr)))
                print("=" * 45)
                if final_pts <= 0:
                    sl_count       += 1
                    consecutive_sl += 1
                else:
                    consecutive_sl = 0
                break


def main():
    global today, sl_count, consecutive_sl, daily_pnl_inr

    print("Sniper Bot Starting...")
    print("Date: " + str(date.today()))
    print("Leverage: " + str(LEVERAGE) + "x")
    print("Max SL: " + str(MAX_SL) + " | Consecutive: " + str(MAX_CONSECUTIVE_SL))
    print("=" * 45)

    pid = get_pid()
    print("Product ID: " + str(pid))

    while True:
        try:
            if date.today() != today:
                today          = date.today()
                sl_count       = 0
                consecutive_sl = 0
                daily_pnl_inr  = 0.0
                print("Daily Reset - " + str(today))

            if sl_count >= MAX_SL:
                print("Max SL reached. Waiting 1hr...")
                time.sleep(3600)
                continue

            if consecutive_sl >= MAX_CONSECUTIVE_SL:
                print("Consecutive SL limit. Waiting 2hr...")
                time.sleep(7200)
                consecutive_sl = 0
                continue

            if daily_pnl_inr <= -DAILY_LOSS_LIMIT:
                print("Daily loss limit hit. Waiting 1hr...")
                time.sleep(3600)
                continue

            print("Scanning... " + time.strftime("%H:%M:%S"))
            data = candles()
            if not data:
                time.sleep(60)
                continue

            signal = find_divergence(data)

            if signal == "HOLD":
                time.sleep(300)
                continue

            cp  = price()
            bal = get_balance()
            has_balance = bal > 1.0

            if not cp:
                time.sleep(60)
                continue

            atr    = calc_atr(data)
            sl_pts = round(atr * ATR_SL_MULT, 1)
            sl_pts = max(sl_pts, MIN_SL_PTS)
            sl_pts = min(sl_pts, MAX_SL_PTS)

            size = calc_size(cp, bal) if has_balance else 0.001

            if signal == "BUY":
                sl = round(cp - sl_pts, 1)
                print("BUY Signal! CP: " + str(cp) + " SL: " + str(sl))
                if has_balance and pid:
                    place_order(pid, "buy", "market_order", size)
                entry = get_actual_entry(pid) or cp
                trade_monitor(pid, "buy", entry, sl, size, has_balance)

            elif signal == "SELL":
                sl = round(cp + sl_pts, 1)
                print("SELL Signal! CP: " + str(cp) + " SL: " + str(sl))
                if has_balance and pid:
                    place_order(pid, "sell", "market_order", size)
                entry = get_actual_entry(pid) or cp
                trade_monitor(pid, "sell", entry, sl, size, has_balance)

            time.sleep(60)

        except KeyboardInterrupt:
            print("Bot stopped.")
            break
        except Exception as e:
            print("Main loop error: " + str(e))
            time.sleep(60)


if __name__ == "__main__":
    main()
                                                                        "limit_order", size,
                                    
