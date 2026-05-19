import requests,hmac,hashlib,time,json
from datetime import date

KEY="9ihv6wjSmxx5wbpG5BwjeV5aY8at9r"
SECRET="qWGvfU1SWHDrOoEKMI1JWdBbWsg6CMx3iYBvu1icXwutzuUaN1tq64VVHKS9"
URL="https://cdn-ind.testnet.deltaex.org"
MAX_SL=3
sl_count=0
today=date.today()

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
        start=end-(60*60*60)
        r=requests.get(URL+"/v2/history/candles",
        params={"symbol":"BTCUSD","resolution":"1h","start":start,"end":end},timeout=10)
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

def signal(candle_data):
    closes=[float(c["close"]) for c in candle_data]
    opens=[float(c["open"]) for c in candle_data]

    e50=ema(closes,50)
    r=rsi(closes)
    p=closes[-1]
    o=opens[-1]

    green_candle=p>o
    red_candle=p<o

    print(f"EMA50:{e50:.1f} RSI:{r:.1f} Green:{green_candle}")

    if p>e50 and r>50 and green_candle:
        return "BUY"
    elif p<e50 and r<50 and red_candle:
        return "SELL"
    return "HOLD"

def get_pid():
    r=requests.get(URL+"/v2/products",timeout=10)
    for x in r.json().get("result",[]):
        if x.get("symbol")=="BTCUSD":
            return x.get("id")
    return None

def order(side):
    global sl_count
    try:
        pid=get_pid()
        if not pid:
            print("Product नहीं मिला")
            return
        p=price()

        b=json.dumps({"product_id":pid,"size":1,"side":side,"order_type":"market_order"})
        h=hdrs("POST","/v2/orders",b)
        res=requests.post(URL+"/v2/orders",headers=h,data=b,timeout=10)
        d=res.json()
        print("ORDER:",side.upper(),"Entry:",p)
        print("Success:",d.get("success"))

        if d.get("success"):
            time.sleep(2)
            close_side="sell" if side=="buy" else "buy"

            sl=round(p-50,1) if side=="buy" else round(p+50,1)
            sl_b=json.dumps({"product_id":pid,"size":1,"side":close_side,"order_type":"limit_order","limit_price":str(sl),"stop_price":str(sl),"stop_order_type":"stop_loss_order"})
            sl_h=hdrs("POST","/v2/orders",sl_b)
            sl_r=requests.post(URL+"/v2/orders",headers=sl_h,data=sl_b,timeout=10)
            print("SL:",sl,"Result:",sl_r.json().get("success"))

            tp=round(p+500,1) if side=="buy" else round(p-500,1)
            tp_b=json.dumps({"product_id":pid,"size":1,"side":close_side,"order_type":"limit_order","limit_price":str(tp)})
            tp_h=hdrs("POST","/v2/orders",tp_b)
            tp_r=requests.post(URL+"/v2/orders",headers=tp_h,data=tp_b,timeout=10)
            print("TP:",tp,"Result:",tp_r.json().get("success"))

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
            print("नया दिन!")
        if sl_count>=MAX_SL:
            print("3 SL! आज बंद!")
            time.sleep(3600)
            continue
        p=price()
        c=candles()
        if p and c:
            s=signal(c)
            print("Price:",p,"Signal:",s,"SL:",sl_count)
            if s!=last and s!="HOLD":
                order(s.lower())
                last=s
        else:
            print("Data नहीं मिला")
        time.sleep(900)

run()
