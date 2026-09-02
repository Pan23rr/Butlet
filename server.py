from typing import Any
import datetime
from pydantic import AnyHttpUrl
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
from mcp.server.auth.settings import AuthSettings
from config import config
from mcp.server.auth.middleware.auth_context import get_access_token
from token_verifier import IntrospectionTokenVerifier
from urllib.parse import urljoin
load_dotenv()



razor_api=os.getenv("RAZORPAY_API")
razor_secret=os.getenv("RAZORPAY_SECRET")

mongo_uri=os.getenv("MONGO_CONNECTION_URL")

client=MongoClient(mongo_uri)
database=client['database']
cart_connection=database['carts']
user_connection=database['users']
payment_connection=database['payments']
razorpay_client=razorpay.Client(auth=(razor_api,razor_secret))

shoe_catalog=pd.read_csv("shop-product-catalog.csv")
rules = pd.read_pickle("rules.pkl")





def create_oauth_urls() -> dict[str, str]:
    auth_base_url = config.auth_base_url

    return {
        "issuer": auth_base_url,
        "introspection_endpoint": urljoin(auth_base_url, "protocol/openid-connect/token/introspect"),
        "authorization_endpoint": urljoin(auth_base_url, "protocol/openid-connect/auth"),
        "token_endpoint": urljoin(auth_base_url, "protocol/openid-connect/token"),
    }



def create_server() -> MCPServer:

    oauth_urls = create_oauth_urls()


    token_verifier = IntrospectionTokenVerifier(
        introspection_endpoint=oauth_urls["introspection_endpoint"],
        server_url=config.server_url,
        client_id=config.OAUTH_CLIENT_ID,
        client_secret=config.OAUTH_CLIENT_SECRET,
    )

    mcp = MCPServer(
        name="butlet",
        instructions="Shoe lookup Server",
        debug=True,
        token_verifier=token_verifier,
        auth=AuthSettings(
            issuer_url=AnyHttpUrl(oauth_urls["issuer"]),
            required_scopes=[config.MCP_SCOPE],
            resource_server_url=AnyHttpUrl(config.server_url),
        ),
    )

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
    def get_cart():
        """
        This tool gets the current cart for the user containing information about the products, quantity and the total cart value
        It also provides recommendations based on the items in the cart, items that people buy with the items
        """
        token=get_access_token()
        user_id=token.claims['azp']

        cart_info=cart_connection.find_one({'user_id':str(user_id)},{"_id":0})
        items=set()
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
    def add_item(product_name=None,quantity=1):    



        """
        This tool can be used to add an item to the cart and recommends items bought together with this item
        Unless explicitly states the otherwise , user must be provided with options / recommendations along with the products "people also buy"

        params:

        product_name: Mandatory product name that is to be added to the cart
        quantity: Optional Number of items that are to be added to the cart

        """

        token=get_access_token()
        user_id=token.claims['azp']

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
            rec_items=[]
            for ids in recoms['productID']:
                indx=shoe_catalog[shoe_catalog['ProductID']==int(ids)]
                rec_items.append({"item":indx['ProductName'].item(),"price":indx['Price'].item()})

            return json.dumps({"updated_cart":str(cart_info),"people also buy":str(rec_items)})

        except Exception as e:
            return json.dumps({
                "error":"Encountered an error "+str(e)
            })


    @mcp.tool()
    def remove_item(product_name=None,quantity=1):    

        """
        This tool can be used to remove an item to the cart

        params:

        product_name: Mandatory product name that is to be removed from the cart
        quantity: Optional Number of items that are to be removed from the cart

        """

        token=get_access_token()
        user_id=token.claims['azp']


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
            item=shoe_catalog[shoe_catalog['ProductName'].str.lower()==product_name.lower()]
            if(quan<=quantity):
                amt=cart_info['Products'][product_name]['Quantity']
                cart_info['Products'].pop(product_name)
                cart_info['Amount']-=quan*item['Price'].iloc[0].item()
                cart_connection.replace_one({'user_id':str(user_id)},cart_info)
                return {"updated_cart":cart_info,"note":"quantity to be removed is larger than or equal to the quantity in thhe cart removed the item completely"}

            cart_info['Products'][product_name]['Quantity']-=quantity
            cart_info['Amount']-=quantity*item['Price'].iloc[0].item()

            cart_connection.replace_one({'user_id':str(user_id)},cart_info)

            return json.dumps({"updated_cart":str(cart_info)})

        except Exception as e:
            return json.dumps({
                "error":"Encountered an error "+str(e)
            })





    @mcp.tool()
    def get_recent_order():
        """
        This tool is used to get the most recent order placed by the user along with the cart info
        """

        token=get_access_token()
        user_id=token['azp']

        pay_info=payment_connection.find_one({'user_id':user_id})
        payments_made=list(pay_info)[-1]

        last_payment={}
        last_payment['order_info']=payments_made['cart']
        last_payment['order_info'].pop('_id')
        last_payment['order_info'].pop('user_id')
        last_payment['user_info']={
            "user_mail":payments_made['mail'],
            "number":payments_made['number']
        }

        return last_payment

        




    @mcp.tool()
    def generate_payment_link(mail,number):
        """
        Tool used to generate the final checkout link, other wise proceed with the payment  if the agent is authorized to make the payment via the wallet

        params:
        mail: Mandatory, User email that should be used for purchase
        number: Mandatory, Phone number that should be used for purchase

        """
        if mail is None:
            return {"error":"Mail is required to generate the payment"}
        if number is None:
            return {"error":"Number is required to generate the payment"}

        token=get_access_token()
        user_id=token.claims['azp']


        cart_info=cart_connection.find_one({"user_id":str(user_id)},{"_id":0})
        user_connection.insert_one({
            "user_id":user_id,
            "mail":mail,
            "number":number
        })
        amount=cart_info['Amount']

        link="http://127.0.0.1:8000/cart/"+user_id

        return json.dumps({
            "payment_url":link,
            "cart":cart_info,
            "amount":amount,
        })

    return mcp

from mcp.server.transport_security import TransportSecuritySettings

import logging
logger = logging.getLogger(__name__)

transport_security = TransportSecuritySettings(
    allowed_hosts=[
        "floss-taekwondo-symptom.ngrok-free.dev",
    ],
)

def main() -> int:
    
    logging.basicConfig(level=logging.INFO)

    oauth_urls = create_oauth_urls()

    try:
        mcp_server = create_server()

        logger.info("Starting MCP Server on %s:%s", config.HOST, config.PORT)
        logger.info("Authorization Server: %s", oauth_urls["issuer"])

        mcp_server.run(
            transport="streamable-http",
            host="localhost",
            port=3000,
            streamable_http_path="/",
            transport_security=transport_security
        )
        return 0

    except Exception:
        logger.exception("Server error")
        return 1


if __name__ == "__main__":
    exit(main())
