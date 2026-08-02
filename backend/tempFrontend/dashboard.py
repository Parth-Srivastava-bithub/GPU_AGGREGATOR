import streamlit as st
import pandas as pd
import requests

API = "http://127.0.0.1:8000"

st.set_page_config(
    page_title="GPU Aggregator",
    page_icon="🚀",
    layout="wide"
)

st.title("🚀 GPU Aggregator Dashboard")

page = st.sidebar.selectbox(
    "Navigation",
    [
        "GPU Catalog",
        "Datacenters"
    ]
)

# ---------------- GPU CATALOG ---------------- #

if page == "GPU Catalog":

    provider = st.selectbox(
        "Provider",
        [
            "RunPod",
            "Novita"
        ]
    )

    if st.button("Load GPUs"):

        data = requests.get(
            f"{API}/gpus/{provider}"
        ).json()

        st.metric("Total GPUs", data["count"])

        df = pd.DataFrame(data["gpus"])

        st.dataframe(
            df,
            use_container_width=True,
            hide_index=True
        )

# ---------------- DATACENTERS ---------------- #

elif page == "Datacenters":

    data = requests.get(
        f"{API}/runpod/datacenters"
    ).json()

    st.metric(
        "RunPod Datacenters",
        data["count"]
    )

    dc = st.selectbox(
        "Datacenter",
        data["datacenters"]
    )

    if st.button("Load Datacenter"):

        doc = requests.get(
            f"{API}/runpod/datacenter/{dc}"
        ).json()

        col1, col2 = st.columns(2)

        with col1:
            st.write("### Information")
            st.write(f"**ID:** {doc['datacenter_id']}")
            st.write(f"**Name:** {doc['name']}")
            st.write(f"**Location:** {doc['location']}")

        with col2:
            st.write("### GPU Availability")

            gpu_df = pd.DataFrame(
                doc.get("gpuAvailability", [])
            )

            st.dataframe(
                gpu_df,
                use_container_width=True,
                hide_index=True
            )