from typing import Any
import os
import httpx2
import logging
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


mongo_uri=os.getenv("MONGO_CONNECTION_URL")

client=MongoClient(mongo_uri)
database=client['database']
cart_connection=database['carts']
razorpay_client=razorpay.Client(auth=(razor_api,razor_secret))

shoe_catalog=pd.read_csv("shop-product-catalog.csv")

mcp=MCPServer("butlet")






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

    try:

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
                limit=30
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
                if id.score<0.3:
                    continue
                item=shoe_catalog[shoe_catalog['ProductID']==id.payload['P_id']]
                soft_matching=pd.concat([soft_matching,item],ignore_index=True)
            res['related_matching']=soft_matching.to_json(orient='records')

        return json.dumps(res)
    except Exception as e:
        with open("error.txt",'w') as f:
            f.write(str(e))




@mcp.tool()
def get_cart(user_id=None):
    """
    This tool gets the current cart for the user containing information about the products, quantity and the total cart value

    params:

    user_id: Mandatory user_id is required to the user specific cart
    
    
    """
    try:
        if user_id is None:
            return json.dumps({"error":"user_id is unavailable, cannot get cart info"})

        cart_info=cart_connection.find_one({'user_id':str(user_id)},{"_id":0})

        return json.dumps(cart_info)
    except Exception as e:
        print(e)

   
@mcp.tool()
def add_item(user_id=None, product_name=None,quantity=1):    



    """
    This tool can be used to add an item to the cart

    params:

    user_id: Mandatory user_id is required to access the user specific cart
    product_name: Mandatory product name that is to be added to the cart
    quantity: Optional Number of items that are to be added to the cart
    
    """
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

        return json.dumps({"updated_cart":str(cart_info)})
        
    except Exception as e:
        print(e)







@mcp.tool()
def generate_payment_link(user_id=None,email=None):
    cart_info=cart_connection.find_one({"user_id":str(user_id)},{"_id":0})
    amount=cart_info['Amount']

    link="www.pay_url.com/"+user_id

    return json.dumps({
        "payment_url":link,
        "cart":cart_info
    })



print(add_item("5505","Air Force 1"))


if __name__=="__main__":
    mcp.run(transport="stdio")
