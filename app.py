import streamlit as st
import pandas as pd
import numpy as np
import requests
import json
import os
import re
import time

from urllib.parse import quote
from datetime import datetime
from math import radians, sin, cos, sqrt, atan2

from ortools.constraint_solver import pywrapcp, routing_enums_pb2


# =========================================================
# APP CONFIG
# =========================================================
st.set_page_config(
    page_title="Lawn Care CRM Dispatch",
    page_icon="🌿",
    layout="wide"
)

st.title("🌿 Lawn Care CRM Dispatch System")


# =========================================================
# FILES
# =========================================================
SAVE_FILE = "dispatch_session.json"
CACHE_FILE = "geo_cache.json"


# =========================================================
# SESSION STATE
# =========================================================
if "dispatch" not in st.session_state:
    st.session_state.dispatch = None

if "completed" not in st.session_state:
    st.session_state.completed = set()

if "arrived" not in st.session_state:
    st.session_state.arrived = {}

if "completed_time" not in st.session_state:
    st.session_state.completed_time = {}


# =========================================================
# LOAD CACHE
# =========================================================
if os.path.exists(CACHE_FILE):
    try:
        GEO_CACHE = json.load(open(CACHE_FILE))
    except:
        GEO_CACHE = {}
else:
    GEO_CACHE = {}


def save_cache():
    with open(CACHE_FILE, "w") as f:
        json.dump(GEO_CACHE, f)


# =========================================================
# GOOGLE API KEY (STREAMLIT SECRETS)
# =========================================================
GOOGLE_API_KEY = st.secrets.get("GOOGLE_API_KEY", "")


# =========================================================
# CLEAN ADDRESS
# =========================================================
def clean(addr):
    if pd.isna(addr):
        return ""
    addr = str(addr)
    addr = re.sub(r"\s+", " ", addr)
    return addr.strip()


# =========================================================
# GOOGLE GEOCODE
# =========================================================
def google_geocode(address):
    if not GOOGLE_API_KEY:
        return None

    try:
        url = (
            "https://maps.googleapis.com/maps/api/geocode/json"
            f"?address={quote(address)}&key={GOOGLE_API_KEY}"
        )

        r = requests.get(url, timeout=10).json()

        if r.get("status") == "OK":
            loc = r["results"][0]["geometry"]["location"]
            return {"lat": loc["lat"], "lon": loc["lng"]}

    except:
        pass

    return None


# =========================================================
# OSM FALLBACK
# =========================================================
def osm_geocode(address):
    try:
        url = (
            "https://nominatim.openstreetmap.org/search"
            f"?q={quote(address)}&format=json&limit=1&countrycodes=us"
        )

        r = requests.get(
            url,
            headers={"User-Agent": "crm-dispatch"},
            timeout=10
        ).json()

        if r:
            return {
                "lat": float(r[0]["lat"]),
                "lon": float(r[0]["lon"])
            }

    except:
        pass

    return None


# =========================================================
# GEOCODER (PRODUCTION)
# =========================================================
def geocode(address):

    address = clean(address)

    if address in GEO_CACHE:
        return GEO_CACHE[address]

    for attempt in [
        address,
        address + ", USA",
        address + ", Mississippi"
    ]:

        g = google_geocode(attempt)
        if g:
            GEO_CACHE[address] = g
            save_cache()
            return g

        g = osm_geocode(attempt)
        if g:
            GEO_CACHE[address] = g
            save_cache()
            return g

        time.sleep(0.2)

    return None


# =========================================================
# DISTANCE (FALLBACK)
# =========================================================
def haversine(a, b):
    R = 6371

    lat1 = radians(a["lat"])
    lon1 = radians(a["lon"])
    lat2 = radians(b["lat"])
    lon2 = radians(b["lon"])

    dlat = lat2 - lat1
    dlon = lon2 - lon1

    x = (
        sin(dlat / 2) ** 2
        + cos(lat1) * cos(lat2)
        * sin(dlon / 2) ** 2
    )

    return 2 * R * atan2(sqrt(x), sqrt(1 - x))


# =========================================================
# GOOGLE MAPS NAV
# =========================================================
def nav(addr):
    return "https://www.google.com/maps/search/?api=1&query=" + quote(addr)


# =========================================================
# CHUNKED ROUTE LINKS
# =========================================================
def route_links(addresses):

    if len(addresses) < 2:
        return []

    max_stops = 10
    links = []

    for i in range(0, len(addresses), max_stops):

        chunk = addresses[i:i + max_stops]

        if len(chunk) < 2:
            continue

        origin = quote(chunk[0])
        dest = quote(chunk[-1])

        waypoints = "|".join(quote(x) for x in chunk[1:-1])

        url = (
            "https://www.google.com/maps/dir/?api=1"
            f"&origin={origin}"
            f"&destination={dest}"
            f"&travelmode=driving"
        )

        if waypoints:
            url += f"&waypoints={waypoints}"

        links.append(url)

    return links


# =========================================================
# FILE UPLOAD
# =========================================================
uploaded = st.file_uploader("Upload Customer Excel", type=["xlsx"])

df = None

if uploaded:
    df = pd.read_excel(uploaded)
    st.success(f"Loaded {len(df)} customers")
    st.dataframe(df)


# =========================================================
# MAIN UI
# =========================================================
if df is not None:

    address_col = st.selectbox("Address Column", df.columns)

    depot = st.text_input("Depot Address (start only, not a stop)")

    df["Include"] = True

    edited = st.data_editor(df, use_container_width=True)

    selected = edited[edited["Include"] == True]

    st.info(f"Selected customers: {len(selected)}")

    # =====================================================
    # GENERATE DISPATCH
    # =====================================================
    if st.button("🚀 Generate Dispatch"):

        locations = []
        failed = []

        depot_loc = None

        # DEPOT
        if depot:
            g = geocode(depot)
            if g:
                depot_loc = {"address": depot, **g}

        # CUSTOMERS
        progress = st.progress(0)
        total = len(selected)

        for i, (_, row) in enumerate(selected.iterrows(), start=1):

            addr = clean(row[address_col])
            geo = geocode(addr)

            if geo:
                locations.append({"address": addr, **geo})
            else:
                failed.append(addr)

            progress.progress(min(int(i / max(total, 1) * 100), 100))
            time.sleep(0.1)

        st.success(f"Geocoded: {len(locations)}")
        if failed:
            st.warning(f"Failed: {len(failed)}")
            st.dataframe(pd.DataFrame(failed, columns=["Failed"]))

        if len(locations) < 2:
            st.error("Not enough valid locations")
            st.stop()

        # =================================================
        # ROUTE MATRIX
        # =================================================
        n = len(locations)
        matrix = np.zeros((n, n))

        for i in range(n):
            for j in range(n):
                if i == j:
                    continue
                try:
                    url = (
                        "https://router.project-osrm.org/route/v1/driving/"
                        f"{locations[i]['lon']},{locations[i]['lat']};"
                        f"{locations[j]['lon']},{locations[j]['lat']}?overview=false"
                    )

                    r = requests.get(url, timeout=5).json()
                    matrix[i][j] = int(r["routes"][0]["duration"] / 60)

                except:
                    matrix[i][j] = int(haversine(locations[i], locations[j]) * 2)

        # =================================================
        # OPTIMIZE
        # =================================================
        manager = pywrapcp.RoutingIndexManager(n, 1, 0)
        routing = pywrapcp.RoutingModel(manager)

        def cb(i, j):
            return int(matrix[manager.IndexToNode(i)][manager.IndexToNode(j)])

        transit = routing.RegisterTransitCallback(cb)
        routing.SetArcCostEvaluatorOfAllVehicles(transit)

        params = pywrapcp.DefaultRoutingSearchParameters()
        params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
        params.time_limit.FromSeconds(20)

        solution = routing.SolveWithParameters(params)

        if not solution:
            st.error("Routing failed")
            st.stop()

        index = routing.Start(0)
        route = []

        while not routing.IsEnd(index):
            route.append(manager.IndexToNode(index))
            index = solution.Value(routing.NextVar(index))

        route.append(manager.IndexToNode(index))

        ordered = [locations[i] for i in route]

        if depot_loc:
            ordered = ordered[1:]  # remove depot from stops

        # SAVE SESSION
        st.session_state.dispatch = ordered
        st.session_state.completed = set()
        st.session_state.arrived = {}
        st.session_state.completed_time = {}

        json.dump(ordered, open(SAVE_FILE, "w"))

        st.success("Dispatch created")


# =========================================================
# DISPATCH BOARD
# =========================================================
if st.session_state.dispatch:

    ordered = st.session_state.dispatch

    st.subheader("🚚 Dispatch Board")

    # GOOGLE MAPS ROUTE
    addresses = [x["address"] for x in ordered]
    links = route_links(addresses)

    if links:
        st.subheader("🗺️ Google Maps Route")
        for i, l in enumerate(links):
            st.markdown(f"[Route Segment {i+1}]({l})")

    # TABLE
    table = []
    for i, stop in enumerate(ordered):
        table.append({
            "Stop": i + 1,
            "Address": stop["address"],
            "Navigate": nav(stop["address"]),
            "Completed": i in st.session_state.completed
        })

    st.dataframe(pd.DataFrame(table), use_container_width=True)

    st.download_button(
        "Download Dispatch CSV",
        pd.DataFrame(table).to_csv(index=False),
        "dispatch.csv",
        "text/csv"
    )

    # STOPS
    st.subheader("Active Stops")

    for i, stop in enumerate(ordered):

        st.markdown(f"### Stop {i+1}")
        st.write(stop["address"])

        c1, c2, c3 = st.columns(3)

        with c1:
            if i not in st.session_state.arrived:
                if st.button(f"Arrived {i+1}", key=f"a{i}"):
                    st.session_state.arrived[i] = datetime.now()

        with c2:
            if i not in st.session_state.completed:
                if st.button(f"Complete {i+1}", key=f"c{i}"):
                    st.session_state.completed.add(i)
                    st.session_state.completed_time[i] = datetime.now()

        with c3:
            st.markdown(f"[Navigate]({nav(stop['address'])})")

        if i in st.session_state.arrived:
            st.success(f"Arrived: {st.session_state.arrived[i]}")

        if i in st.session_state.completed_time:
            st.info(f"Completed: {st.session_state.completed_time[i]}")

        st.divider()
