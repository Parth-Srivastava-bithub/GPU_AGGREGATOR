from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from database.db import get_connection
from fastapi import FastAPI
from fastapi import Query
from scrapers.runpod import CompoundRunpod
from scrapers.novita import CompoundNovita
app = FastAPI(title="Connector")

providers = {
    "runpod": CompoundRunpod(),
    "novita": CompoundNovita(),
}
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/gpus/{provider}")
def get_provider_gpus(provider: str):

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT *

        FROM gpu_catalog

        WHERE LOWER(provider)=LOWER(?)

        ORDER BY hourly_price ASC
        """,
        (provider,)
    )

    columns = [col[0] for col in cursor.description]

    rows = [
        dict(zip(columns, row))
        for row in cursor.fetchall()
    ]

    conn.close()

    return {
        "provider": provider,
        "count": len(rows),
        "gpus": rows
    }
    


@app.get("/gpu")
def get_gpu(
    provider: str,
    gpu_name: str,
    vram_gb: int | None = Query(default=None),
    ram_gb: int | None = Query(default=None),
    cpu: int | None = Query(default=None),
):

    conn = get_connection()
    cursor = conn.cursor()

    query = """
    SELECT *
    FROM gpu_catalog
    WHERE LOWER(provider)=LOWER(?)
    AND LOWER(gpu_name)=LOWER(?)
    """

    values = [provider, gpu_name]

    if vram_gb is not None:
        query += " AND vram_gb=?"
        values.append(vram_gb)

    if ram_gb is not None:
        query += " AND ram_gb=?"
        values.append(ram_gb)

    if cpu is not None:
        query += " AND cpu=?"
        values.append(cpu)

    query += " LIMIT 1"

    cursor.execute(query, values)

    row = cursor.fetchone()

    if row is None:
        conn.close()
        return {"message": "GPU not found"}

    columns = [col[0] for col in cursor.description]

    result = dict(zip(columns, row))

    conn.close()

    return result

@app.get("/{provider}/datacenter/{datacenter_id}")
def get_datacenter(provider: str, datacenter_id: str):

    provider = provider.lower()

    if provider not in providers:
        return {"message": "Provider not supported"}

    return providers[provider].volume.get_datacenter(datacenter_id)

@app.get("/{provider}/datacenters")
def get_datacenters(provider: str):

    provider = provider.lower()

    if provider not in providers:
        return {"message": "Provider not supported"}

    ids = providers[provider].volume.get_datacenter_ids()

    return {
        "provider": provider,
        "count": len(ids),
        "datacenters": ids
    }
    
    
@app.get("/providers")

def get_providers():
    """

    Returns:
        {
            "providers": [
                "runpod",
                "novita"
            ]
        }
    """
    return {
        "providers": list(providers.keys())
    }
    
@app.get("/gpus")
def get_all_gpus():

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT *
        FROM gpu_catalog
        ORDER BY provider ASC, hourly_price ASC
        """
    )

    columns = [col[0] for col in cursor.description]

    rows = [
        dict(zip(columns, row))
        for row in cursor.fetchall()
    ]

    conn.close()

    return {
        "count": len(rows),
        "gpus": rows
    }
    

@app.get("/{provider}/datacenter/{datacenter_id}/gpus")
def get_provider_datacenter_gpus(provider: str, datacenter_id: str):
    provider = provider.lower()

    if provider not in providers:
        return {"message": "Provider not supported"}

    datacenter = providers[provider].volume.get_datacenter(datacenter_id)

    if isinstance(datacenter, str):
        return {"message": datacenter}

    gpu_availability = datacenter.get("gpuAvailability", [])

    return {
        "provider": provider,
        "datacenter_id": datacenter_id,
        "count": len(gpu_availability),
        "gpus": gpu_availability
    }
    

@app.get("/{provider}/gpu_availability")
def get_provider_gpu_availability(provider: str):
    provider = provider.lower()

    if provider not in providers:
        return {"message": "Provider not supported"}

    gpu_availability = providers[provider].volume.get_gpu_availability_across_datacenters()

    return {
        "provider": provider,
        "count": len(gpu_availability),
        "gpu_availability": gpu_availability
    }
    
    
class VolumeCreationSchema(BaseModel):
    datacenter_id: str
    name: str
    size: int
    
    
@app.post("/{provider}/create_volume")
def create_volume(provider: str, volume_data: VolumeCreationSchema):
    provider = provider.lower()

    if provider not in providers:
        return {"message": "Provider not supported"}

    datacenter_id = volume_data.datacenter_id
    name = volume_data.name
    size = volume_data.size

    try:
        providers[provider].volume.create_volume(datacenter_id, name, size)
        return {"message": "Volume created successfully"}
    except Exception as e:
        return {"message": f"Error creating volume: {str(e)}"}


@app.get("/{provider}/user_volumes")
def get_user_volumes(provider: str):
    """
    Runpod output format
    {
        "provider": "runpod",
        "count": 1,
        "volumes": [
            {
            "dataCenterId": "AP-IN-2",
            "id": "filpk6bjg5",
            "name": "instant_amethyst_cheetah",
            "size": 10
            }
        ]
    }
    
    Novita output format:
    {
        "provider": "novita",
        "count": 2,
        "volumes": {
            "data": [
            {
                "storageId": "3b7dd5a3-32f1-4854-8e24-d105577dd1bc",
                "storageName": "random",
                "storageSize": 10,
                "clusterId": "us-dallas-nas-2",
                "clusterName": "US-Dallas-NAS-02 (Dallas)",
                "price": "200",
                "creator": "",
                "createdAt": "1785775326",
                "uuid": "a45681a6-88c0-46b4-86f0-6f1d286841e2"
            }
            ],
            "total": 1
        }
    }
    """
    
    
    provider = provider.lower()

    if provider not in providers:
        return {"message": "Provider not supported"}

    try:
        if provider == "novita":
            raw = providers[provider].volume.get_user_volume()

            volumes = [
                {
                    "dataCenterId": volume["clusterId"],
                    "id": volume["storageId"],
                    "name": volume["storageName"],
                    "size": volume["storageSize"],
                }
                for volume in raw["data"]
            ]

        elif provider == "runpod":
            volumes = providers[provider].volume.get_user_volume()
        else:
            return {"message": "Provider not supported"}

        return {
            "provider": provider,
            "count": len(volumes),
            "volumes": volumes
        }
    except Exception as e:
        return {"message": f"Error fetching user volumes: {str(e)}"}


@app.delete("/{provider}/delete_volume/{volume_id}")
def delete_volume(provider: str, volume_id: str):
    provider = provider.lower()

    if provider not in providers:
        return {"message": "Provider not supported"}

    try:
        result = providers[provider].volume.delete_volume(volume_id)
        return result
    except Exception as e:
        return {"message": f"Error deleting volume: {str(e)}"}
    

@app.get("/{provider}/user_pods")
def get_user_pods(provider: str):
    provider = provider.lower()

    if provider not in providers:
        return {"message": "Provider not supported"}

    try:
        if provider == "novita":
            raw = providers[provider].pods.get_user_pods()

            pods = [
                {
                    "id": pod["id"],
                    "name": pod["name"],
                    "status": pod["status"]["status"],
                    "region": pod["region"],
                    "gpuCount": pod["resource_specs"]["gpu_num"],
                    "cpuCount": pod["resource_specs"]["cpu_num"],
                    "memoryGB": int(pod["resource_specs"]["memory_gb"]),
                    "diskGB": pod["resource_specs"]["rootfs_size_gb"],
                    "image": pod["image"],
                    "publicIp": pod["network"]["ip"] or None,
                    "ports": pod["ports"],
                    "createdAt": pod["created_at"],
                    "lastStartedAt": pod["last_started_at"],
                }
                for pod in raw["data"]
            ]

        elif provider == "runpod":
            raw = providers[provider].pods.get_user_pods()

            pods = [
                {
                    "id": pod["id"],
                    "name": pod["name"],
                    "status": pod["desiredStatus"].lower(),
                    "region": None,
                    "gpuCount": pod["gpuCount"],
                    "cpuCount": pod["vcpuCount"],
                    "memoryGB": pod["memoryInGb"],
                    "diskGB": pod["containerDiskInGb"],
                    "image": pod["imageName"],
                    "publicIp": pod["publicIp"],
                    "ports": pod["ports"],
                    "createdAt": pod["createdAt"],
                    "lastStartedAt": pod["lastStartedAt"],
                }
                for pod in raw
            ]

        return {
            "provider": provider,
            "count": len(pods),
            "pods": pods,
        }

    except Exception as e:
        return {"message": f"Error fetching user pods: {str(e)}"}
    
@app.get("/{provider}/user_pod/{pod_id}")
def get_user_pod(provider: str, pod_id: str):
    provider = provider.lower()

    if provider not in providers:
        return {"message": "Provider not supported"}

    try:
        pod = providers[provider].pods.get_pod(pod_id)

        if "message" in pod:
            return pod

        return {
            "provider": provider,
            "pod": pod
        }

    except Exception as e:
        return {"message": f"Error fetching user pod: {str(e)}"}
    
    
@app.post("/{provider}/create_pod")
def create_pod(
    provider: str,
    name: str,
    gpu_id: str,
    image_name: str = "runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04",
    gpu_count: int = 1,
    container_disk_gb: int = 20,
    volume_gb: int = 20,
    volume_mount_path: str = "/workspace",
    network_volume_id: str = None,
    vcpu_count: int = None,
):
    provider = provider.lower()

    if provider not in providers:
        return {"message": "Provider not supported"}

    try:
        pod = providers[provider].pods.create_pod(
            name=name,
            gpu_id=gpu_id,
            image_name=image_name,
            gpu_count=gpu_count,
            container_disk_gb=container_disk_gb,
            volume_gb=volume_gb,
            volume_mount_path=volume_mount_path,
            network_volume_id=network_volume_id,
            vcpu_count=vcpu_count,
        )

        return {
            "provider": provider,
            "pod": pod
        }

    except Exception as e:
        return {
            "message": f"Error creating pod: {str(e)}"
        }