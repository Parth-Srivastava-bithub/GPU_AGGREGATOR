from fastapi.middleware.cors import CORSMiddleware
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