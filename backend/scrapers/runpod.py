from dotenv import load_dotenv
from rich import print
import requests
import json
import re
import sys
import os
import typing
load_dotenv()
from datetime import datetime, timedelta
import json
import requests
import json
import subprocess
from pymongo import MongoClient


class RunpodProvider:
    def __init__(self):
        self.volume_url = "https://rest.runpod.io/v1/networkvolumes"
        self.headers = {
            "Authorization": f"Bearer {os.getenv('RUNPOD_API_KEY')}",
            "Content-Type": "application/json"
        }
        self.client = MongoClient("mongodb://localhost:27017/")
        self.db = self.client["gpu_aggregator"]

class RunpodVolume(RunpodProvider):
    def __init__(self):
        super().__init__()

    
    def sync_runpod_datacenters(self):
        datacenters_collection = self.db['datacenters']
        
        result = subprocess.run(
            [
                r"C:\Users\user\runpodctl.exe",
                "datacenter",
                "list",
                "-o",
                "json"
            ],
            capture_output=True,
            text=True,
            check=True
        )
        data = json.loads(result.stdout)
        
        for dc in data:
            datacenters_collection.update_one(
                {"_id": f"runpod>{dc['id']}"},
                {
                    "$set": {
                        "provider": "RunPod",
                        "datacenter_id": dc["id"],
                        "name": dc["name"],
                        "location": dc["location"],
                        "gpuAvailability": dc.get("gpuAvailability", [])
                    }
                },
                upsert=True
            )
            
    def get_runpod_datacenter(self, datacenter_id):
        datacenters_collection = self.db["datacenters"]

        doc = datacenters_collection.find_one(
            {"_id": f"runpod>{datacenter_id}"}
        )

        if doc:
            return doc
        else:
            return ("Datacenter not found.")
            
    def get_gpu_availability(self, datacenter_id):

        doc = self.db["datacenters"].find_one(
            {"_id": f"runpod>{datacenter_id}"}
        )

        if not doc:
            return []

        return doc.get("gpuAvailability", [])  

    def get_datacenter_ids(self):
        datacenters_collection = self.db["datacenters"]

        docs = datacenters_collection.find(
            {},
            {"_id": 0, "datacenter_id": 1}
        )

        return [doc["datacenter_id"] for doc in docs]

class CompoundRunpod:
    def __init__(self):
        self.volume = RunpodVolume()
        
# rv = RunpodVolume()
# print(rv.get_gpu_availability("CA-MTL-1"))