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

import sqlite3

DB_NAME = r"C:\Users\user\Documents\GPU_AGGREGATE\backend\database\gpu_catalog.db"


def get_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

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
                        "provider": "Runpod",
                        "datacenter_id": dc["id"],
                        "name": dc["name"],
                        "location": dc["location"],
                        "gpuAvailability": dc.get("gpuAvailability", [])
                    }
                },
                upsert=True
            )
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
            ("runpod",)
        )

        columns = [col[0] for col in cursor.description]

        rows = [
            dict(zip(columns, row))
            for row in cursor.fetchall()
        ]

        conn.close()

        return {
            "provider": "runpod",
            "count": len(rows),
            "gpus": rows
        }
    def get_gpu_metadata(self, gpu_id):
        conn = get_connection()
        cursor = conn.cursor()
        gpu_id = f"runpod>{gpu_id}"  # Prefix the GPU ID with "runpod>"
        cursor.execute(
            """
            SELECT *

            FROM gpu_catalog

            WHERE LOWER(provider)=LOWER(?)
            AND gpu_id=?
            """,
            ("runpod", gpu_id)
        )

        columns = [col[0] for col in cursor.description]

        row = cursor.fetchone()

        conn.close()

        if row:
            return dict(zip(columns, row))
        else:
            return {"message": "GPU not found."}
             
    def get_datacenter(self, datacenter_id):
        datacenters_collection = self.db["datacenters"]

        doc = datacenters_collection.find_one(
            {"_id": f"runpod>{datacenter_id}"}
        )

        if doc:
            return doc
        else:
            return {"message": "Datacenter not found."}

    def get_datacenter_ids(self):
        datacenters_collection = self.db["datacenters"]

        docs = datacenters_collection.find(
            {"provider": "Runpod"},
            {"_id": 0, "datacenter_id": 1}
        )

        return [doc["datacenter_id"] for doc in docs]

    def get_gpu_availability_across_datacenters(self):
        datacenter_gpu_availability = {}
        datacenters_collection = self.db["datacenters"]
        provider = "Runpod"
        
        datacollection = datacenters_collection.find(
            {"provider": provider},
            {"_id": 0, "datacenter_id": 1, "gpuAvailability": 1}
        )
        
        for doc in datacollection:
            datacenter_id = doc["datacenter_id"]
            gpu_availability = doc.get("gpuAvailability", [])
            datacenter_gpu_availability[datacenter_id] = gpu_availability

        return datacenter_gpu_availability
    



    def create_volume(self, datacenter_id, name, size):
        """
            curl --request POST \
            --url https://rest.runpod.io/v1/networkvolumes \
            --header 'Authorization: Bearer <token>' \
            --header 'Content-Type: application/json' \
            --data '
            {
            "dataCenterId": "EU-RO-1",
            "name": "my network volume",
            "size": 50
            }
            '

        Output:
        {
            "dataCenterId": "EU-RO-1",
            "id": "agv6w2qcg7",
            "name": "my network volume",
            "size": 50
        }
        """
        payload = {
            "dataCenterId": datacenter_id,
            "name": name,
            "size": size
        }
        
        response = requests.post(
            self.volume_url,
            headers=self.headers,
            json=payload
        )
        
        if response.status_code == 200:
            return response.json()
        else:
            return {"message": f"Failed to create volume: {response.text}"}
    
    def get_user_volume(self):
        response = requests.get(
            self.volume_url,
            headers=self.headers
        )
        
        if response.status_code == 200:
            return response.json()
        else:
            return {"message": f"Failed to fetch user volumes: {response.text}"}
    
    def delete_volume(self, volume_id):
        delete_url = f"{self.volume_url}/{volume_id}"
        
        response = requests.delete(
            delete_url,
            headers=self.headers
        )
        if response.status_code == 204:
            return {"message": "Volume deleted successfully"}
        else:
            return {"message": f"Failed to delete volume: {response.text}"}

class RunpodPods(RunpodProvider):
    def __init__(self):
        super().__init__()
        self.volume = RunpodVolume()
    
    def get_user_pods(self):
        pods_url = "https://rest.runpod.io/v1/pods"
        response = requests.get(
            pods_url,
            headers=self.headers
        )
        
        if response.status_code == 200:
            return response.json()
        else:
            return {"message": f"Failed to fetch user pods: {response.text}"}

    def get_pod(self, pod_id):
        pods = self.get_user_pods()
        for pod in pods:
            if pod.get("id") == pod_id:
                return pod
        return {"message": f"Pod with ID {pod_id} not found."}

    def resolve_gpu(self, gpu_name=None):
        """
        Resolve GPU name into compatible GPU Type IDs and Datacenter IDs.

        If gpu_name is None:
            - Returns all available datacenters.
            - Returns an empty gpuTypeIds list so RunPod scheduler can choose.
        """

        availability = self.volume.get_gpu_availability_across_datacenters()

        # User didn't specify a GPU
        if gpu_name is None:
            return {
                "gpuTypeIds": [],
                "dataCenterIds": self.volume.get_datacenter_ids()
            }

        datacenter_ids = []
        gpu_type_ids = set()

        for dc, gpus in availability.items():
            for gpu in gpus:
                if gpu["displayName"].lower() == gpu_name.lower():
                    datacenter_ids.append(dc)
                    gpu_type_ids.add(gpu["gpuId"])

        if not datacenter_ids:
            raise ValueError(f"GPU '{gpu_name}' not found in any datacenter.")

        return {
            "gpuTypeIds": list(gpu_type_ids),
            "dataCenterIds": datacenter_ids
        }
    
    def get_gpu_availbable_datacenter_ids(self, gpu_id):
        """
        Get available datacenter IDs for a specific GPU ID.
        """
        availability = self.volume.get_gpu_availability_across_datacenters()

        gpu_info = []
        for dc, gpus in availability.items():
            for gpu in gpus:
                if gpu["gpuId"] == gpu_id:
                    gpu_info.append({
                        # everything from the gpu dict, plus the datacenter id
                        **gpu,
                        "datacenter_id": dc
                    })

        if not gpu_info:
            raise ValueError(f"GPU '{gpu_id}' not found in any datacenter.")

        return gpu_info
    
    def get_gpu_info(self, gpu_id=None):
        """
        If gpu_id is None:
            Return all available GPUs.

        If gpu_id is provided:
            Return:
            - GPU metadata
            - Datacenter IDs where this GPU is available
        """

        if gpu_id is None:
            gpu_names_with_id = [
                {
                    "gpu_name": gpu["gpu_name"],
                    "gpu_id": gpu["gpu_id"].split(">")[1],
                    "availability": gpu["availability"],
                }
                for gpu in self.volume.get_provider_gpus()["gpus"]
            ]

            return {
                "message": "GPU ID required.",
                "gpus": sorted(
                    gpu_names_with_id,
                    key=lambda x: (
                        x["availability"] != "available",
                        x["availability"] != "medium",
                        x["availability"] != "low",
                        x["gpu_name"],
                    ),
                ),
            }
        
        return {
            "gpu": self.volume.get_gpu_metadata(gpu_id),
            "datacenter_ids": [
                gpu["datacenter_id"]
                for gpu in self.get_gpu_availbable_datacenter_ids(gpu_id)
            ],
        }
    
    def create_pod(
        self,
        name,
        gpu_id=None,
        image_name="runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04",
        gpu_count=1,
        container_disk_gb=20,
        volume_gb=20,
        volume_mount_path="/workspace",
        ports=None,
        network_volume_id=None,
        env=None,
        support_public_ip=True,
        cloud_type="SECURE",
        compute_type="GPU",
        interruptible=False,
        vcpu_count=None,
    ):
        pods_url = "https://rest.runpod.io/v1/pods"

        # User/AI didn't specify a GPU
        if gpu_id is None:
            return self.get_gpu_info()

        gpu_info = self.get_gpu_info(gpu_id)

        gpu = gpu_info["gpu"]

        payload = {
            "name": name,
            "imageName": image_name,

            "cloudType": cloud_type,
            "computeType": compute_type,

            "gpuCount": gpu_count,

            "gpuTypeIds": [
                gpu["gpu_id"].split(">")[1]
            ],
            "gpuTypePriority": "availability",

            "dataCenterIds": gpu_info["datacenter_ids"],
            "dataCenterPriority": "availability",

            "containerDiskInGb": container_disk_gb,

            "volumeInGb": volume_gb,
            "volumeMountPath": volume_mount_path,

            "ports": ports or [
                "8888/http",
                "22/tcp"
            ],

            "vcpuCount": (
                vcpu_count
                if vcpu_count is not None
                else gpu["cpu"]
            ),

            "minRAMPerGPU": gpu["ram_gb"],

            "supportPublicIp": support_public_ip,
            "interruptible": interruptible,
        }

        if env:
            payload["env"] = env

        if network_volume_id:
            payload["networkVolumeId"] = network_volume_id

        print(payload)   # Debug

        response = requests.post(
            pods_url,
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
        
    
class CompoundRunpod:
    def __init__(self):
        self.volume = RunpodVolume()
        self.pods = RunpodPods()
        
        
# rv = CompoundRunpod()
# print(rv.pods.get_user_pods())