import subprocess

from dotenv import load_dotenv
import requests
import os
import re
from pymongo import MongoClient
from rich import print
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
        self.region_endpoint = "https://api.novita.ai/gpus/v2/regions"
        self.create_volume_url = "https://api.novita.ai/gpus/v2/storage/create"
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
    
    def delete_db(self):
        self.db["datacenters"].delete_many({"provider": "Novita"})
    
    def __deprecated__sync_novita_datacenters(self):

        collection = self.db["datacenters"]

        scraper_data = "scrape_novita_datacenters()"

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
    
    def sync_novita_datacenters(self):

        collection = self.db["datacenters"]

        response = requests.get(
            self.region_endpoint,
            headers={
                "Authorization": f"Bearer {self.api_key}"
            }
        )

        response.raise_for_status()

        regions = response.json()["data"]

        for region in regions:

            gpu_availability = [
                {
                    "gpu_name": gpu,
                    "available": True
                }
                for gpu in region.get("gpus", [])
            ]

            match = re.match(r"(.+?)\s+\((.+)\)", region["name"])

            if match:
                location = match.group(2)
            else:
                location = ""

            collection.update_one(
                {
                    "_id": f"novita>{region['id']}"
                },
                {
                    "$set": {
                        "provider": "Novita",
                        "datacenter_id": region["id"],   # region_id ko hi datacenter_id maan lo

                        "name": region["name"],
                        "location": location,

                        "gpuAvailability": gpu_availability,

                        "network_volume": region["feature"].get(
                            "network_volume", False
                        ),

                        "instance_vpc_network": region["feature"].get(
                            "instance_vpc_network", False
                        )
                    }
                },
                upsert=True
            )

        return regions
    
    
    def get_datacenter(self, datacenter_id):
        return self.db["datacenters"].find_one(
            {"_id": f"novita>{datacenter_id}"}
        )
            
    def get_datacenter_ids(self):
        datacenters_collection = self.db["datacenters"]

        return list(
            datacenters_collection.find(
                {"provider": "Novita"},
                {"_id": 0, "datacenter_id": 1}
            )
        )


    def get_gpu_availability_across_datacenters(self):
        datacenter_gpu_availability = {}
        datacenters_collection = self.db["datacenters"]
        provider = "Novita"
        
        datacollection = datacenters_collection.find(
            {"provider": provider},
            {"_id": 0, "datacenter_id": 1, "gpuAvailability": 1}
        )
        
        for doc in datacollection:
            datacenter_id = doc["datacenter_id"]
            gpu_availability = doc.get("gpuAvailability", [])
            datacenter_gpu_availability[datacenter_id] = gpu_availability

        return datacenter_gpu_availability

    # curl command novita storage create --cluster-id <cluster_id> --name data-volume --size 100
    def create_volume(self, datacenter_id, name, size):
        subprocess.run(
            [
                "novita",
                "--api-key",
                self.api_key,
                "storage",
                "create",
                "--cluster-id",
                datacenter_id,
                "--name",
                name,
                "--size",
                str(size),
            ],
            check=True,
        )
        
    def get_user_volume(self):
        url = f"{self.url}/gpu-instance/openapi/v1/networkstorages/list"

        headers = {
            "Authorization": f"Bearer {self.api_key}"
        }

        response = requests.get(url, headers=headers)
        response.raise_for_status()

        return response.json()
    
    def delete_volume(self, storage_id):
        url = f"{self.url}/gpu-instance/openapi/v1/networkstorage/delete"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {"storageId": storage_id}

        response = requests.post(url, headers=headers, json=payload)
        try:
            response.raise_for_status()
            return {"message": "Volume deleted successfully"}
        except requests.exceptions.RequestException as e:
            # print(f"{response.status_code} - {response.text}")
            return {"message": f"Failed to delete volume: {str(e)}"}
        
class NovitaPods(NovitaProvider):
    """
    curl --request GET \
  --url 'https://api.novita.ai/gpus/v2/instances?status=running' \
  --header 'Authorization: Bearer YOUR_API_KEY'
    """
    
    def __init__(self):
        super().__init__()
        self.pods_url = "https://api.novita.ai/gpus/v2/instances"
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
    def get_user_pods(self, status="running"):
        url = f"{self.pods_url}?status={status}"
        response = requests.get(url, headers=self.headers)
        try:
            response.raise_for_status()
            print(f"Successfully fetched user pods: {response.status_code}")
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"Error fetching user pods: {response.status_code} - {response.text}")
            return {"message": f"Failed to fetch user pods: {str(e)}"}

    def get_pod(self, pod_id):
        pods = self.get_user_pods()
        for pod in pods.get("data", []):
            if pod.get("id") == pod_id:
                return pod
        return {"message": f"Pod with ID {pod_id} not found."}
    
class CompoundNovita:

    def __init__(self):
        self.provider = NovitaProvider()
        self.volume = NovitaVolume()
        
        self.pods = NovitaPods()


# nv = CompoundNovita()
# nv.pods.get_user_pods()


# {
#     'data': [
#         {
#             'id': '37d312386c80a3b9',
#             'name': 'Gemma 4 31B',
#             'product_id': '4090.16c62g.os',
#             'billing': {
#                 'mode': 'postpaid'
#             },
#             'image': 
# 'novitalabs/gemma-4-31b-it:v0.03',
#             'registry_auth_id': '',
#             'entrypoint': '',
#             'command': '--model 
# /hf_data/hub/models--gg-hf-gg--gemma-4-31B-it/snapshots/05f9f47c69f1b7c6dea5e3a790a0411fa705b2c1 --served-model-name gemma-4-31b-it 
# --trust-remote-code 
# --enable-auto-tool-choice --tool-call-parsergemma4 --tensor-parallel-size 1 
# --max-cudagraph-capture-size 64 
# --gpu-memory-utilization 0.96 
# --max-model-len 32768 
# --limit-mm-per-prompt.image 64 --port 30000 
# --reasoning-parser gemma4',
#             'envs': [
#                 {
#                     'key': 
# 'CUDA_VISIBLE_DEVICES',
#                     'value': '0'
#                 },
#                 {
#                     'key': 
# 'FLASHINFER_DISABLE_VERSION_CHECK',
#                     'value': '1'
#                 },
#                 {
#                     'key': 
# 'VLLM_AUDIO_FETCH_TIMEOUT',
#                     'value': '100'
#                 },
#                 {
#                     'key': 
# 'VLLM_IMAGE_FETCH_TIMEOUT',
#                     'value': '100'
#                 }
#             ],
#             'ports': [
#                 {
#                     'port': 30000,
#                     'protocol': 'http',
#                     'endpoint': 
# 'https://37d312386c80a3b9-30000.us-ca-6.gpu-instance.novita.ai'
#                 }
#             ],
#             'resource_specs': {
#                 'rootfs_size_gb': 100,
#                 'gpu_num': 1,
#                 'cpu_num': 16,
#                 'memory_gb': '62',
#                 'gpu_ids': [3]
#             },
#             'volumes': [],
#             'region': 'us-ca-6',
#             'auto_migrate': {
#                 'enabled': True,
#                 'include_system_disk': True
#             },
#             'created_at': '1785780950',
#             'last_started_at': '1785780954',            'last_stopped_at': '0',
#             'status': {
#                 'status': 'running',
#                 'error': '',
#                 'message': ''
#             },
#             'member_id': '',
#             'owner_id': 
# 'a45681a6-88c0-46b4-86f0-6f1d286841e2',
#             'region_version': 'v2',
#             'network': {
#                 'id': '',
#                 'ip': ''
#             },
#             'type': 'gpu'
#         }
#     ],
#     'next_cursor': '',
#     'has_more': False,
#     'total': 1
# }