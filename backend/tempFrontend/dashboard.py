import streamlit as st
import pandas as pd
import requests

API = "http://127.0.0.1:8000"
PROVIDERS = ["RunPod", "Novita"]

st.set_page_config(
    page_title="GPU Aggregator",
    page_icon="🚀",
    layout="wide"
)

st.title("🚀 GPU Aggregator Dashboard")


def fetch_json(url: str):
    try:
        response = requests.get(url, timeout=20)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        st.error(f"API error: {e}")
        return None


page = st.sidebar.selectbox(
    "Navigation",
    ["GPU Catalog", "Datacenters"],
    key="nav_page"
)

# ---------------- GPU CATALOG ---------------- #
if page == "GPU Catalog":

    provider = st.selectbox(
        "Provider",
        PROVIDERS,
        key="gpu_provider"
    )

    if st.button("Load GPUs", key="load_gpus"):
        data = fetch_json(f"{API}/gpus/{provider.lower()}")

        if data and "gpus" in data:
            st.metric("Total GPUs", data["count"])

            df = pd.DataFrame(data["gpus"])
            if df.empty:
                st.info("No GPUs found for this provider.")
            else:
                st.dataframe(
                    df,
                    use_container_width=True,
                    hide_index=True
                )

# ---------------- DATACENTERS ---------------- #
elif page == "Datacenters":

    provider = st.selectbox(
        "Provider",
        PROVIDERS,
        key="dc_provider"
    )

    data = fetch_json(f"{API}/{provider.lower()}/datacenters")

    if not data:
        st.stop()

    st.metric(f"{provider} Datacenters", data.get("count", 0))

    datacenters = data.get("datacenters", [])

    if not datacenters:
        st.warning(f"No datacenters found for {provider}.")
        st.stop()

    dc = st.selectbox(
        "Datacenter",
        datacenters,
        key=f"dc_select_{provider.lower()}"
    )

    if st.button("Load Datacenter", key="load_datacenter"):
        doc = fetch_json(f"{API}/{provider.lower()}/datacenter/{dc}")

        if not doc:
            st.stop()

        col1, col2 = st.columns(2)

        with col1:
            st.subheader("Information")
            st.write(f"**Provider:** {doc.get('provider', 'N/A')}")
            st.write(f"**ID:** {doc.get('datacenter_id', 'N/A')}")
            st.write(f"**Name:** {doc.get('name', 'N/A')}")
            st.write(f"**Location:** {doc.get('location', 'N/A')}")

        with col2:
            st.subheader("GPU Availability")

            gpu_df = pd.DataFrame(doc.get("gpuAvailability", []))

            if gpu_df.empty:
                st.info("No GPU availability data found.")
            else:
                st.dataframe(
                    gpu_df,
                    use_container_width=True,
                    hide_index=True
                )