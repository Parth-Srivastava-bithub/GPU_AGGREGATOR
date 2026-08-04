import subprocess

from dotenv import load_dotenv
import requests
import os
import re
from pymongo import MongoClient
from rich import print
import sqlite3
# from backend.connector import get_provider_datacenter_gpus
load_dotenv()

DB_NAME = r"C:\Users\user\Documents\GPU_AGGREGATE\backend\database\gpu_catalog.db"


def get_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn




class NovitaProvider:
    def __init__(self):
        self.api_key = os.getenv("NOVITA_API_KEY")
        self.url = "https://api.novita.ai"
        self.client = MongoClient("mongodb://localhost:27017/")
        self.db = self.client["gpu_aggregator"]

    def extract_vram(self, name):
        match = re.search(r'(\d+)GB', name)
        return int(match.group(1)) if match else None
        
    def get_provider_gpus(self):

        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT *

            FROM gpu_catalog

            WHERE LOWER(provider)=LOWER(?)

            ORDER BY hourly_price ASC
            """,
            ("novita",)
        )

        columns = [col[0] for col in cursor.description]

        rows = [
            dict(zip(columns, row))
            for row in cursor.fetchall()
        ]

        conn.close()

        return {
            "provider": "novita",
            "count": len(rows),
            "gpus": rows
        }
    
    def get_gpu_metadata(self, gpu_id):
        conn = get_connection()
        cursor = conn.cursor()

        gpu_id = f"novita>{gpu_id}"  # Prefix the GPU ID with "novita>"
        cursor.execute(
            """
            SELECT *

            FROM gpu_catalog

            WHERE LOWER(provider)=LOWER(?)
            AND gpu_id=?
            """,
            ("novita", gpu_id)
        )

        columns = [col[0] for col in cursor.description]

        row = cursor.fetchone()

        conn.close()

        if row:
            return dict(zip(columns, row))
        else:
            return {"message": "GPU not found."}
    
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
    def __init__(self):
        super().__init__()
        self.pods_url = "https://api.novita.ai/gpus/v2/instances"
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
    def get_user_pods(self, status=None):
        url = self.pods_url
        if status:
            url = f"{url}?status={status}"

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

    def get_resolve_info(self):
        availabile_gpus = self.get_provider_gpus()
        gpu_ids = [(gpu["gpu_id"].split(">")[1], gpu["gpu_name"]) for gpu in availabile_gpus.get("gpus", [])]
        storage_ids = [(volume["storageId"], volume["storageName"]) for volume in self.get_user_volume().get("data", [])]
        return {
            "gpu_ids": gpu_ids,
            "storage_ids": storage_ids
        }
    def __disable__create_instance(
        self,
        name,
        product_id=None,
        image="pytorch/pytorch:latest",
        billing_mode="postpaid",
        gpu_num=1,
        rootfs_size_gb=20,
        volume_id=None,
        mount_point="/workspace",
        ports=None,
        env=None,
        command="",
        entrypoint="",
        candidate_regions=None,
        jupyter=True,
        auto_migrate=False,
        prepaid_months=1,
        prepaid_auto_renew=False,
        prepaid_auto_renew_months=1,
    ):
        resolve_info = self.get_resolve_info()

        available_gpus = resolve_info.get("gpu_ids", [])
        available_products = [gpu_id for gpu_id, _ in available_gpus]

        available_volumes = resolve_info.get("storage_ids", [])
        available_volume_ids = [storage_id for storage_id, _ in available_volumes]

        if product_id is None:
            return {
                "message": "product_id is required. Choose one from the available products.",
                "available_products": [
                    {"product_id": gpu_id, "gpu_name": gpu_name}
                    for gpu_id, gpu_name in available_gpus
                ],
            }

        if product_id not in available_products:
            return {
                "message": "Invalid product_id. Choose one from the available products.",
                "available_products": [
                    {"product_id": gpu_id, "gpu_name": gpu_name}
                    for gpu_id, gpu_name in available_gpus
                ],
            }

        if volume_id is None:
            return {
                "message": "volume_id is required. Choose one from your available volumes.",
                "available_volumes": [
                    {"storage_id": storage_id, "storage_name": storage_name}
                    for storage_id, storage_name in available_volumes
                ],
            }

        if volume_id not in available_volume_ids:
            return {
                "message": "Invalid volume_id. Choose one from your available volumes.",
                "available_volumes": [
                    {"storage_id": storage_id, "storage_name": storage_name}
                    for storage_id, storage_name in available_volumes
                ],
            }

        payload = {
            "name": name,
            "product_id": product_id,
            "image": image,
            "billing": {
                "mode": billing_mode,
            },
            "resource": {
                "gpu_num": gpu_num,
                "rootfs_size_gb": rootfs_size_gb,
            },
            "volumes": [
                {
                    "type": "network",
                    "id": volume_id,
                    "mount_point": mount_point,
                }
            ],
            "ports": ports or [
                {"port": 8888, "protocol": "http"}
            ],
            "envs": [
                {"key": k, "value": v}
                for k, v in env.items()
            ] if env else [],
            "candidate_regions": candidate_regions or [],
            "tools": {
                "jupyter": {
                    "enabled": jupyter,
                    "port": 8888,
                    "protocol": "http",
                }
            },
            "auto_migrate": {
                "enabled": auto_migrate,
                "include_system_disk": False,
            },
        }

        if billing_mode == "prepaid":
            payload["billing"]["prepaid"] = {
                "months": prepaid_months,
                "auto_renew": {
                    "enabled": prepaid_auto_renew,
                    "months": prepaid_auto_renew_months,
                },
            }

        response = requests.post(
            "https://api.novita.ai/gpus/v2/instances",
            headers=self.headers,
            json=payload,
        )

        if response.status_code in (200, 201):
            return response.json()

        return {
            "status_code": response.status_code,
            "payload": payload,
            "error": response.text,
        }
    def __disable2__create_instance(
        self,
        name,
        product_id,
        volume_id,
        image="pytorch/pytorch:latest",
        billing_mode="postpaid",
        gpu_num=1,
        rootfs_size_gb=20,
        mount_point="/workspace",
        ports=None,
        env=None,
        command="",
        entrypoint="",
    ):
        url = "https://api.novita.ai/gpus/v2/instances"

        datacenters = self.get_datacenters_having_gpu(product_id)
        gpu = self.get_gpu_metadata(product_id)
        gpu_name = gpu['gpu_name']
        print(gpu_name)
        payload = {
            "name": name,
            "product_id": product_id,
            "image": image,

            "billing": {
                "mode": billing_mode
            },

            "resource": {
                "gpu_num": gpu_num,
                "rootfs_size_gb": rootfs_size_gb,
            },

            "volumes": [
                {
                    "type": "network",
                    "id": volume_id,
                    "mount_point": mount_point,
                }
            ],

            "candidate_regions": [
                dc["datacenter_id"]
                for dc in datacenters
            ],

            "ports": ports or [
                {
                    "port": 8888,
                    "protocol": "http"
                }
            ],

            "envs": [
                {"key": k, "value": v}
                for k, v in env.items()
            ] if env else [],

            "command": command,
            "entrypoint": entrypoint,

            "tools": {
                "jupyter": {
                    "enabled": True,
                    "port": 8888,
                    "protocol": "http"
                }
            },

            "auto_migrate": {
                "enabled": False,
                "include_system_disk": False
            }
        }

        payload.pop("ports")

        regions = requests.get(
            "https://api.novita.ai/gpus/v2/regions",
            headers=self.headers
        ).json()["data"]
        print(regions)
        candidate_regions = [
            region["id"]
            for region in regions
            if gpu_name in region["gpus"]
        ]      
        payload["candidate_regions"] = candidate_regions

        print("Candidate Regions:", payload["candidate_regions"])
        # print(payload)
        response = requests.post(
            url,
            headers=self.headers,
            json=payload
        )

        if response.status_code in (200, 201):
            return response.json()

        return {
            "status_code": response.status_code,
            "payload": payload,
            "error": response.text
        }
    
    def create_pod(
        self,
        product_id,
        image,
        gpu_num=1,
        name=None,
        rootfs_size_gb=20,
        billing="onDemand",
        env=None,
        command=None,
    ):
        cmd = [
            "novita",
            "gpu",
            "create",
            "--product-id",
            product_id,
            "--image",
            image,
            "--gpu-num",
            str(gpu_num),
            "--rootfs",
            str(rootfs_size_gb),
            "--billing",
            billing,
        ]

        if name:
            cmd.extend(["--name", name])

        if command:
            cmd.extend(["--command", command])

        if env:
            for key, value in env.items():
                cmd.extend(["--env", f"{key}={value}"])

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "NOVITA_API_KEY": os.getenv("NOVITA_API_KEY")
            }
        )

        if result.returncode == 0:
            return {
                "success": True,
                "output": result.stdout.strip()
            }

        return {
            "success": False,
            "error": result.stderr.strip() or result.stdout.strip()
        }
    
    def get_datacenters_having_gpu(self, product_id):
        """
        Returns all datacenter IDs where the given GPU product is available.

        Example:
            product_id = "4090.16c62g.os"
        """
        
        gpus_data = self.get_provider_gpus()
        def get_product(product_id):
            for gpu in gpus_data['gpus']:
                if gpu["gpu_id"].split(">")[1] == product_id:
                    return gpu
            return {"message": "Product not found"}

        
        # Product details
        product = get_product(product_id)
        print(product)
        if "message" in product:
            return product

        gpu_name = product["gpu_name"]

        datacenters = self.db["datacenters"].find(
            {"provider": "Novita"}
        )

        matching_datacenters = []

        for dc in datacenters:
            for gpu in dc.get("gpuAvailability", []):
                if gpu["gpu_name"] == gpu_name and gpu["available"]:
                    matching_datacenters.append({
                        "datacenter_id": dc["datacenter_id"],
                        "name": dc["name"],
                        "location": dc["location"],
                    })
                    break

        return matching_datacenters
    def get_product_regions(self, product_id):
        """
        Returns the region_ids for a given Novita product_id.

        Example:
            get_product_regions("4090.16c62g.os")
        """

        response = requests.get(
            "https://api.novita.ai/gpus/v2/products",
            headers=self.headers,
            params={
                "type": "gpu",
                "category": "instance"
            }
        )

        if response.status_code != 200:
            return {
                "message": f"Failed to fetch products: {response.text}"
            }

        products = response.json().get("data", [])

        for product in products:
            if product["id"] == product_id:
                return {
                    "product_id": product["id"],
                    "gpu_name": product["name"],
                    "region_ids": product.get("region_ids", [])
                }

        return {
            "message": f"Product '{product_id}' not found."
        }
        
    
    def start_pod(self,pod_id):

        try:
            subprocess.run(
                [
                    "novita",
                        "--api-key",
                    self.api_key,
                    "gpu",
                    "start",
                    pod_id
                ],
                check=True,
            )
        except subprocess.CalledProcessError as e:
            return {
                "success": False,
                "error": str(e)
            }
        return {
            "success": True
        }

    def stop_pod(self, pod_id):
        try:
            subprocess.run(
                [
                    "novita",
                    "--api-key",
                    self.api_key,
                    "gpu",
                    "stop",
                    pod_id
                ],
                check=True,
            )
        except subprocess.CalledProcessError as e:
            return {
                "success": False,
                "error": str(e)
            }
        return {
            "success": True
        }
        
    def delete_pod(self, pod_id):
        try:
            subprocess.run(
                [
                    "novita",
                    "--api-key",
                    self.api_key,
                    "gpu",
                    "delete",
                    pod_id
                ],
                check=True,
            )
        except subprocess.CalledProcessError as e:
            return {
                "success": False,
                "error": str(e)
            }
        return {
            "success": True
        }
    
class CompoundNovita:

    def __init__(self):
        self.provider = NovitaProvider()
        self.volume = NovitaVolume()
        
        self.pods = NovitaPods()

