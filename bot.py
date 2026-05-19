import requests,hmac,hashlib,time,json
from datetime import date,datetime

KEY="9ihv6wjSmxx5wbpG5BwjeV5aY8at9r"
SECRET="qWGvfU1SWHDrOoEKMI1JWdBbWsg6CMx3iYBvu1icXwutzuUaN1tq64VVHKS9"
URL="https://cdn-ind.testnet.deltaex.org"
MAX_SL=3
sl_count=0
today=date.today()
CAPITAL=5000
LEVERAGE=5
PER_TRADE=0.20

# News times (IST) - इन times पर trade नहीं
NEWS_HOURS=[20,21,22]  # 8-10 PM IST = US market news

def hdrs(m,p,b=""):
    t=str(int(time.time()))
    s=hmac.new(SECRET.encode(),(m+t+p+b).encode(),hashlib.sha256).hexdigest()
    return {"api-key":KEY,"timestamp":t,"signature":s,"Content-Type":"application/json"}

def price():
    try:
        r=requests.get(URL+"/v2/tickers",timeout=10)
        for x in r.json()["result"]:
            if x["symbol"]=="BTCUSD":
                return float(x["close"])
    except:
        return None

def candles(resolution="1h",hours=60):
    try:
        end=int(time.time())
        start=end-(hours*3600)
        r=requests.get(URL+"/v2/history/candles",
        params={"symbol":"BTCUSD","resolution":resolution,"start":start,"end":end},timeout=10)
        return r.json()["result"]
    except:
        return None

def ema(closes,n):
    k=2/(n+1)
    e=closes[0]
    for p in closes[1:]:
        e=p*k+e*(1-k)
    return e

def rsi(closes,n=14):
    gains,losses=[],[]
    for i in range(1,len(closes)):
        d=closes[i]-closes[i-1]
        gains.append(max(d,0))
        losses.append(max(-d,0))
    ag=sum(gains[-n:])/n
    al=sum(losses[-n:])/n
    if al==0:
        return 100
    return 100-(100/(1+ag/al))

def volume_ok(candle_data):
    # Last candle volume > average volume
    vols=[float(c.get("volume",0)) for c in candle_data]
    avg_vol=sum(vols[:-1])/len(vols[:-1])
    last_vol=vols[-1]
    ok=last_vol>avg_vol
    print(f"Volume:{last_vol:.0f} Avg:{avg_vol:.0f} OK:{ok}")
    return ok

def news_time():
    hour=datetime.now().hour
    if hour in NEWS_HOURS:
        print(f"⚠️ News time! {hour}:00 - Skip")
        return True
    return False

def signal_1h(candle_data):
    closes=[float(c["close"]) for c in candle_data]
    opens=[float(c["open"]) for c in candle_data]
    e50=ema(closes,50)
    r=rsi(closes)
    p=closes[-1]
    o=opens[-1]
    green=p>o
    red=p<o
    print(f"1H → EMA50:{e50:.0f} RSI:{r:.1f} Green:{green}")
    if p>e50 and r>50 and green:
        return "BUY"
    elif p<e50 and r<50 and red:
        return "SELL"
    return "HOLD"

def signal_4h(candle_data):
    closes=[float(c["close"]) for c in candle_data]
    opens=[float(c["open"]) for c in candle_data]
    e50=ema(closes,50)
    r=rsi(closes)
    p=closes[-1]
    o=opens[-1]
    green=p>o
    red=p<o
    print(f"4H → EMA50:{e50:.0f} RSI:{r:.1f} Green:{green}")
    if p>e50 and r>50 and green:
        return "BUY"
    elif p<e50 and r<50 and red:
        return "SELL"
    return "HOLD"

def get_pid():
    r=requests.get(URL+"/v2/products",timeout=10)
    for x in r.json().get("result",[]):
        if x.get("symbol")=="BTCUSD":
            return x.get("id")
    return None

def calc_size(p):
    margin=CAPITAL*PER_TRADE
    size=round((margin*LEVERAGE)/p,4)
    return max(size,0.001)

def order(side):
    global sl_count
    try:
        pid=get_pid()
        if not pid:
            return
        p=price()
        size=calc_size(p)

        b=json.dumps({"product_id":pid,"size":size,"side":side,"order_type":"market_order"})
        h=hdrs("POST","/v2/orders",b)
        res=requests.post(URL+"/v2/orders",headers=h,data=b,timeout=10)
        d=res.json()
        print(f"ORDER:{side.upper()} Entry:{p} Size:{size}")
        print("Success:",d.get("success"))

        if d.get("success"):
            time.sleep(2)
            close_side="sell" if side=="buy" else "buy"

            # SL
            sl=round(p-50,1) if side=="buy" else round(p+50,1)
            sl_b=json.dumps({"product_id":pid,"size":size,"side":close_side,"order_type":"limit_order","limit_price":str(sl),"stop_price":str(sl),"stop_order_type":"stop_loss_order"})
            sl_h=hdrs("POST","/v2/orders",sl_b)
            sl_r=requests.post(URL+"/v2/orders",headers=sl_h,data=sl_b,timeout=10)
            print("SL:",sl,"Result:",sl_r.json().get("success"))

            # TP
            tp=round(p+500,1) if side=="buy" else round(p-500,1)
            tp_b=json.dumps({"product_id":pid,"size":size,"side":close_side,"order_type":"limit_order","limit_price":str(tp)})
            tp_h=hdrs("POST","/v2/orders",tp_b)
            tp_r=requests.post(URL+"/v2/orders",headers=tp_h,data=tp_b,timeout=10)
            print("TP:",tp,"Result:",tp_r.json().get("success"))

            # Trailing SL - 15 min check
            print("Trailing SL monitoring शुरू...")
            entry=p
            best=p
            for _ in range(20):
                time.sleep(900)
                cp=price()
                if not cp:
                    continue
                if side=="buy":
                    if cp>best:
                        best=cp
                        new_sl=round(best-50,1)
                        print(f"Trailing SL update: {new_sl}")
                    if cp<=round(best-50,1):
                        print("Trailing SL hit!")
                        break
                else:
                    if cp<best:
                        best=cp
                        new_sl=round(best+50,1)
                        print(f"Trailing SL update: {new_sl}")
                    if cp>=round(best+50,1):
                        print("Trailing SL hit!")
                        break

        else:
            print("Error:",d.get("error"))

    except Exception as e:
        print("Error:",e)

def run():
    global sl_count,today
    last="HOLD"
    while True:
        if date.today()!=today:
            today=date.today()
            sl_count=0
            print("🌅 नया दिन!")

        if sl_count>=MAX_SL:
            print("🚫 3 SL! आज बंद!")
            time.sleep(3600)
            continue

        # News time check
        if news_time():
            time.sleep(1800)
            continue

        p=price()
        c1h=candles("1h",60)
        c4h=candles("4h",240)

        if p and c1h and c4h:
            s1h=signal_1h(c1h)
            s4h=signal_4h(c4h)
            vol=volume_ok(c1h)

            print(f"Price:{p} 1H:{s1h} 4H:{s4h} Vol:{vol}")

            # 1H + 4H दोनों same + Volume OK
            if s1h==s4h and s1h!="HOLD" and vol:
                print(f"✅ Confirmed Signal: {s1h}")
                if s1h!=last:
                    order(s1h.lower())
                    last=s1h
            else:
                print("⏳ Signal confirm नहीं हुआ")
        else:
            print("Data नहीं मिला")

        time.sleep(900)

run()
