from pymongo import MongoClient
import os
from dotenv import load_dotenv

load_dotenv()

mongo_uri=os.getenv("MONGO_CONNECTION_URL")


client=MongoClient(mongo_uri)


database=client['database']
carts=database['carts']

res=carts.find_one({"user_id":"110"},{"_id":0})



print(res)