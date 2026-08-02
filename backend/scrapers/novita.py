from dotenv import load_dotenv
import requests
import os
import re
from scrapers.novita_playwright import scrape_novita_datacenters
from pymongo import MongoClient

load_dotenv()



class NovitaProvider:
    def __init__(self):
        self.api_key = os.getenv("NOVITA_API_KEY")
        self.url = "https://api.novita.ai"
        self.client = MongoClient("mongodb://localhost:27017/")
        self.db = self.client["gpu_aggregator"]

    def extract_vram(self, name):
        match = re.search(r'(\d+)GB', name)
        return int(match.group(1)) if match else None
    
    def availability_rank(self, status):

        s = str(status).lower()

        if s == "high":
            return 4
        elif s == "normal":
            return 3
        elif s == "low":
            return 2
        else:
            return 1
    
    def get_gpus(self):

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        response = requests.get(
            f"{self.url}/gpu-instance/openapi/v1/products",
            headers=headers
        )

        data = response.json()
        result = []
        
        for gpu in data["data"]:
            name = gpu.get("name", "").upper()

            if "NVIDIA" in name or "RTX" in name or "H100" in name or "A100" in name:
                manufacturer = "Nvidia"
            elif "AMD" in name or "MI300" in name:
                manufacturer = "AMD"
            else:
                manufacturer = "Unknown"
                
            result.append({
                "provider": "Novita",

                "gpu_id": gpu.get("id"),

                "gpu_name": gpu.get("name"),

                "vram_gb": self.extract_vram(
                    gpu.get("name", "")
                ),

                "hourly_price": (
                    int(gpu["price"]) / 100000
                    if gpu.get("price")
                    else None
                ),

                "spot_price": (
                    int(gpu["spotPrice"]) / 100000
                    if gpu.get("spotPrice")
                    and gpu["spotPrice"] != "0"
                    else None
                ),

                "availability": (
                    gpu.get("inventoryState", "unavailable")
                    .lower()
                ),

                "deployable": gpu.get(
                    "availableDeploy",
                    False
                ),

                "regions": gpu.get(
                    "regions",
                    []
                ),

                # Unknown
                "gpu_count": 1,

                "reliability": None,

                # These actually exist!
                "cpu": gpu.get("cpuPerGpu"),

                "ram_gb": gpu.get("memoryPerGpu"),
                "manufacturer": manufacturer,
                "community_price": None,
                "secure_price": None,
            })
        result.sort(
            key=lambda x: self.availability_rank(x["availability"]),
            reverse=True
        )
        return result

class NovitaVolume(NovitaProvider):

    def __init__(self):
        super().__init__()

    def sync_novita_datacenters(self):

        collection = self.db["datacenters"]

        scraper_data = scrape_novita_datacenters()

        for dc in scraper_data:

            match = re.match(r"(.+?)\s+\((.+)\)", dc["cluster"])

            if match:
                datacenter_id = match.group(1)
                location = match.group(2)
            else:
                datacenter_id = dc["cluster"]
                location = ""

            gpu_availability = []

            for gpu in dc["available"]:
                gpu_availability.append({
                    "gpu_name": gpu,
                    "available": True
                })

            for gpu in dc["unavailable"]:
                gpu_availability.append({
                    "gpu_name": gpu,
                    "available": False
                })

            collection.update_one(
                {
                    "_id": f"novita>{datacenter_id}"
                },
                {
                    "$set": {
                        "provider": "Novita",
                        "datacenter_id": datacenter_id,
                        "name": dc["cluster"],
                        "location": location,
                        "gpuAvailability": gpu_availability
                    }
                },
                upsert=True
            )

        return scraper_data
    
    
class CompoundNovita:

    def __init__(self):
        self.provider = NovitaProvider()
        self.volume = NovitaVolume()
        
        
# nv = CompoundNovita()

# nv.provider.get_gpus()
# nv.volume.sync_novita_datacenters()