from apscheduler.schedulers.blocking import BlockingScheduler
from database.db import get_connection
import sqlite3

from scrapers.runpod_playwright import (
    runpod_scrape_runpod,
    runpod_get_gpus,
    runpod_merge
)

from scrapers.novita import NovitaProvider
novita = NovitaProvider()

def upsert_many(merged):

    conn = get_connection()
    cursor = conn.cursor()

    query = """
    INSERT INTO gpu_catalog (

        provider,
        gpu_id,
        gpu_name,
        manufacturer,

        vram_gb,
        ram_gb,
        cpu,
        gpu_count,

        hourly_price,
        community_price,
        secure_price,
        spot_price,

        availability,
        deployable,
        reliability,

        updated_at

    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))

    ON CONFLICT(gpu_id)
    DO UPDATE SET

        provider=excluded.provider,
        gpu_name=excluded.gpu_name,
        manufacturer=excluded.manufacturer,

        vram_gb=excluded.vram_gb,
        ram_gb=excluded.ram_gb,
        cpu=excluded.cpu,
        gpu_count=excluded.gpu_count,

        hourly_price=excluded.hourly_price,
        community_price=excluded.community_price,
        secure_price=excluded.secure_price,
        spot_price=excluded.spot_price,

        availability=excluded.availability,
        deployable=excluded.deployable,
        reliability=excluded.reliability,

        updated_at=datetime('now');
    """

    values = []

    for gpu in merged:

        values.append((
            gpu["provider"],
            gpu["gpu_id"],
            gpu["gpu_name"],
            gpu["manufacturer"],

            gpu["vram_gb"],
            gpu["ram_gb"],
            gpu["cpu"],
            gpu["gpu_count"],

            gpu["hourly_price"],
            gpu["community_price"],
            gpu["secure_price"],
            gpu["spot_price"],

            gpu["availability"],
            int(gpu["deployable"]),
            gpu["reliability"],
        ))

    cursor.executemany(query, values)

    conn.commit()
    conn.close()

    print(f"Upserted {len(values)} GPUs.")


def update_live_fields(graphql_data):

    conn = get_connection()
    cursor = conn.cursor()

    query = """
    UPDATE gpu_catalog
    SET

        hourly_price=?,
        community_price=?,
        secure_price=?,

        availability=?,
        deployable=?,

        updated_at=datetime('now')

    WHERE gpu_id=?
    """

    values = []

    for gpu in graphql_data:

        values.append((
            gpu["hourly_price"],
            gpu["community_price"],
            gpu["secure_price"],

            gpu["availability"],
            int(gpu["deployable"]),

            gpu["gpu_id"],
        ))

    cursor.executemany(query, values)

    conn.commit()
    conn.close()

    print(f"Updated {len(values)} GPUs.")


def full_sync():
    print("Running full sync...")

    # ---------- RunPod ----------
    print("RunPod Scraping...")
    playwright_data = runpod_scrape_runpod()

    print("RunPod GraphQL...")
    graphql_data = runpod_get_gpus()

    print("RunPod Merge...")
    merged = runpod_merge(playwright_data, graphql_data)

    print("RunPod Upsert...")
    upsert_many(merged)

    # ---------- Novita ----------
    print("Novita Fetch...")

    novita_data = novita.get_gpus()

    print("Novita Upsert...")

    upsert_many(novita_data)

def live_sync():

    print("RunPod Live Update")
    update_live_fields(runpod_get_gpus())

    print("Novita Live Update")
    update_live_fields(novita.get_gpus())


scheduler = BlockingScheduler()

scheduler.add_job(
    full_sync,
    "interval",
    minutes=1,
    id="full_sync",
    max_instances=1,
    coalesce=True,
)

scheduler.add_job(
    live_sync,
    "interval",
    seconds=20,
    id="live_sync",
    max_instances=1,
    coalesce=True,
)

if __name__ == "__main__":
    print("Initial sync...")
    full_sync()
    print("Scheduler started...")
    scheduler.start()


    