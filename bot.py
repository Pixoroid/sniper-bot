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
        r=requests.get(URL+"/v2/history/candles",params={"symbol":"BTCUSD","resolution":"1h","start":start,"end":end},timeout=10)
        return [float(c["close"]) for c in r.json()["result"]]
    except:
        return None

def ema(prices,n):
    k=2/(n+1)
    e=prices[0]
    for p in prices[1:]:
        e=p*k+e*(1-k)
    return e

def signal(c):
    e50=ema(c,50)
    p=c[-1]
    if p>e50:
        return "BUY"
    elif p<e50:
        return "SELL"
    return "HOLD"

def order(side):
    try:
        r=requests.get(URL+"/v2/products",timeout=10)
        pid=None
        for x in r.json().get("result",[]):
            if x.get("symbol")=="BTCUSD":
                pid=x.get("id")
                break
        if not pid:
            print("Product नहीं मिला")
            return
        b=json.dumps({"product_id":pid,"size":1,"side":side,"order_type":"market_order"})
        h=hdrs("POST","/v2/orders",b)
        res=requests.post(URL+"/v2/orders",headers=h,data=b,timeout=10)
        d=res.json()
        print("ORDER:",side.upper(),"Success:",d.get("success"))
        if not d.get("success"):
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
