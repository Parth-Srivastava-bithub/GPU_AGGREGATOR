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

class RunpodProvider:
    def __init__(self):
        self.api_key = os.getenv("RUNPOD_API_KEY")
        self.url = "https://api.runpod.io/graphql"
        self.base_url = "https://rest.runpod.io/v1/pods"
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        self.simplify_header = {
            "Authorization": f"Bearer {self.api_key}",
        }
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
        query = """
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

        try:
            response = requests.post(
                self.url,
                headers=self.headers,
                json={"query": query}
            )
            data = response.json()
            print(data)
            gpu_types = data["data"]["gpuTypes"]

            result = []
            
            for gpu in gpu_types:
                lowest = gpu.get("lowestPrice")

                result.append({
                    "provider": "RunPod",
                    "source_id": gpu.get("id"),
                    "gpu_name": gpu["displayName"],
                    "vram_gb": gpu["memoryInGb"],

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

                    "gpu_count": None,

                    "reliability": None,

                    "cpu": None,

                    "ram_gb": None
                })
                
            result.sort(
                key=lambda x: self.availability_rank(x["availability"]),
                reverse=True
            )
            return result

        except Exception as e:
            return {"error": str(e)}
    def test_lowest_price_fields(self):
        query = """
        query {
        gpuTypes {
            id
            displayName

            lowestPrice(
            input: {
                gpuCount: 1
                secureCloud: false
            }
            ) {
            stockStatus
            uninterruptablePrice

            minVcpu
            minMemory

            availableGpuCounts
            maxUnreservedGpuCount
            }
        }
        }
        """

        try:
            response = requests.post(
                self.url,
                headers=self.headers,
                json={"query": query}
            )

            print(f"Status Code: {response.status_code}")
            print(json.dumps(response.json(), indent=4))

        except Exception as e:
            print(e)

    
    def discover_myself_fields(self):
        fields = [
            "balance",
            "credits",
            "creditBalance",
            "wallet",
            "usage",
            "spent",
            "remaining",
            "remainingCredits",
            "amount",
            "currency",
            "invoices",
            "transactions",
            "paymentMethod",
            "currentBalance",
            "availableBalance",
            "billingCycle",
            "totalSpent",
            "currentSpend",
            "availableCredit",
            "creditRemaining",
        ]

        with open("filter.txt", "w", encoding="utf-8") as f:
            for field in fields:

                query = f"""
                    query {{
                        myself {{
                            billing(input: {{}}) {{
                                {field}
                            }}
                        }}
                    }}
                    """

                try:
                    response = requests.post(
                        self.url,
                        headers=self.headers,
                        json={"query": query}
                    )

                    result = response.json()

                    f.write("=" * 80 + "\n")
                    f.write(f"FIELD: {field}\n")
                    f.write(json.dumps(result, indent=4))
                    f.write("\n\n")

                    print(f"Tested: {field}")

                except Exception as e:
                    f.write(f"{field} -> {e}\n")
                    

    def test_user_billing_summary(self):
        query = """
        query getUserBillingSummary($input: UserBillingInput!) {
        myself {
            billing(input: $input) {
            summary {
                time
                gpuCloudAmount
                cpuCloudAmount
                runpodEndpointAmount
                serverlessAmount
                storageAmount
                __typename
            }
            __typename
            }
            __typename
        }
        }
        """

        variables = {
            "input": {
                "granularity": "DAILY"
            }
        }

        try:
            response = requests.post(
                self.url,
                headers=self.headers,
                json={
                    "operationName": "getUserBillingSummary",
                    "query": query,
                    "variables": variables
                }
            )

            data = response.json()

            print(f"Status Code: {response.status_code}")
            print(json.dumps(data, indent=4))

            with open("billing_summary.txt", "w", encoding="utf-8") as f:
                f.write(json.dumps(data, indent=4))

        except Exception as e:
            print(e)

    def test_cluster_billing(self):
        query = """
        query getClusterBilling($input: UserBillingInput!) {
        myself {
            billing(input: $input) {
            cluster {
                __typename
            }
            __typename
            }
            __typename
        }
        }
        """

        variables = {
            "input": {
                "granularity": "DAILY"
            }
        }

        try:
            response = requests.post(
                self.url,
                headers=self.headers,
                json={
                    "operationName": "getClusterBilling",
                    "query": query,
                    "variables": variables
                }
            )

            data = response.json()

            print(f"Status Code: {response.status_code}")
            print(json.dumps(data, indent=4))

            with open("cluster_billing.txt", "w", encoding="utf-8") as f:
                f.write(json.dumps(data, indent=4))

        except Exception as e:
            print(e)


    def test_pod_billing_history(self):
        end_time = datetime.utcnow()
        start_time = end_time - timedelta(days=90)

        url = f"{self.base_url}/billing/pods"

        params = {
            "bucketSize": "day",
            "startTime": start_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "endTime": end_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "grouping": "gpuTypeId"
        }

        try:
            response = requests.get(
                "https://rest.runpod.io/v1/billing/pods",
                headers=self.simplify_header,
                params=params
            )

            print(f"Status Code: {response.status_code}")

            data = response.json()

            print(json.dumps(data, indent=4))

            with open("pod_billing_history.txt", "w", encoding="utf-8") as f:
                f.write(json.dumps(data, indent=4))

        except Exception as e:
            print(e)

    def test_endpoint_billing_history(self):
        end_time = datetime.utcnow()
        start_time = end_time - timedelta(days=90)

        url = "https://rest.runpod.io/v1/billing/endpoints"

        params = [
            ("bucketSize", "day"),
            ("grouping", "endpointId"),
            ("startTime", start_time.strftime("%Y-%m-%dT%H:%M:%SZ")),
            ("endTime", end_time.strftime("%Y-%m-%dT%H:%M:%SZ")),
        ]

        data_centers = [
            "EU-RO-1",
            "CA-MTL-1",
            "EU-SE-1",
            "US-IL-1",
            "EUR-IS-1",
            "EU-CZ-1",
            "US-TX-3",
            "EUR-IS-2",
            "US-KS-2",
            "US-GA-2",
            "US-WA-1",
            "US-TX-1",
            "CA-MTL-3",
            "EU-NL-1",
            "US-TX-4",
            "US-CA-2",
            "US-NC-1",
            "OC-AU-1",
            "US-DE-1",
            "EUR-IS-3",
            "CA-MTL-2",
            "AP-JP-1",
            "EUR-NO-1",
            "EU-FR-1",
            "US-KS-3",
            "US-GA-1",
        ]

        for dc in data_centers:
            params.append(("dataCenterId", dc))

        try:
            response = requests.get(
                url,
                headers=self.simplify_header,
                params=params,
            )

            print(f"Status Code: {response.status_code}")

            data = response.json()

            print(json.dumps(data, indent=4))

            with open("endpoint_billing_history.txt", "w", encoding="utf-8") as f:
                f.write(json.dumps(data, indent=4))

            if isinstance(data, list):
                total = sum(item.get("amount", 0) for item in data)
                print(f"\nTotal Endpoint Spend: ${total:.6f}")

        except Exception as e:
            print(e)
    def test_network_volume_billing_history(self):
        end_time = datetime.utcnow()
        start_time = end_time - timedelta(days=90)

        url = "https://rest.runpod.io/v1/billing/networkvolumes"

        params = {
            "bucketSize": "day",
            "startTime": start_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "endTime": end_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }

        try:
            response = requests.get(
                url,
                headers=self.simplify_header,
                params=params,
            )

            print(f"Status Code: {response.status_code}")

            data = response.json()

            print(json.dumps(data, indent=4))

            with open("network_volume_billing_history.txt", "w", encoding="utf-8") as f:
                f.write(json.dumps(data, indent=4))

            if isinstance(data, list):
                total = sum(item.get("amount", 0) for item in data)
                print(f"\nTotal Network Volume Spend: ${total:.6f}")

        except Exception as e:
            print(e)  
