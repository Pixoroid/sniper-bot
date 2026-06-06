import requests, hmac, hashlib, time, json, os
from datetime import date, datetime, timezone, timedelta

KEY    = "afr1UynKRx9xZiwOLlioGEqQAP4qTxÀ"
SECRET = "0EIc661e8iXKOgi3EqLbZCKVK82BMXSaBsCg8JiJT8VwaLOa90utgEFKA85c"
URL    = "https://api.india.delta.exchange"

# ══════════════════════════════════════════
# CONFIG
# ══════════════════════════════════════════
LEVERAGE           = 5
INR_RATE           = 85
MIN_BALANCE        = 10      # Real trade के लिए minimum $

# Risk Management
MAX_SL             = 3       # दिन में max SL hits
MAX_CONSECUTIVE_SL = 2       # लगातार max SL
DAILY_LOSS_LIMIT   = 200     # ₹ में daily max loss

# SL Config
ATR_SL_MULT        = 1.5
MIN_SL_PTS         = 150
MAX_SL_PTS         = 1000

# Dynamic TP Multipliers (ATR based)
TP1_MULT           = 1.5     # ATR × 1.5
TP2_MULT           = 3.0     # ATR × 3.0
TP3_MULT           = 5.0     # ATR × 5.0

# Trailing SL Multipliers
TRAIL_WEAK         = 2.0     # ADX < 25 (weak trend)
TRAIL_STRONG       = 3.0     # ADX > 25 (strong trend) — ज्यादा room

# ADX Thresholds
ADX_STRONG         = 25      # इससे ऊपर = strong trend
ADX_WEAK           = 20      # इससे नीचे = TP3 पर full exit

# Partial Exit Sizes (% of position)
EXIT_TP1           = 0.25    # 25% at TP1
EXIT_TP2           = 0.25    # 25% at TP2
EXIT_TP3           = 0.25    # 25% at TP3
EXIT_TRAIL         = 0.25    # 25% trail करता रहेगा

# ══════════════════════════════════════════
# STATE VARIABLES
# ══════════════════════════════════════════
sl_count       = 0
consecutive_sl = 0
daily_pnl_inr  = 0.0
today          = date.today()
last_signal    = "HOLD"
trade_log      = []


# ══════════════════════════════════════════
# LOGGING
# ══════════════════════════════════════════
def log_trade(trade_type, side, entry, exit_price, pts,
              tp1, tp2, tp3, trails, adx, mtf_confirm,
              balance_at_entry, max_pts_seen):
    record = {
        "time":         datetime.now().strftime("%Y-%m-%d %H:%M"),
        "type":         trade_type,
        "side":         side.upper(),
        "entry":        entry,
        "exit":         round(exit_price, 1),
        "pts":          round(pts, 1),
        "max_pts":      round(max_pts_seen, 1),
        "capture_pct":  round(pts / max_pts_seen * 100, 1)
                        if max_pts_seen > 0 else 0,
        "inr_approx":   round(abs(pts) * 0.001 * INR_RATE, 1),
        "tp1":          "✅" if tp1 else "❌",
        "tp2":          "✅" if tp2 else "❌",
        "tp3":          "✅" if tp3 else "❌",
        "trails":       trails,
        "adx":          round(adx, 1),
        "1h_confirm":   "✅" if mtf_confirm else "❌",
        "balance":      balance_at_entry,
    }
    trade_log.append(record)

    with open("trade_history.json", "a") as f:
        f.write(json.dumps(record) + "\n")

    print(f"\n📁 Saved → trade_history.json")
    print(f"📊 Captured: {record['capture_pct']}% of max move "
          f"({pts:.0f}/{max_pts_seen:.0f} pts)")


# ══════════════════════════════════════════
# API HELPERS
# ══════════════════════════════════════════
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
                print(f"💲 Price: {p:.0f}")
                return p
    except Exception as e:
        print(f"❌ Price Error: {e}")
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
                print(f"💼 Balance: ${bal:.2f} ({sym})")
                return bal
        if data:
            return float(data[0].get("available_balance", 0))
    except Exception as e:
        print(f"❌ Balance Error: {e}")
    return 0.0

def candles(resolution="15m", limit_hours=24):
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
        data = r.json()["result"]
        if data:
            print(f"📊 {resolution} | Candles: {len(data)} | "
                  f"Last: {float(data[-1]['close']):.0f}")
        return data
    except Exception as e:
        print(f"❌ Candles({resolution}) Error: {e}")
    return None


# ══════════════════════════════════════════
# INDICATORS
# ══════════════════════════════════════════
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
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    if len(trs) < n:
        return 200
    k = 2 / (n + 1)
    a = sum(trs[:n]) / n
    for t in trs[n:]:
        a = t * k + a * (1 - k)
    return round(a, 1)

def calc_adx(candle_data, n=14):
    """
    ADX — Trend Strength
    > 25 = Strong Trend (trail करो, ज्यादा points मिलेंगे)
    < 20 = Weak / Ranging (जल्दी exit करो)
    """
    if len(candle_data) < n * 2:
        return 20  # default — weak assume करो

    highs  = [float(c["high"])  for c in candle_data]
    lows   = [float(c["low"])   for c in candle_data]
    closes = [float(c["close"]) for c in candle_data]

    plus_dm, minus_dm, tr_list = [], [], []

    for i in range(1, len(highs)):
        h_diff = highs[i]  - highs[i-1]
        l_diff = lows[i-1] - lows[i]
        plus_dm.append( h_diff if h_diff > l_diff and h_diff > 0 else 0)
        minus_dm.append(l_diff if l_diff > h_diff and l_diff > 0 else 0)
        tr = max(highs[i] - lows[i],
                 abs(highs[i]  - closes[i-1]),
                 abs(lows[i]   - closes[i-1]))
        tr_list.append(tr)

    def smooth(data, n):
        s = sum(data[:n])
        result = [s]
        for x in data[n:]:
            s = s - s / n + x
            result.append(s)
        return result

    str_  = smooth(tr_list,   n)
    spdm  = smooth(plus_dm,   n)
    smdm  = smooth(minus_dm,  n)

    dx_list = []
    for i in range(len(str_)):
        if str_[i] == 0:
            continue
        pdi = 100 * spdm[i] / str_[i]
        mdi = 100 * smdm[i] / str_[i]
        if pdi + mdi == 0:
            continue
        dx_list.append(100 * abs(pdi - mdi) / (pdi + mdi))

    if not dx_list:
        return 20

    adx = sum(dx_list[-n:]) / min(n, len(dx_list))
    return round(adx, 1)

def volume_ok(candle_data, multiplier=1.2):
    vols = [float(c["volume"]) for c in candle_data]
    avg  = sum(vols[-20:]) / 20
    cur  = vols[-1]
    ok   = cur > avg * multiplier
    print(f"📊 Volume: {cur:.0f} | Avg: {avg:.0f} | OK: {ok}")
    return ok

def get_1h_direction(candle_1h):
    """
    1H timeframe direction check
    Returns: "UP", "DOWN", "NEUTRAL"
    """
    if not candle_1h or len(candle_1h) < 20:
        return "NEUTRAL"

    closes = [float(c["close"]) for c in candle_1h]
    rsi    = calc_rsi(closes)

    # 1H EMA 20
    ema = closes[0]
    k   = 2 / 21
    for c in closes[1:]:
        ema = c * k + ema * (1 - k)

    last_close = closes[-1]
    direction  = "NEUTRAL"

    if last_close > ema and rsi > 50:
        direction = "UP"
    elif last_close < ema and rsi < 50:
        direction = "DOWN"

    print(f"📈 1H | Close: {last_close:.0f} | "
          f"EMA20: {ema:.0f} | RSI: {rsi:.1f} | "
          f"Direction: {direction}")
    return direction

def find_signal(candle_15m, candle_1h):
    """
    Signal Engine:
    - RSI Divergence (primary)
    - Trend Follow (backup)
    - 1H MTF Confirm check
    Returns: (signal, mtf_confirmed)
    signal = "BUY" / "SELL" / "HOLD"
    mtf_confirmed = True/False
    """
    if len(candle_15m) < 20:
        print("⚠️ कम 15m candles!")
        return "HOLD", False

    closes = [float(c["close"]) for c in candle_15m]
    opens  = [float(c["open"])  for c in candle_15m]
    highs  = [float(c["high"])  for c in candle_15m]
    lows   = [float(c["low"])   for c in candle_15m]

    rsi_values = []
    for i in range(14, len(closes)):
        rsi_values.append(calc_rsi(closes[:i+1]))

    if len(rsi_values) < 10:
        return "HOLD", False

    current_rsi = rsi_values[-1]
    vol_good    = volume_ok(candle_15m)
    green       = closes[-1] > opens[-1]
    red         = closes[-1] < opens[-1]

    # 1H Direction
    dir_1h      = get_1h_direction(candle_1h)

    lookback     = 20
    recent_highs = highs[-lookback:]
    recent_lows  = lows[-lookback:]
    recent_rsi   = rsi_values[-lookback:]

    price_lows, rsi_lows = [], []
    for i in range(1, len(recent_lows)-1):
        if (recent_lows[i] < recent_lows[i-1]
                and recent_lows[i] < recent_lows[i+1]):
            price_lows.append((i, recent_lows[i]))
            if i < len(recent_rsi):
                rsi_lows.append((i, recent_rsi[i]))

    price_highs, rsi_highs = [], []
    for i in range(1, len(recent_highs)-1):
        if (recent_highs[i] > recent_highs[i-1]
                and recent_highs[i] > recent_highs[i+1]):
            price_highs.append((i, recent_highs[i]))
            if i < len(recent_rsi):
                rsi_highs.append((i, recent_rsi[i]))

    print(f"\n📊 15m RSI: {current_rsi:.1f} | "
          f"Lows: {len(price_lows)} | "
          f"Highs: {len(price_highs)} | "
          f"Vol: {vol_good} | G:{green} R:{red}")

    # ── BULLISH DIVERGENCE ──────────────────
    if len(price_lows) >= 2 and len(rsi_lows) >= 2:
        p_low1 = price_lows[-2][1]
        p_low2 = price_lows[-1][1]
        r_low1 = rsi_lows[-2][1]
        r_low2 = rsi_lows[-1][1]
        swing  = abs(p_low1 - p_low2)
        if (p_low2 < p_low1 and r_low2 > r_low1
                and current_rsi < 45
                and vol_good and green
                and swing >= 500):
            mtf = (dir_1h == "UP")
            print(f"🟢 BULLISH DIV! Swing:{swing:.0f} "
                  f"1H:{'✅' if mtf else '⚠️ Half Size'}")
            return "BUY", mtf

    # ── BEARISH DIVERGENCE ──────────────────
    if len(price_highs) >= 2 and len(rsi_highs) >= 2:
        p_hi1 = price_highs[-2][1]
        p_hi2 = price_highs[-1][1]
        r_hi1 = rsi_highs[-2][1]
        r_hi2 = rsi_highs[-1][1]
        swing  = abs(p_hi2 - p_hi1)
        if (p_hi2 > p_hi1 and r_hi2 < r_hi1
                and current_rsi > 55
                and vol_good and red
                and swing >= 500):
            mtf = (dir_1h == "DOWN")
            print(f"🔴 BEARISH DIV! Swing:{swing:.0f} "
                  f"1H:{'✅' if mtf else '⚠️ Half Size'}")
            return "SELL", mtf

    # ── TREND FOLLOW (Backup) ────────────────
    curr = closes[-1]
    prev = closes[-5] if len(closes) >= 5 else closes[0]
    move = (prev - curr) / prev * 100

    if move > 1.0 and current_rsi < 50 and red:
        mtf = (dir_1h == "DOWN")
        print(f"🔴 TREND SELL! Move:{move:.1f}% "
              f"1H:{'✅' if mtf else '⚠️'}")
        return "SELL", mtf

    if move < -1.0 and current_rsi > 50 and green:
        mtf = (dir_1h == "UP")
        print(f"🟢 TREND BUY! Move:{move:.1f}% "
              f"1H:{'✅' if mtf else '⚠️'}")
        return "BUY", mtf

    print(f"⏳ No Signal | RSI:{current_rsi:.1f} | Move:{move:.1f}%")
    return "HOLD", False


# ══════════════════════════════════════════
# REAL ORDER
# ══════════════════════════════════════════
def place_real_order(side, size=1):
    try:
        body = json.dumps({
            "product_id":    139,
            "size":          size,
            "side":          side,
            "order_type":    "market_order",
            "time_in_force": "gtc"
        })
        h = hdrs("POST", "/v2/orders", body)
        r = requests.post(URL + "/v2/orders",
                          headers=h, data=body, timeout=10)
        result = r.json()
        if result.get("success"):
            print(f"✅ REAL ORDER! Side:{side.upper()} "
                  f"Size:{size} ID:{result['result']['id']}")
            return True
        else:
            print(f"❌ Order Failed: {result}")
            return False
    except Exception as e:
        print(f"❌ Order Error: {e}")
        return False


# ══════════════════════════════════════════
# TRADE MONITOR — MAX POINTS CAPTURE ENGINE
# ══════════════════════════════════════════
def trade_monitor(side, entry, sl, candle_15m,
                  is_real, balance_at_entry, mtf_confirmed):
    global sl_count, consecutive_sl
    global daily_pnl_inr, last_signal

    trade_type  = "REAL" if is_real else "TRACKED"
    tag         = "💰 REAL" if is_real else "📊 TRACKED"

    # Dynamic TP — ATR based
    current_atr = calc_atr(candle_15m)
    tp1         = round(entry + current_atr * TP1_MULT, 1) \
                  if side == "buy" \
                  else round(entry - current_atr * TP1_MULT, 1)
    tp2         = round(entry + current_atr * TP2_MULT, 1) \
                  if side == "buy" \
                  else round(entry - current_atr * TP2_MULT, 1)
    tp3         = round(entry + current_atr * TP3_MULT, 1) \
                  if side == "buy" \
                  else round(entry - current_atr * TP3_MULT, 1)

    # ADX — Trend Strength
    adx         = calc_adx(candle_15m)
    strong_trend = adx >= ADX_STRONG
    trail_mult  = TRAIL_STRONG if strong_trend else TRAIL_WEAK
    trail_dist  = round(current_atr * trail_mult, 1)
    trail_dist  = max(trail_dist, MIN_SL_PTS)
    trail_dist  = min(trail_dist, MAX_SL_PTS)

    current_sl  = sl
    best_price  = entry
    trail_hits  = 0
    max_pts     = 0.0   # maximum unrealized profit देखा

    tp1_hit = tp2_hit = tp3_hit = False

    # Position tracking (partial exits के लिए)
    remaining_pct = 1.0   # 100% position अभी open है

    print(f"\n{'═'*50}")
    print(f"  {tag} TRADE — MAX CAPTURE MODE")
    print(f"{'═'*50}")
    print(f"  📌 Side:       {side.upper()}")
    print(f"  💲 Entry:      {entry:.0f}")
    print(f"  🛡️  SL:         {current_sl:.0f} "
          f"(-{abs(entry-current_sl):.0f} pts)")
    print(f"  📊 ATR:        {current_atr:.0f} pts")
    print(f"  📈 ADX:        {adx:.1f} "
          f"({'STRONG 💪' if strong_trend else 'WEAK 😐'})")
    print(f"  🕐 1H Confirm: {'✅ Full Size' if mtf_confirmed else '⚠️ Half Size'}")
    print(f"  ─────────────────────────────────────────")
    print(f"  🎯 TP1 (25%):  {tp1:.0f} "
          f"(+{abs(tp1-entry):.0f} pts | ATR×{TP1_MULT})")
    print(f"  🎯 TP2 (25%):  {tp2:.0f} "
          f"(+{abs(tp2-entry):.0f} pts | ATR×{TP2_MULT})")
    print(f"  🎯 TP3 (25%):  {tp3:.0f} "
          f"(+{abs(tp3-entry):.0f} pts | ATR×{TP3_MULT})")
    print(f"  ♾️  Trail(25%): ATR×{trail_mult} = {trail_dist:.0f} pts")
    print(f"{'═'*50}\n")

    for _ in range(5000):
        time.sleep(60)
        cp = price()
        if not cp:
            continue

        # Fresh ATR + ADX हर 15 min
        c_data = candles("15m", 12)
        if c_data:
            fresh_atr    = calc_atr(c_data)
            adx          = calc_adx(c_data)
            strong_trend = adx >= ADX_STRONG
            trail_mult   = TRAIL_STRONG if strong_trend else TRAIL_WEAK
            trail_dist   = round(fresh_atr * trail_mult, 1)
            trail_dist   = max(trail_dist, MIN_SL_PTS)
            trail_dist   = min(trail_dist, MAX_SL_PTS)

        # Max points track
        cur_pts = round(cp - entry, 1) if side == "buy" \
                  else round(entry - cp, 1)
        if cur_pts > max_pts:
            max_pts = cur_pts

        rr = round(cur_pts / abs(entry - current_sl), 2) \
             if abs(entry - current_sl) > 0 else 0

        print(f"{tag} | CP:{cp:.0f} | "
              f"P&L:{cur_pts:+.0f}pts | "
              f"Max:{max_pts:.0f} | "
              f"R:R 1:{rr:.1f} | "
              f"SL:{current_sl:.0f} | "
              f"ADX:{adx:.0f} | "
              f"Pos:{remaining_pct*100:.0f}% | "
              f"Daily:₹{daily_pnl_inr:+.0f}")

        # ════════════════════════════════════
        # BUY SIDE
        # ════════════════════════════════════
        if side == "buy":

            # TP1 — 25% Exit
            if not tp1_hit and cp >= tp1:
                tp1_hit       = True
                remaining_pct -= EXIT_TP1
                current_sl    = entry + 10   # Breakeven
                partial_pts   = round(tp1 - entry, 1)
                partial_inr   = round(partial_pts * 0.001
                                      * INR_RATE * EXIT_TP1, 1)
                daily_pnl_inr += partial_inr
                print(f"\n{'✅'*8}")
                print(f"TP1 HIT! 25% Exit")
                print(f"Exit Price:  {tp1:.0f}")
                print(f"Pts:         +{partial_pts:.0f}")
                print(f"INR (25%):   +₹{partial_inr:.0f}")
                print(f"SL → BE:     {entry+10:.0f}")
                print(f"Remaining:   {remaining_pct*100:.0f}%")
                print(f"{'✅'*8}\n")

            # TP2 — 25% Exit
            elif tp1_hit and not tp2_hit and cp >= tp2:
                tp2_hit       = True
                remaining_pct -= EXIT_TP2
                current_sl    = tp1             # TP1 lock
                partial_pts   = round(tp2 - entry, 1)
                partial_inr   = round(partial_pts * 0.001
                                      * INR_RATE * EXIT_TP2, 1)
                daily_pnl_inr += partial_inr
                print(f"\n{'🚀'*8}")
                print(f"TP2 HIT! 25% Exit")
                print(f"Exit Price:  {tp2:.0f}")
                print(f"Pts:         +{partial_pts:.0f}")
                print(f"INR (25%):   +₹{partial_inr:.0f}")
                print(f"SL → TP1:    {tp1:.0f}")
                print(f"Remaining:   {remaining_pct*100:.0f}%")
                                   
                  
            
