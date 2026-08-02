from pymongo import MongoClient


client = MongoClient("mongodb://localhost:27017/")
db = client["gpu_aggregator"]

def db_get_datacenter(provider, datacenter_id):
    provider = provider.lower()
    datacenters_collection = db["datacenters"]

    return datacenters_collection.find_one(
        {"_id": f"{provider}>{datacenter_id}"},
        {"_id": 0}
    )
        
def db_get_datacenter_ids(provider):
    provider = provider.capitalize()

    datacenters_collection = db["datacenters"]

    docs = datacenters_collection.find(
        {"provider": provider},
        {"_id": 0, "datacenter_id": 1}
    )

    return [doc["datacenter_id"] for doc in docs]