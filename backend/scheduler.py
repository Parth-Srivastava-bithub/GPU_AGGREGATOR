from apscheduler.schedulers.blocking import BlockingScheduler

from database.db import create_database

from scrapers.runpod import CompoundRunpod
from scrapers.novita import CompoundNovita

from scheduler_helper import upsert_many, update_live_fields

from scrapers.runpod_playwright import (
    runpod_scrape_runpod,
    runpod_get_gpus,
    runpod_merge
)

scheduler = BlockingScheduler()

compound_runpod = CompoundRunpod()
compound_novita = CompoundNovita()


# =========================================================
# GPU Catalog
# =========================================================

def update_runpod_catalog():

    print("\n========== RunPod Catalog ==========")

    playwright = runpod_scrape_runpod()

    graphql = runpod_get_gpus()

    merged = runpod_merge(playwright, graphql)

    upsert_many(merged)


def update_novita_catalog():

    print("\n========== Novita Catalog ==========")

    upsert_many(
        compound_novita.provider.get_gpus()
    )


# =========================================================
# Datacenters
# =========================================================

def sync_runpod_datacenters():

    print("\n========== RunPod Datacenters ==========")

    compound_runpod.volume.sync_runpod_datacenters()


def sync_novita_datacenters():

    print("\n========== Novita Datacenters ==========")

    compound_novita.volume.sync_novita_datacenters()


# =========================================================
# Live Updates
# =========================================================

def runpod_live_sync():

    print("\nRunPod Live Update")

    update_live_fields(
        runpod_get_gpus()
    )


def novita_live_sync():

    print("\nNovita Live Update")

    update_live_fields(
        compound_novita.provider.get_gpus()
    )


# =========================================================
# Initial Sync
# =========================================================

def initial_sync():

    print("\n=========== INITIAL SYNC ===========")

    update_runpod_catalog()
    update_novita_catalog()

    sync_runpod_datacenters()
    sync_novita_datacenters()

    print("\nInitial Sync Complete")


# =========================================================
# Scheduler
# =========================================================

scheduler.add_job(
    update_runpod_catalog,
    "interval",
    hours=1,
    id="runpod_catalog",
    max_instances=1,
    coalesce=True,
)

scheduler.add_job(
    update_novita_catalog,
    "interval",
    hours=1,
    id="novita_catalog",
    max_instances=1,
    coalesce=True,
)

scheduler.add_job(
    sync_runpod_datacenters,
    "interval",
    hours=4,
    id="runpod_datacenters",
    max_instances=1,
    coalesce=True,
)

scheduler.add_job(
    sync_novita_datacenters,
    "interval",
    hours=4,
    id="novita_datacenters",
    max_instances=1,
    coalesce=True,
)

scheduler.add_job(
    runpod_live_sync,
    "interval",
    seconds=20,
    id="runpod_live",
    max_instances=1,
    coalesce=True,
)

scheduler.add_job(
    novita_live_sync,
    "interval",
    seconds=20,
    id="novita_live",
    max_instances=1,
    coalesce=True,
)


# =========================================================

# if __name__ == "__main__":

#     print("Initializing database...")
#     create_database()

#     print("Running initial sync...")
#     initial_sync()

#     print("Scheduler started...")
#     scheduler.start()