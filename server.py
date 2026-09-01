from typing import Any
import datetime
import os
import jwt
from mcp.server import MCPServer
import pandas as pd
import numpy as np
import json
from dotenv import load_dotenv
from qdrant_client import QdrantClient
import sqlite3 as sq3
from pathlib import Path
import os
from qdrant_client.models import Document
from pymongo import MongoClient
import shelve
import razorpay
load_dotenv()



razor_api=os.getenv("RAZORPAY_API")
razor_secret=os.getenv("RAZORPAY_SECRET")

jwt_secret=os.getenv("JWT_SECRET")
jwt_algorithm=os.getenv("JWT_ALGORITHM")


mongo_uri=os.getenv("MONGO_CONNECTION_URL")

client=MongoClient(mongo_uri)
database=client['database']
cart_connection=database['carts']
user_connection=database['users']
razorpay_client=razorpay.Client(auth=(razor_api,razor_secret))

shoe_catalog=pd.read_csv("shop-product-catalog.csv")
rules = pd.read_pickle("rules.pkl")


mcp=MCPServer("butlet")




def recommend_items(cart, rules, top_n=5):
    cart = {str(x) for x in cart}
    recommendations = []

    for _, rule in rules.iterrows():
        antecedent = {str(x) for x in rule["antecedents"]}
        consequent = {str(x) for x in rule["consequents"]}

        if antecedent.issubset(cart):
            for item in consequent:
                if item not in cart:
                    recommendations.append({
                        "productID": item,
                        "confidence": rule["confidence"],
                    })

    if not recommendations:
        return pd.DataFrame()

    recommendations = pd.DataFrame(recommendations)

    return (
        recommendations
        .sort_values(
            ["confidence"],
            ascending=False
        )
        .drop_duplicates("productID")
        .head(top_n)
        .reset_index(drop=True)
    )



def verify(token=None):
    if token is None:
        return False
    try:
        user_info=jwt.decode(token,jwt_secret,jwt_algorithm)
        exp_time=user_info['exp']
        curr_time=int(datetime.datetime.now().timestamp())
        if exp_time-curr_time<0:
            return False
        email=user_info['email']
        res=user_connection.find_one({'email':email})
        if res is None:
            return False
        return True

    except Exception as e:
        print(e)
        return False
    
    




@mcp.tool()
def get_product(product_name=None,product_brand=None,starting_price=0,ending_price=19999,gender='unisex',shoe_description=None,shoe_color=None):


    """
    This tool lets you search for product based on different filters, this uses a hard filter and a soft filter(shoe description is a MUST)

    params:
    product_name: Optional this can be used for specific products but only when the name is specific
    product_brand: Optional this can be used to filter products from a particular brand,
    starting_price: INTEGER Optional this can be used to find product that are atleast this price,
    ending_price: INTEGER Optional this can be used to set the upper limit for the product,
    gender:Optional this is used to filter products for a particular gender or unisex by default if nothing is passed,
    shoe_description: Optional use semantic search to find products that fit the description,
    shoe_color: Optional This can be used to filter products based on a particular color, if nothing is passed all colors are considered
    
    """
    semantic_res=None
    if shoe_description:
        client=QdrantClient(
            url=os.getenv("QDRANT_URL"),
            api_key=os.getenv("QDRANT_API"),
            cloud_inference=True
        )
        if product_brand is not None:
            shoe_description+=f'Brand: {product_brand}'
        if shoe_color is not None:
            shoe_description+=f'Color {shoe_color}'
        semantic_res=client.query_points(
            collection_name="catalog",
            query=Document(text=shoe_description,model="sentence-transformers/all-MiniLM-L6-v2"),
            with_payload=True,
            limit=10
        )
    hard_matching=None
    if product_name is not None:
        hard_matching=shoe_catalog[shoe_catalog['ProductName'].str.lower()==product_name.lower()]
    if product_brand is not None:
        hard_matching=shoe_catalog[shoe_catalog['ProductBrand'].str.lower()==product_brand.lower()]
    if int(starting_price) >0:
        if hard_matching is not None:
            hard_matching=hard_matching[hard_matching['Price']>=int(starting_price)]
        else:
            hard_matching=shoe_catalog[shoe_catalog['Price']>=int(starting_price)]
    if int(ending_price) <19999:
        if hard_matching is not None:
            
            hard_matching=hard_matching[hard_matching['Price']<=int(ending_price)]
        else:
            hard_matching=shoe_catalog[shoe_catalog['Price']<=int(ending_price)]
    if gender.lower() !='unisex':
        if hard_matching is not None:
            hard_matching=hard_matching[hard_matching['Gender'].str.lower()==gender.lower()]
        else:
            hard_matching=shoe_catalog[shoe_catalog['Gender'].str.lower()==gender.lower()]
    if shoe_color is not None:
        if hard_matching is not None:
            hard_matching=hard_matching[hard_matching['PrimaryColor'].str.lower()==shoe_color.lower()]
        else:
            hard_matching=shoe_catalog[shoe_catalog['PrimaryColor'].str.lower()==shoe_color.lower()]
    res={"direct_matching":None,"related_matching":None}
    if hard_matching is not None:
        res['direct_matching']=hard_matching.to_json(orient='records')
    if semantic_res is not None:
        soft_matching=pd.DataFrame(columns=shoe_catalog.columns)
        for id in semantic_res.points:
            if id.score<0.5:
                continue
            item=shoe_catalog[shoe_catalog['ProductID']==id.payload['P_id']]
            soft_matching=pd.concat([soft_matching,item],ignore_index=True)
        res['related_matching']=soft_matching.to_json(orient='records')
    return json.dumps(res)



@mcp.tool()
def get_cart(token=None):
    """
    This tool gets the current cart for the user containing information about the products, quantity and the total cart value
    It also provides recommendations based on the items in the cart, items that people buy with the items

    params:

    token: Mandatory token is used to  verify user to get the cart
    
    
    """
    if not verify(token):
        return {"error":"Invalid token"}
    user_id=jwt.decode(token,jwt_secret,jwt_algorithm)['_id']

    if user_id is None:
        return json.dumps({"error":"user_id is unavailable, cannot get cart info"})
    cart_info=cart_connection.find_one({'user_id':str(user_id)},{"_id":0})
    items=set()
    print(cart_info)
    for item in list(cart_info['Products'].keys()):
        id=shoe_catalog[shoe_catalog['ProductName']==item]['ProductID'].iloc[0].item()
        items.add(id)
    recommendations=recommend_items(items,rules)
    if recommendations.empty:
        return json.dumps(cart_info)
    rec_items=[]
    for ids in recommendations['productID']:
        indx=shoe_catalog[shoe_catalog['ProductID']==int(ids)]
        rec_items.append({"item":indx['ProductName'].item(),"price":indx['Price'].item()})  
    cart_info['People also buy']=rec_items
    return json.dumps(cart_info)

   
@mcp.tool()
def add_item(token=None, product_name=None,quantity=1):    



    """
    This tool can be used to add an item to the cart and recommends items bought together with this item

    params:

    token: Mandatory token is used to verify user to add items to the valid user
    product_name: Mandatory product name that is to be added to the cart
    quantity: Optional Number of items that are to be added to the cart
    
    """

    if not verify(token):
        return {"error":"Invalid token"}
    user_id=str(jwt.decode(token,jwt_secret,jwt_algorithm)['_id'])

    try:
        if user_id is None:
            return json.dumps({"error":"invalid User ID"})

        if product_name is None:
            return json.dumps({"error":"invalid product Name"})

        item=shoe_catalog[shoe_catalog['ProductName']==product_name]

        if len(item)<1:
            return json.dumps({"error":"No item was found"})

        res=cart_connection.find_one({'user_id':str(user_id)},{'_id':0})
        quantity=int(quantity)
        new_doc=False
        cart_info=res
        if res is None:
            cart_info={
                "user_id":str(user_id),
                "Products":{},
                "Amount":0
            }
            new_doc=True
        products=cart_info.get("Products")
        if products.get(item['ProductName'].iloc[0],None) is None:
            cart_info['Products'][item['ProductName'].iloc[0]]={}
            cart_info['Products'][item['ProductName'].iloc[0]]['Quantity']=quantity
        else:
            cart_info['Products'][item['ProductName'].iloc[0]]['Quantity']+=quantity
        cart_info['Amount']+=quantity*item['Price'].iloc[0].item()

        if new_doc:
            cart_connection.insert_one(cart_info)
        else:
            cart_connection.replace_one({'user_id':str(user_id)},cart_info)

        recoms=recommend_items({item['ProductID'].iloc[0].item()},rules)
        return json.dumps({"updated_cart":str(cart_info),"people also buy":str(recoms)})
        
    except Exception as e:
        return json.dumps({
            "error":"Encountered an error "+str(e)
        })




@mcp.tool()
def remove_item(token=None, product_name=None,quantity=1):    



    """
    This tool can be used to remove an item to the cart

    params:

    token: Mandatory token is used to verify user to add items to the valid user
    product_name: Mandatory product name that is to be removed from the cart
    quantity: Optional Number of items that are to be removed from the cart
    
    """

    if not verify(token):
        return {"error":"Invalid token"}
    user_id=str(jwt.decode(token,jwt_secret,jwt_algorithm)['_id'])

    try:
        if user_id is None:
            return json.dumps({"error":"invalid User ID"})

        if product_name is None:
            return json.dumps({"error":"invalid product Name"})

        if int(quantity)<0:
            return json.dumps({"error":"Cannot remove negatie quantity"})
        res=cart_connection.find_one({'user_id':str(user_id)},{'_id':0})
        quantity=int(quantity)
        cart_info=res
        if res is None:
            return {"error":"User does not have any cart"}
        products=cart_info.get("Products")
        if(products.get(product_name,None)) is None:
            return {"error":"User's cart doesnt have the item in the cart"}
        quan=products.get(product_name)['Quantity']
        
        if(quan<=quantity):
            amt=cart_info['Products'][product_name]['Quantity']
            cart_info['Products'].pop(product_name)
            cart_connection.replace_one({'user_id':str(user_id)},cart_info)
            return {"updated_cart":cart_info,"note":"quantity to be removed is larger than or equal to the quantity in thhe cart removed the item completely"}
        cart_info['Products'][product_name]['Quantity']-=quantity

        cart_connection.replace_one({'user_id':str(user_id)},cart_info)

        return json.dumps({"updated_cart":str(cart_info)})
        
    except Exception as e:
        return json.dumps({
            "error":"Encountered an error "+str(e)
        })



@mcp.tool()
def login(email=None,password=None):
    if email is None:
        return {"error":"No email was sent"}
    if password is None:
        return {"error":"No password was sent"}
    user=user_connection.find_one({"email":email})

    if user is None:
        return {"error":"Invalid email no user account is associated with this email"}
    if user['password']!=password:
        return {"error":"Invalid password"}
    user.pop('password')
    user['_id']=str(user['_id'])
    now=datetime.datetime.now()
    expiry_time=int(now.timestamp()+(3600))
    user['exp']=expiry_time
    token=jwt.encode(dict(user),jwt_secret,jwt_algorithm)

    return {"token":token}





@mcp.tool()
def generate_payment_link(token):
    """
    Tool used to generate the final checkout link, other wise proceed with the payment  if the agent is authorized to make the payment via the wallet

    params:
    token:Mandatory token is used to verify user and generate valid links
    
    """

    if not verify(token):
        return {"error":"Invalid token"}
    user_id=str(jwt.decode(token,jwt_secret,jwt_algorithm)['_id'])

    cart_info=cart_connection.find_one({"user_id":str(user_id)},{"_id":0})
    amount=cart_info['Amount']

    link="http://127.0.0.1:8000/cart/"+user_id

    return json.dumps({
        "payment_url":link,
        "cart":cart_info,
        "amount":amount
    })


if __name__=="__main__":
    mcp.run(transport="stdio")