import streamlit as st
import pandas as pd
import numpy as np
import requests
import time
import re
import json
import os

from urllib.parse import quote
from math import radians, sin, cos, sqrt, atan2
from datetime import datetime

from ortools.constraint_solver import pywrapcp, routing_enums_pb2


# =========================================================
# CONFIG
# =========================================================
st.set_page_config(
    page_title="Time Out Dispatch System",
    page_icon="🚚",
    layout="wide"
)

st.title("🚚 Time Out Operations Dispatch System")

SAVE_FILE = "last_dispatch.json"
GEO_CACHE_FILE = "geo_cache.json"


# =========================================================
# SESSION STATE
# =========================================================
if "dispatch" not in st.session_state:
    st.session_state.dispatch = None

if "completed" not in st.session_state:
    st.session_state.completed = set()

if "arrival_times" not in st.session_state:
    st.session_state.arrival_times = {}

if "completion_times" not in st.session_state:
    st.session_state.completion_times = {}


# =========================================================
# LOAD SAVED DISPATCH
# =========================================================
if (
    st.session_state.dispatch is None
    and os.path.exists(SAVE_FILE)
):

    try:

        with open(SAVE_FILE, "r") as f:

            st.session_state.dispatch = json.load(f)

    except:
        pass


# =========================================================
# LOAD GEO CACHE
# =========================================================
if os.path.exists(GEO_CACHE_FILE):

    try:

        with open(GEO_CACHE_FILE, "r") as f:

            GEO_CACHE = json.load(f)

    except:

        GEO_CACHE = {}

else:

    GEO_CACHE = {}


# =========================================================
# GOOGLE API KEY
# =========================================================
GOOGLE_API_KEY = st.secrets.get(
    "GOOGLE_API_KEY",
    ""
)


# =========================================================
# HELPERS
# =========================================================
def clean(addr):

    if addr is None:
        return ""

    addr = str(addr)

    addr = re.sub(r"\s+", " ", addr)

    return addr.strip()


def nav(address):

    return (
        "https://www.google.com/maps/search/?api=1&query="
        + quote(address)
    )


# =========================================================
# GOOGLE MAPS FULL ROUTE
# =========================================================
def full_route_link(addresses):

    if len(addresses) < 2:
        return None

    chunks = []

    max_stops = 10

    for i in range(0, len(addresses), max_stops):

        chunk = addresses[i:i + max_stops]

        if len(chunk) < 2:
            continue

        origin = quote(chunk[0])

        destination = quote(chunk[-1])

        waypoints = "|".join(
            quote(x)
            for x in chunk[1:-1]
        )

        url = (
            "https://www.google.com/maps/dir/?api=1"
            f"&origin={origin}"
            f"&destination={destination}"
            f"&travelmode=driving"
        )

        if waypoints:
            url += f"&waypoints={waypoints}"

        chunks.append(url)

    return chunks


# =========================================================
# SAVE GEO CACHE
# =========================================================
def save_geo_cache():

    try:

        with open(GEO_CACHE_FILE, "w") as f:

            json.dump(GEO_CACHE, f)

    except:
        pass


# =========================================================
# ADDRESS NORMALIZATION
# =========================================================
def normalize_address(address):

    address = clean(address)

    replacements = {

        " dr.": " drive",
        " dr ": " drive ",

        " rd.": " road",
        " rd ": " road ",

        " st.": " street",
        " st ": " street ",

        " blvd.": " boulevard",
        " blvd ": " boulevard ",

        " ct.": " court",
        " ct ": " court ",

        " cir.": " circle",
        " cir ": " circle ",

        " hwy ": " highway ",

        " ln.": " lane",
        " ln ": " lane ",

        " ave.": " avenue",
        " ave ": " avenue "
    }

    addr = " " + address.lower() + " "

    for k, v in replacements.items():

        addr = addr.replace(k, v)

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
            f"?address={quote(address)}"
            f"&key={GOOGLE_API_KEY}"
        )

        response = requests.get(
            url,
            timeout=10
        ).json()

        status = response.get("status")

        if (
            status == "OK"
            and response.get("results")
        ):

            loc = (
                response["results"][0]
                ["geometry"]
                ["location"]
            )

            return {
                "lat": loc["lat"],
                "lon": loc["lng"]
            }

    except:
        pass

    return None


# =========================================================
# OSM GEOCODE
# =========================================================
def osm_geocode(address):

    try:

        url = (
            "https://nominatim.openstreetmap.org/search"
            f"?q={quote(address)}"
            f"&format=json"
            f"&limit=1"
            f"&countrycodes=us"
        )

        headers = {
            "User-Agent": "field-ops-routing"
        }

        response = requests.get(
            url,
            headers=headers,
            timeout=10
        ).json()

        if response:

            return {
                "lat": float(response[0]["lat"]),
                "lon": float(response[0]["lon"])
            }

    except:
        pass

    return None


# =========================================================
# PRODUCTION GEOCODER
# =========================================================
def geocode(address):

    address = normalize_address(address)

    # =====================================================
    # CACHE HIT
    # =====================================================
    if address in GEO_CACHE:

        return GEO_CACHE[address]

    attempts = [

        address,

        address + ", USA",

        address + ", Brandon, MS",

        address + ", Mississippi",

        address.replace("highway", "hwy"),

        address.replace("street", "st"),

        address.replace("drive", "dr"),

        address.replace("court", "ct"),

        address.replace("circle", "cir")
    ]

    attempts = list(dict.fromkeys(attempts))

    for attempt in attempts:

        # =================================================
        # GOOGLE FIRST
        # =================================================
        result = google_geocode(attempt)

        if result:

            GEO_CACHE[address] = result

            save_geo_cache()

            return result

        # =================================================
        # FALLBACK OSM
        # =================================================
        result = osm_geocode(attempt)

        if result:

            GEO_CACHE[address] = result

            save_geo_cache()

            return result

        time.sleep(0.15)

    return None


# =========================================================
# DISTANCE
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
        + cos(lat1)
        * cos(lat2)
        * sin(dlon / 2) ** 2
    )

    return 2 * R * atan2(
        sqrt(x),
        sqrt(1 - x)
    )


# =========================================================
# CLUSTER KEY
# =========================================================
def cluster_key(address):

    parts = address.split(",")

    if len(parts) > 0:

        street = parts[0].strip().lower()

        words = street.split()

        if len(words) > 1:

            return words[-1]

    return "other"


# =========================================================
# ROUTE SOLVER
# =========================================================
def solve_route(locations, matrix):

    n = len(locations)

    manager = pywrapcp.RoutingIndexManager(
        n,
        1,
        0
    )

    routing = pywrapcp.RoutingModel(manager)

    def cb(i, j):

        return int(
            matrix[
                manager.IndexToNode(i)
            ][
                manager.IndexToNode(j)
            ]
        )

    transit = routing.RegisterTransitCallback(cb)

    routing.SetArcCostEvaluatorOfAllVehicles(
        transit
    )

    params = pywrapcp.DefaultRoutingSearchParameters()

    params.first_solution_strategy = (
        routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    )

    params.local_search_metaheuristic = (
        routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    )

    params.time_limit.FromSeconds(30)

    solution = routing.SolveWithParameters(params)

    if not solution:
        return None

    route = []

    total = 0

    index = routing.Start(0)

    while not routing.IsEnd(index):

        node = manager.IndexToNode(index)

        route.append(node)

        prev = index

        index = solution.Value(
            routing.NextVar(index)
        )

        total += matrix[
            manager.IndexToNode(prev)
        ][
            manager.IndexToNode(index)
        ]

    route.append(
        manager.IndexToNode(index)
    )

    return route, total


# =========================================================
# FILE UPLOAD
# =========================================================
uploaded_file = st.file_uploader(
    "Upload Customer List",
    type=["xlsx", "xls"]
)

df = None

if uploaded_file:

    try:

        df = pd.read_excel(uploaded_file)

        st.success(
            f"Loaded {len(df)} customers"
        )

    except Exception as e:

        st.error(f"Excel read error: {e}")


# =========================================================
# MAIN
# =========================================================
if df is not None:

    st.subheader("📋 Customer Selection")

    address_col = st.selectbox(
        "Address Column",
        df.columns
    )

    depot = st.text_input(
        "Depot Address (optional)"
    )

    df["Include"] = True

    edited_df = st.data_editor(
        df,
        use_container_width=True
    )

    selected_df = edited_df[
        edited_df["Include"] == True
    ]

    st.success(
        f"{len(selected_df)} customers selected"
    )

    # =====================================================
    # GENERATE ROUTE
    # =====================================================
    if st.button("🚀 Generate Dispatch"):

        locations = []
        failed = []

        depot_location = None

        st.info("Geocoding addresses...")

        # =================================================
        # DEPOT
        # =================================================
        if depot:

            geo = geocode(depot)

            if geo:

                depot_location = {
                    "address": depot,
                    **geo
                }

        # =================================================
        # CUSTOMERS
        # =================================================
        progress = st.progress(0)

        total_rows = len(selected_df)

        for counter, (_, row) in enumerate(
            selected_df.iterrows(),
            start=1
        ):

            addr = clean(
                row[address_col]
            )

            geo = geocode(addr)

            if geo:

                locations.append({
                    "address": addr,
                    **geo
                })

            else:

                failed.append(addr)

            percent = int(
                (counter / max(total_rows, 1)) * 100
            )

            percent = min(percent, 100)

            progress.progress(percent)

        # =================================================
        # RESULTS
        # =================================================
        st.success(
            f"Valid geocodes: {len(locations)}"
        )

        if failed:

            st.warning(
                f"Failed geocodes: {len(failed)}"
            )

            st.dataframe(
                pd.DataFrame(
                    failed,
                    columns=["Failed Address"]
                )
            )

        if len(locations) < 2:

            st.error(
                "Not enough valid locations"
            )

            st.stop()

        # =================================================
        # CLUSTER
        # =================================================
        st.info("Clustering neighborhoods...")

        customer_locs = locations.copy()

        customer_locs.sort(
            key=lambda x: (
                cluster_key(x["address"]),
                x["lat"],
                x["lon"]
            )
        )

        locations = customer_locs

        # =================================================
        # ADD DEPOT AS START ONLY
        # =================================================
        if depot_location:

            locations.insert(0, depot_location)

        # =================================================
        # MATRIX
        # =================================================
        st.info("Building road network matrix...")

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
                        f"{locations[j]['lon']},{locations[j]['lat']}"
                        "?overview=false"
                    )

                    r = requests.get(
                        url,
                        timeout=8
                    ).json()

                    seconds = (
                        r["routes"][0]["duration"]
                    )

                    matrix[i][j] = int(
                        seconds / 60
                    )

                except:

                    matrix[i][j] = int(
                        haversine(
                            locations[i],
                            locations[j]
                        ) * 2
                    )

        # =================================================
        # SOLVE
        # =================================================
        st.info("Optimizing route...")

        result = solve_route(
            locations,
            matrix
        )

        if not result:

            st.error("Routing failed")

            st.stop()

        route, total = result

        ordered = [
            locations[i]
            for i in route
        ]

        # =================================================
        # REMOVE DEPOT FROM DRIVER STOPS
        # =================================================
        if depot_location:

            ordered = ordered[1:]

        # =================================================
        # SAVE
        # =================================================
        st.session_state.dispatch = {
            "ordered": ordered,
            "total": total,
            "depot": depot_location
        }

        st.session_state.completed = set()

        st.session_state.arrival_times = {}

        st.session_state.completion_times = {}

        with open(SAVE_FILE, "w") as f:

            json.dump(
                st.session_state.dispatch,
                f
            )

        st.success(
            "Dispatch generated successfully"
        )


# =========================================================
# DISPATCH BOARD
# =========================================================
if st.session_state.dispatch:

    ordered = st.session_state.dispatch["ordered"]

    depot_location = st.session_state.dispatch.get(
        "depot"
    )

    st.subheader("🚚 Dispatch Board")

    # =====================================================
    # FULL GOOGLE ROUTE LINKS
    # =====================================================
    route_addresses = [
        x["address"]
        for x in ordered
    ]

    if depot_location:

        route_addresses.insert(
            0,
            depot_location["address"]
        )

    route_links = full_route_link(
        route_addresses
    )

    if route_links:

        st.subheader("🗺️ Full Google Maps Route")

        for idx, link in enumerate(route_links):

            st.markdown(
                f"[Open Route Segment {idx+1}]({link})"
            )

    # =====================================================
    # DISPATCH TABLE
    # =====================================================
    board = []

    for i, stop in enumerate(ordered):

        board.append({
            "Stop": i + 1,
            "Address": stop["address"],
            "Completed": (
                i in st.session_state.completed
            ),
            "Navigate": nav(stop["address"])
        })

    dispatch_df = pd.DataFrame(board)

    st.dataframe(
        dispatch_df,
        use_container_width=True
    )

    st.download_button(
        "📥 Download Dispatch CSV",
        dispatch_df.to_csv(index=False),
        "dispatch.csv",
        "text/csv"
    )

    # =====================================================
    # ACTIVE STOPS
    # =====================================================
    st.subheader("🚚 Active Stops")

    for i, stop in enumerate(ordered):

        st.markdown(f"### Stop {i+1}")

        st.write(stop["address"])

        col1, col2, col3 = st.columns(3)

        # =================================================
        # ARRIVED
        # =================================================
        with col1:

            if (
                i
                not in st.session_state.arrival_times
            ):

                if st.button(
                    f"Arrived #{i+1}",
                    key=f"arrive_{i}"
                ):

                    st.session_state.arrival_times[i] = (
                        datetime.now().strftime(
                            "%I:%M:%S %p"
                        )
                    )

        # =================================================
        # COMPLETE
        # =================================================
        with col2:

            if (
                i
                not in st.session_state.completed
            ):

                if st.button(
                    f"Complete #{i+1}",
                    key=f"complete_{i}"
                ):

                    st.session_state.completed.add(i)

                    st.session_state.completion_times[i] = (
                        datetime.now().strftime(
                            "%I:%M:%S %p"
                        )
                    )

        # =================================================
        # NAVIGATE
        # =================================================
        with col3:

            st.markdown(
                f"[Navigate]"
                f"({nav(stop['address'])})"
            )

        # =================================================
        # STATUS
        # =================================================
        arrival = (
            st.session_state.arrival_times.get(i)
        )

        complete = (
            st.session_state.completion_times.get(i)
        )

        if arrival:

            st.success(
                f"Arrived: {arrival}"
            )

        if complete:

            st.info(
                f"Completed: {complete}"
            )

        # =================================================
        # DURATION
        # =================================================
        if arrival and complete:

            fmt = "%I:%M:%S %p"

            try:

                start = datetime.strptime(
                    arrival,
                    fmt
                )

                end = datetime.strptime(
                    complete,
                    fmt
                )

                duration = (
                    end - start
                ).total_seconds() / 60

                st.metric(
                    f"Stop {i+1} Duration",
                    f"{int(duration)} min"
                )

            except:
                pass

        st.divider()

    # =====================================================
    # PERFORMANCE
    # =====================================================
    st.subheader("📊 Route Performance")

    st.metric(
        "Completed Stops",
        len(st.session_state.completed)
    )
