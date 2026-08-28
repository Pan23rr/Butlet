from qdrant_client import QdrantClient
from qdrant_client.models import Distance,VectorParams,PointStruct,Document
from dotenv import load_dotenv
import os
import pandas as pd
load_dotenv()


def upload_job(product_description,product_ids,color,brand):
    client=QdrantClient(
        url=os.getenv("QDRANT_URL"),
        api_key=os.getenv("QDRANT_API"),
        cloud_inference=True
    )

    client.create_collection(
        collection_name="catalog",
        vectors_config=VectorParams(size=384,distance=Distance.COSINE)
    )
    client.close()

    points=[]

    for i,description in enumerate(product_description):
        
        point=PointStruct(
            id=i,
            vector=Document(
                text=description+" color: "+str(color[i])+"brand: "+str(brand[i]),
                model="sentence-transformers/all-MiniLM-L6-v2",
            ),
            payload={
                "P_id":int(product_ids[i]),
            }
        )
        points.append(point)

    client=QdrantClient(
        url=os.getenv("QDRANT_URL"),
        api_key=os.getenv("QDRANT_API"),
        cloud_inference=True
    )

    client.upsert(
        collection_name="catalog",
        points=points
    )


catalog=pd.read_csv("shop-product-catalog.csv")

upload_job(catalog['Description'],catalog['ProductID'],catalog['PrimaryColor'],catalog['ProductBrand'])
