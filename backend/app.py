from fastapi import FastAPI,requests,Form, HTTPException
from fastapi.responses import HTMLResponse
from pymongo import MongoClient
from  pydantic import BaseModel
from dotenv import load_dotenv
import os
import html
from bson.objectid import ObjectId
from razorpay import Client
import razorpay
from datetime import datetime
from html import escape
from pathlib import Path
import hashlib
import hmac






load_dotenv()

class Amount(BaseModel):
    amount: int 
    user_id:str



TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Receipt</title>
<style>
  :root{
    --page:#e6eee1;
    --band:#d7e4d1;
    --ink:#16241c;
    --ink-soft:#5d7161;
    --rule:#a7bda2;
    --bind:#8a2033;
    --bind-dark:#6a1826;
    --surround:#151d16;
    --pad:30px;
  }
 
  *{box-sizing:border-box}
 
  body{
    margin:0;
    min-height:100vh;
    padding:48px 18px;
    display:flex;
    align-items:center;
    justify-content:center;
    background:var(--surround);
    color:var(--ink);
    font-family:"Archivo","Helvetica Neue",Arial,sans-serif;
    font-size:16px;
    -webkit-font-smoothing:antialiased;
  }
 
  .ledger{
    width:min(440px,100%);
    display:grid;
    grid-template-columns:16px minmax(0,1fr);
    background:var(--page);
    box-shadow:0 20px 44px rgba(0,0,0,.5);
  }
 
  .ledger__bind{
    background:linear-gradient(90deg,var(--bind-dark),var(--bind) 60%,var(--bind-dark));
    position:relative;
  }
  .ledger__bind::before{
    content:"";
    position:absolute;
    left:50%; top:26px; bottom:26px;
    width:2px;
    transform:translateX(-50%);
    background:repeating-linear-gradient(180deg,rgba(255,255,255,.55) 0 7px,transparent 7px 17px);
    opacity:.4;
  }
 
  .ledger__body{padding:var(--pad)}
 
  .head{
    display:flex;
    align-items:center;
    justify-content:space-between;
    gap:14px;
    margin-bottom:24px;
  }
  .head h1{
    margin:0;
    font-size:30px;
    font-weight:800;
    font-stretch:118%;
    letter-spacing:-.02em;
    line-height:1.02;
  }
  .head p{margin:7px 0 0;color:var(--ink-soft);font-size:14px}
 
  .stamp{
    flex:0 0 auto;
    display:flex;
    flex-direction:column;
    align-items:center;
    gap:3px;
    padding:8px 13px 7px;
    border:2px solid var(--bind);
    color:var(--bind);
    transform:rotate(-7deg);
    opacity:.92;
  }
  .stamp__word{
    font-size:19px;
    font-weight:800;
    font-stretch:118%;
    letter-spacing:.13em;
    line-height:1;
    text-indent:.13em;
  }
  .stamp__date{
    font-size:11px;
    letter-spacing:.08em;
    font-variant-numeric:tabular-nums;
  }
 
  .items{
    list-style:none;
    margin:0 calc(var(--pad) * -1);
    padding:0;
    border-top:1px solid var(--rule);
    border-bottom:1px solid var(--rule);
  }
  .item{
    display:flex;
    align-items:baseline;
    justify-content:space-between;
    gap:18px;
    padding:13px var(--pad);
    line-height:1.35;
  }
  .item:nth-child(even){background:var(--band)}
  .item__name{min-width:0;overflow-wrap:anywhere}
  .item__qty{
    color:var(--ink-soft);
    font-variant-numeric:tabular-nums;
    white-space:nowrap;
    font-size:15px;
  }
  .item__qty--id{
    white-space:normal;
    text-align:right;
    overflow-wrap:anywhere;
    letter-spacing:.01em;
  }
 
  .total{
    display:flex;
    align-items:flex-end;
    justify-content:space-between;
    gap:20px;
    margin-top:26px;
    padding-bottom:8px;
    border-bottom:4px double var(--ink);
  }
  .total__label{color:var(--ink-soft);font-size:15px;padding-bottom:11px}
  .total__value{
    display:flex;
    align-items:baseline;
    gap:.08em;
    font-size:clamp(46px,14vw,62px);
    font-weight:800;
    font-stretch:125%;
    letter-spacing:-.035em;
    line-height:.82;
    font-variant-numeric:tabular-nums;
  }
  .total__rupee{
    font-size:.42em;
    font-weight:600;
    font-stretch:100%;
    letter-spacing:0;
    color:var(--ink-soft);
  }
 
  .note{
    margin:22px 0 0;
    text-align:center;
    font-size:13px;
    line-height:1.5;
    color:var(--ink-soft);
  }
 
  @media (max-width:420px){
    :root{--pad:22px}
    body{padding:24px 12px}
    .head h1{font-size:24px}
    .stamp__word{font-size:17px}
  }
  @media (prefers-reduced-motion:reduce){
    *{transition:none !important}
  }
  @media print{
    body{background:#fff;padding:0;min-height:0;display:block}
    .ledger{width:100%;box-shadow:none}
  }
</style>
</head>
<body>
  <main class="ledger">
    <div class="ledger__bind" aria-hidden="true"></div>
    <div class="ledger__body">
 
      <header class="head">
        <div>
          <h1>Payment received</h1>
          <p>{{date}}</p>
        </div>
        <div class="stamp" role="img" aria-label="Paid {{stamp_date}}">
          <span class="stamp__word" aria-hidden="true">PAID</span>
          <span class="stamp__date" aria-hidden="true">{{stamp_date}}</span>
        </div>
      </header>
 
      <ul class="items">
        <li class="item">
          <span class="item__name">Payment ID</span>
          <span class="item__qty item__qty--id">{{payment_id}}</span>
        </li>
        <li class="item">
          <span class="item__name">Order ID</span>
          <span class="item__qty item__qty--id">{{order_id}}</span>
        </li>
        <li class="item">
          <span class="item__name">Ordered</span>
          <span class="item__qty">{{item_count}}</span>
        </li>
      </ul>
 
      <div class="total">
        <span class="total__label">Amount paid</span>
        <span class="total__value"><span class="total__rupee">&#8377;</span>{{amount}}</span>
      </div>
 
      <p class="note">Quote the payment ID if you need to ask us about this order.</p>
 
    </div>
  </main>
</body>
</html>
"""
 



razorpay_api=os.getenv("RAZORPAY_API")
razorpay_secret=os.getenv("RAZORPAY_SECRET")
razorpay_client=Client(auth=(razorpay_api,razorpay_secret))


mongo_uri=os.getenv("MONGO_CONNECTION_URL")
client=MongoClient(mongo_uri)
database=client['database']

cart_connection=database['carts']
user_connection=database['users']
payment_connection=database['payments']
order_connection=database['orders']



def inr(n):
    n = int(round(float(n)))
    s = str(abs(n))
    if len(s) > 3:
        last3, rest = s[-3:], s[:-3]
        parts = []
        while len(rest) > 2:
            parts.insert(0, rest[-2:])
            rest = rest[:-2]
        if rest:
            parts.insert(0, rest)
        s = ",".join(parts + [last3])
    return ("-" if n < 0 else "") + s




def render(**values) -> str:
    html = TEMPLATE
    for key, value in values.items():
        html = html.replace("{{" + key + "}}", escape(str(value)))
    return html





app=FastAPI()

@app.get("/cart/{user_id}")
def return_cart(user_id):
    res=cart_connection.find_one({'user_id':user_id})
    user=user_connection.find_one({'_id':ObjectId(user_id)})
    if res is None:
        return HTMLResponse("""
            <!DOCTYPE html>
            <html>
            <head>
            <title>CART</title>
            </head>
            <body>
            No cart found please check the URL
            </body>
            </html>
        """)


    start_doc = """<!DOCTYPE html>
    <html lang="en">
    <head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Cart</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Archivo:wdth,wght@62..125,400..800&display=swap" rel="stylesheet">
    <style>
      :root{
        --page:#e6eee1;
        --band:#d7e4d1;
        --ink:#16241c;
        --ink-soft:#5d7161;
        --rule:#a7bda2;
        --bind:#8a2033;
        --bind-dark:#6a1826;
        --surround:#151d16;
        --pad:30px;
      }
    
      *{box-sizing:border-box}
    
      body{
        margin:0;
        min-height:100vh;
        padding:48px 18px;
        display:flex;
        align-items:center;
        justify-content:center;
        background:var(--surround);
        color:var(--ink);
        font-family:"Archivo","Helvetica Neue",Arial,sans-serif;
        font-size:16px;
        -webkit-font-smoothing:antialiased;
      }
    
      .ledger{
        width:min(440px,100%);
        display:grid;
        grid-template-columns:16px minmax(0,1fr);
        background:var(--page);
        box-shadow:0 20px 44px rgba(0,0,0,.5);
      }
    
      .ledger__bind{
        background:linear-gradient(90deg,var(--bind-dark),var(--bind) 60%,var(--bind-dark));
        position:relative;
      }
      .ledger__bind::before{
        content:"";
        position:absolute;
        left:50%; top:26px; bottom:26px;
        width:2px;
        transform:translateX(-50%);
        background:repeating-linear-gradient(180deg,rgba(255,255,255,.55) 0 7px,transparent 7px 17px);
        opacity:.4;
      }
    
      .ledger__body{padding:var(--pad)}
    
      .head{
        display:flex;
        align-items:baseline;
        justify-content:space-between;
        gap:16px;
        margin-bottom:24px;
      }
      .head h1{
        margin:0;
        font-size:30px;
        font-weight:800;
        font-stretch:118%;
        letter-spacing:-.02em;
        line-height:1;
      }
      .head p{margin:0;color:var(--ink-soft);font-size:14px}
    
      .items{
        list-style:none;
        margin:0 calc(var(--pad) * -1);
        padding:0;
        border-top:1px solid var(--rule);
        border-bottom:1px solid var(--rule);
      }
      .item{
        display:flex;
        align-items:baseline;
        justify-content:space-between;
        gap:18px;
        padding:13px var(--pad);
        line-height:1.35;
      }
      .item:nth-child(even){background:var(--band)}
      .item__name{min-width:0;overflow-wrap:anywhere}
      .item__qty{
        color:var(--ink-soft);
        font-variant-numeric:tabular-nums;
        white-space:nowrap;
        font-size:15px;
      }
    
      .empty{
        margin:0 calc(var(--pad) * -1);
        padding:34px var(--pad);
        border-top:1px solid var(--rule);
        border-bottom:1px solid var(--rule);
        color:var(--ink-soft);
      }
    
      .total{
        display:flex;
        align-items:flex-end;
        justify-content:space-between;
        gap:20px;
        margin-top:26px;
        padding-bottom:8px;
        border-bottom:4px double var(--ink);
      }
      .total__label{color:var(--ink-soft);font-size:15px;padding-bottom:11px}
      .total__value{
        display:flex;
        align-items:baseline;
        gap:.08em;
        font-size:clamp(46px,14vw,62px);
        font-weight:800;
        font-stretch:125%;
        letter-spacing:-.035em;
        line-height:.82;
        font-variant-numeric:tabular-nums;
      }
      .total__rupee{
        font-size:.42em;
        font-weight:600;
        font-stretch:100%;
        letter-spacing:0;
        color:var(--ink-soft);
      }
    
      .pay{
        width:100%;
        margin-top:26px;
        padding:17px 20px;
        border:0;
        background:var(--bind);
        color:#fdf3f0;
        font-family:inherit;
        font-size:16px;
        font-weight:700;
        font-stretch:110%;
        cursor:pointer;
        box-shadow:inset 0 -3px 0 rgba(0,0,0,.3);
        transition:background-color .15s ease;
      }
      .pay:hover{background:#9b2739}
      .pay:active{transform:translateY(2px);box-shadow:inset 0 -1px 0 rgba(0,0,0,.3)}
      .pay:focus-visible{outline:3px solid var(--ink);outline-offset:3px}
      .pay[disabled]{background:#8d8f89;cursor:progress;box-shadow:none}
    
      .note{
        margin:12px 0 0;
        text-align:center;
        font-size:13px;
        color:var(--ink-soft);
      }
      .notice{
        margin:14px 0 0;
        padding:11px 13px;
        background:#f6e2e2;
        border-left:4px solid var(--bind);
        font-size:14px;
        line-height:1.4;
      }
      .notice[hidden]{display:none}
    
      @media (max-width:420px){
        :root{--pad:22px}
        body{padding:24px 12px}
        .head h1{font-size:26px}
      }
      @media (prefers-reduced-motion:reduce){
        *{transition:none !important}
        .pay:active{transform:none}
      }
    </style>
    </head>
    <body>
    """
    
    
    products = res['Products']
    count = sum(int(d['Quantity']) for d in products.values())
    
    mid_doc = """
    <div class="ledger">
      <div class="ledger__bind" aria-hidden="true"></div>
      <div class="ledger__body">
    
        <header class="head">
          <h1>Cart</h1>
          <p>{count} item{plural}</p>
        </header>
    """.format(count=count, plural="" if count == 1 else "s")
    
    if products:
        mid_doc += '<ul class="items">'
        for item, details in products.items():
            mid_doc += (
                '<li class="item">'
                '<span class="item__name">{name}</span>'
                '<span class="item__qty">&times;{qty}</span>'
                '</li>'
            ).format(
                name=html.escape(str(item)),
                qty=html.escape(str(details['Quantity'])),
            )
        mid_doc += '</ul>'
    else:
        mid_doc += '<p class="empty">Nothing here yet. Add something to get started.</p>'
    
    mid_doc += """
        <div class="total">
          <span class="total__label">Total</span>
          <span class="total__value"><span class="total__rupee">&#8377;</span><span id="amount">{amount}</span></span>
        </div>
    """.format(amount=inr(res['Amount']))
    
    
    amount_paise = int(round(float(res['Amount']) * 100))
    amount_text = inr(res['Amount'])
    email = html.escape(str(user['email']))
    
    end_doc = f"""
        <button class="pay" type="button" id="pay" onclick="payNow()">Pay &#8377;{amount_text}</button>
        <p class="note">Razorpay handles the payment.</p>
        <p class="notice" id="notice" hidden></p>
    
      </div>
    </div>
    
    <script src="https://checkout.razorpay.com/v1/checkout.js"></script>
    <script>
        const payBtn = document.getElementById('pay');
        const notice = document.getElementById('notice');
    
        function showNotice(text) {{
            notice.textContent = text;
            notice.hidden = false;
        }}
    
        async function payNow() {{
            user_id=(document.URL).split("/").at(-1)
            console.log(user_id)
            notice.hidden = true;
            payBtn.disabled = true;
            payBtn.textContent = 'Opening Razorpay\u2026';
    
            try {{
                
                const response = await fetch('/create-order', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ amount: {amount_paise} , user_id:user_id}})
                }});
    
                if (!response.ok) throw new Error('order failed');
                const order = await response.json();
    
                const rzp = new Razorpay({{
                    key: '{razorpay_api}',
                    amount: order.amount,
                    currency: 'INR',
                    name: 'Testing',
                    description: 'Order payment',
                    order_id: order.id,
                    callback_url: 'http://127.0.0.1:8000/handle-payment',
                    prefill: {{
                        email: '{email}'
                    }},
                    theme: {{ color: '#8a2033' }},
                    modal: {{
                        ondismiss: function () {{ resetButton(); }}
                    }}
                }});
    
                rzp.on('payment.failed', function () {{
                    resetButton();
                    showNotice("That payment didn't go through. Nothing was charged  try again.");
                }});
    
               rzp.open();
                
            }} catch (err) {{
                resetButton();
                showNotice("Couldn't reach the payment server. Check your connection and try again.");
            }}
        }}
    
        function resetButton() {{
            payBtn.disabled = false;
            payBtn.textContent = 'Pay \u20b9{amount_text}';
        }}
    </script>
    
    </body>
    </html>
    """

    return HTMLResponse(start_doc+mid_doc+end_doc)


@app.post("/create-order")
def create_order(Amt:Amount):
    amt=Amt.amount
    currency='INR'
    order_info=razorpay_client.order.create(data={
        "amount":amt,
        "currency":currency
    })
    order_info['user_id']=Amt.user_id
    res=order_connection.insert_one(order_info)
    order_info.pop("_id")
    return order_info



@app.post("/handle-payment")
async def payment_success(
    razorpay_payment_id: str = Form(...),
    razorpay_order_id: str = Form(...),
    razorpay_signature: str = Form(...)
):
    
 
    order_info = order_connection.find_one({"id": str(razorpay_order_id)})
    if not order_info:
        raise HTTPException(status_code=404, detail="Order not found")

    try:
        razorpay_client.utility.verify_payment_signature({
            'razorpay_payment_id':razorpay_payment_id,
            'razorpay_order_id':razorpay_order_id,
            'razorpay_signature':razorpay_signature
        })
    except Exception as e:
        return {"error":e}
 
    order_info["payment_id"] = razorpay_payment_id
    order_info["paid_at"] = datetime.utcnow()
 
    payment_connection.insert_one(order_info)
    order_connection.delete_one({"_id": order_info["_id"]})
    cart_connection.delete_one({"user_id": order_info["user_id"]})
 
    now = datetime.now()
    items = order_info.get("items", [])
    item_count = sum(int(i.get("quantity", 1)) for i in items) if items else len(items)
 
    return HTMLResponse(render(
        date=now.strftime("%d %b %Y"),
        stamp_date=now.strftime("%d.%m.%Y").upper(),
        payment_id=razorpay_payment_id,
        order_id=razorpay_order_id,
        item_count=f"{item_count} item" + ("" if item_count == 1 else "s"),
        amount=inr(order_info.get("amount", 0)/100),
    ))