from playwright.sync_api import sync_playwright
from rapidfuzz import fuzz
import csv
import re
import dotenv
import os


dotenv.load_dotenv()

import requests

QUERY = """
query {
  gpuTypes {
    id
    displayName
    manufacturer
    memoryInGb

    communityPrice
    securePrice

    maxGpuCount

    lowestPrice(
      input: {
        gpuCount: 1
        secureCloud: false
      }
    ) {
      stockStatus
      uninterruptablePrice
    }
  }
}
"""
chrome_url = "http://127.0.0.1:9222"

def runpod_scrape_runpod():
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(chrome_url)
        context = browser.contexts[0]

        page = None
        for pg in context.pages:
            if "console.runpod.io/deploy" in pg.url:
                page = pg
                break

        if page is None:
            raise Exception("Deploy page not found. Open https://console.runpod.io/deploy")

        page.wait_for_timeout(3000)

        body = page.locator("body").inner_text()

        gpu_names = [
            "H100 SXM","RTX PRO 6000","H200 SXM","B200",
            "RTX 4000 Ada","RTX 4090","RTX PRO 4000",
            "RTX 5090","RTX PRO 4500","L40S",
            "H100 PCIe","H100 NVL","RTX PRO 6000 WK",
            "H200 NVL","B300","RTX 2000 Ada",
            "RTX A4000","RTX A4500","RTX 3090",
            "L4","RTX A5000","A40","L40",
            "RTX 6000 Ada","RTX A6000",
            "A100 PCIe","A100 SXM","MI300X"
        ]

        rows = []

        for gpu in gpu_names:

            idx = body.find(gpu)
            if idx == -1:
                continue

            chunk = body[idx:idx+400]

            price = re.search(r"\$([\d.]+)/hr", chunk)
            vram = re.search(r"(\d+)\s*GB VRAM", chunk)
            max_count = re.search(r"(\d+)\s*max", chunk)
            ram = re.search(r"(\d+)\s*GB RAM", chunk)
            vcpu = re.search(r"(\d+)\s*vCPU", chunk)
            availability = re.search(
                r"\b(High|Medium|Low|Unavailable)\b",
                chunk,
                re.IGNORECASE
            )
            rows.append({
                "gpu_name": gpu,
                "hourly_price": float(price.group(1)) if price else None,
                "vram_gb": int(vram.group(1)) if vram else None,
                "max": int(max_count.group(1)) if max_count else None,
                "ram_gb": int(ram.group(1)) if ram else None,
                "vcpu": int(vcpu.group(1)) if vcpu else None,
                "availability": availability.group(1).lower() if availability else None,
            })

        with open("runpod_gpu_catalog.csv", "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "gpu_name",
                    "hourly_price",
                    "vram_gb",
                    "max",
                    "ram_gb",
                    "vcpu",
                    "availability"
                ]
            )
            writer.writeheader()
            writer.writerows(rows)

        print(f"Saved {len(rows)} GPUs to runpod_gpu_catalog.csv")
        return rows

def normalize_gpu_name(name: str) -> str:
    name = name.upper()

    replacements = [
        "NVIDIA",
        "TESLA",
        "GENERATION",
        "BLACKWELL",
        "SERVER EDITION",
        "WORKSTATION EDITION",
        "MAX-Q",
        "MAXQ",
    ]

    for r in replacements:
        name = name.replace(r, "")

    name = " ".join(name.split())
    return name.strip()

def match_gpu(playwright_gpu, graphql_gpus):

    best = None
    best_score = -1

    p_name = normalize_gpu_name(playwright_gpu["gpu_name"])

    for gpu in graphql_gpus:

        g_name = normalize_gpu_name(gpu["gpu_name"])
    
        score = fuzz.ratio(p_name, g_name)

        # Bonus if VRAM matches
        if (
            playwright_gpu.get("vram_gb") is not None
            and gpu.get("vram_gb") == playwright_gpu.get("vram_gb")
        ):
            score += 15

        # Bonus if max gpu matches
        if (
            playwright_gpu.get("max") is not None
            and gpu.get("gpu_count") == playwright_gpu.get("max")
        ):
            score += 10

        if score > best_score:
            best_score = score
            best = gpu

    return best, best_score

def runpod_merge(playwright_data, graphql_data):

    merged = []

    for pw_gpu in playwright_data:

        gpu, score = match_gpu(pw_gpu, graphql_data)

        if score < 85:
            print(f"❌ No match: {pw_gpu['gpu_name']}")
            continue

        print(f"✅ {pw_gpu['gpu_name']} -> {gpu['gpu_name']} ({score:.1f})")

        merged.append({
            **gpu,
            "ram_gb": pw_gpu["ram_gb"],
            "cpu": pw_gpu["vcpu"],
            "gpu_count": pw_gpu["max"],
            "availability": pw_gpu["availability"] or gpu["availability"],
        })

    return merged

def runpod_get_gpus():
        url = "https://api.runpod.io/graphql"

        headers = {
            "Authorization": f"Bearer {os.getenv("RUNPOD_API_KEY")}",
            "Content-Type": "application/json"
        }
        try:
            response = requests.post(
                url,
                headers=headers,
                json={"query": QUERY}
            )
            data = response.json()
            gpu_types = data["data"]["gpuTypes"]

            result = []
            for gpu in gpu_types:
                lowest = gpu.get("lowestPrice")

                result.append({
                    "provider": "RunPod",
                    "gpu_id": gpu.get("id"),
                    "gpu_name": gpu["displayName"],
                    "vram_gb": gpu["memoryInGb"],
                    "manufacturer": gpu["manufacturer"],
                    "community_price": gpu["communityPrice"],
                    "secure_price": gpu["securePrice"],
                    "hourly_price": (
                        lowest.get("uninterruptablePrice")
                        if lowest and lowest.get("uninterruptablePrice") is not None
                        else gpu.get("communityPrice")
                    ),

                    "spot_price": None,

                    "availability": (
                        (lowest.get("stockStatus") or "unavailable").lower()
                        if lowest
                        else "unavailable"
                    ),

                    "deployable": (
                        lowest is not None and
                        lowest.get("uninterruptablePrice") is not None
                    ),

                    "regions": None,

                    "gpu_count": gpu["maxGpuCount"],

                    "reliability": None,

                    "cpu": None,

                    "ram_gb": None,
                })
            def availability_rank(status):

                s = str(status).lower()

                if s == "high":
                    return 4
                elif s == "normal":
                    return 3
                elif s == "low":
                    return 2
                else:
                    return 1
                    
            result.sort(
                key=lambda x: availability_rank(x["availability"]),
                reverse=True
            )
            return result

        except Exception as e:
            return {"error": str(e)}

def main():

    playwright_data = scrape_runpod()

    # graphql_data = Runpod().get_gpus()
    graphql_data = get_gpus()     # jo bhi tera function hai

    merged = merge(playwright_data, graphql_data)
    with open(
        "runpod_merged.csv",
        "w",
        newline="",
        encoding="utf-8"
    ) as f:

        writer = csv.DictWriter(
            f,
            fieldnames=merged[0].keys()
        )

        writer.writeheader()
        writer.writerows(merged)

    print(f"Saved {len(merged)} GPUs to runpod_merged.csv")