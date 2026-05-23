import requests,hmac,hashlib,time,json
from datetime import date

KEY="9ihv6wjSmxx5wbpG5BwjeV5aY8at9r"
SECRET="qWGvfU1SWHDrOoEKMI1JWdBbWsg6CMx3iYBvu1icXwutzuUaN1tq64VVHKS9"
URL="https://cdn-ind.testnet.deltaex.org"
MAX_SL=3
sl_count=0
today=date.today()
SIZE=1
SL_PTS=100
TRAIL_STEP=500

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

def candles():
    try:
        end=int(time.time())
        start=end-(20*3600)
        r=requests.get(URL+"/v2/history/candles",
        params={"symbol":"BTCUSD","resolution":"15m","start":start,"end":end},timeout=10)
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
    vols=[float(c.get("volume",0)) for c in candle_data]
    avg_vol=sum(vols[:-1])/len(vols[:-1])
    last_vol=vols[-1]
    ok=last_vol>(avg_vol*0.5)
    print(f"Volume:{last_vol:.0f} Avg:{avg_vol:.0f} OK:{ok}")
    return ok

def signal(candle_data):
    closes=[float(c["close"]) for c in candle_data]
    opens=[float(c["open"]) for c in candle_data]
    e9=ema(closes,9)
    e21=ema(closes,21)
    r=rsi(closes)
    p=closes[-1]
    o=opens[-1]
    green=p>o
    red=p<o
    print(f"EMA9:{e9:.0f} EMA21:{e21:.0f} RSI:{r:.1f} Green:{green}")
    if e9>e21 and r>=45 and r<=65 and green:
        return "BUY"
    elif e9<e21 and r>=35 and r<=55 and red:
        return "SELL"
    return "HOLD"

def get_pid():
    r=requests.get(URL+"/v2/products",timeout=10)
    for x in r.json().get("result",[]):
        if x.get("symbol")=="BTCUSD":
            return x.get("id")
    return None

def cancel_all_orders(pid):
    try:
        b=json.dumps({"product_id":pid,"cancel_limit_orders":True,"cancel_stop_orders":True})
        h=hdrs("DELETE","/v2/orders",b)
        r=requests.delete(URL+"/v2/orders",headers=h,data=b,timeout=10)
        print("Orders cancelled:",r.json().get("success"))
    except Exception as e:
        print("Cancel error:",e)

def place_order(pid,side,order_type,price_val=None,stop_price=None,stop_type=None):
    body={"product_id":pid,"size":SIZE,"side":side,"order_type":order_type}
    if price_val:
        body["limit_price"]=str(round(price_val,1))
    if stop_price:
        body["stop_price"]=str(round(stop_price,1))
    if stop_type:
        body["stop_order_type"]=stop_type
    b=json.dumps(body)
    h=hdrs("POST","/v2/orders",b)
    r=requests.post(URL+"/v2/orders",headers=h,data=b,timeout=10)
    return r.json()

def order(side):
    global sl_count
    try:
        pid=get_pid()
        if not pid:
            print("Product नहीं मिला")
            return
        entry=price()
        close_side="sell" if side=="buy" else "buy"

        # Main Entry
        res=place_order(pid,side,"market_order")
        print(f"ORDER:{side.upper()} Entry:{entry} Size:{SIZE}")
        print("Success:",res.get("success"))

        if not res.get("success"):
            print("Error:",res.get("error"))
            return

        time.sleep(2)

        # Initial SL
        sl=round(entry-SL_PTS,1) if side=="buy" else round(entry+SL_PTS,1)
        sl_res=place_order(pid,close_side,"limit_order",sl,sl,"stop_loss_order")
        print(f"SL:{sl} OK:{sl_res.get('success')}")

        # Trailing Monitor
        print("🔄 Trailing monitor शुरू...")
        current_sl=sl
        next_trail=entry+TRAIL_STEP if side=="buy" else entry-TRAIL_STEP
        trail_count=0
        breakeven=False

        for _ in range(500):
            time.sleep(300)
            cp=price()
            if not cp:
                continue

            if side=="buy":
                # Trail level hit हुआ
                if cp>=next_trail:
                    trail_count+=1
                    if not breakeven:
                        # पहला trail = Breakeven
                        current_sl=entry
                        breakeven=True
                        print(f"✅ +{TRAIL_STEP} pts! Breakeven SL:{current_sl}")
                    else:
                        # अगला trail = SL ऊपर
                        current_sl=next_trail-SL_PTS
                        print(f"🚀 +{TRAIL_STEP*trail_count} pts! SL:{current_sl}")
                    next_trail=round(next_trail+TRAIL_STEP,1)
                    print(f"Next Trail Target: {next_trail}")

                # SL Hit
                if cp<=current_sl:
                    if breakeven:
                        profit=round(cp-entry,1)
                        print(f"🎯 Exit! Profit:+{profit} pts 🔥")
                    else:
                        print(f"🛑 SL Hit! -{SL_PTS} pts")
                        sl_count+=1
                    cancel_all_orders(pid)
                    break

            else:
                # Trail level hit हुआ
                if cp<=next_trail:
                    trail_count+=1
                    if not breakeven:
                        current_sl=entry
                        breakeven=True
                        print(f"✅ +{TRAIL_STEP} pts! Breakeven SL:{current_sl}")
                    else:
                        current_sl=next_trail+SL_PTS
                        print(f"🚀 +{TRAIL_STEP*trail_count} pts! SL:{current_sl}")
                    next_trail=round(next_trail-TRAIL_STEP,1)
                    print(f"Next Trail Target: {next_trail}")

                # SL Hit
                if cp>=current_sl:
                    if breakeven:
                        profit=round(entry-cp,1)
                        print(f"🎯 Exit! Profit:+{profit} pts 🔥")
                    else:
                        print(f"🛑 SL Hit! -{SL_PTS} pts")
                        sl_count+=1
                    cancel_all_orders(pid)
                    break

        print(f"✅ Trade Done! SL:{sl_count}/{MAX_SL}")

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

        p=price()
        c=candles()

        if p and c:
            s=signal(c)
            vol=volume_ok(c)
            print(f"Price:{p} Signal:{s} Vol:{vol} SL:{sl_count}/{MAX_SL}")

            if s!="HOLD" and vol and s!=last:
                print(f"✅ Confirmed: {s}")
                order(s.lower())
                last=s
            else:
                print("⏳ Wait...")
        else:
            print("Data नहीं मिला")

        time.sleep(900)

run()
