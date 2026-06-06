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
# CONFIG
# =========================================================
st.set_page_config(
    page_title="Time Out Lawncare Dispatch",
    page_icon="🌿",
    layout="wide"
)

st.title("🌿 Time Out Lawncare Dispatch System")


# =========================================================
# FILES
# =========================================================
CACHE_FILE = "geo_cache.json"
SAVE_FILE = "dispatch_session.json"


# =========================================================
# SESSION STATE
# =========================================================
if "dispatch" not in st.session_state:
    st.session_state.dispatch = []

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

        with open(CACHE_FILE, "r") as f:
            GEO_CACHE = json.load(f)

    except:

        GEO_CACHE = {}

else:

    GEO_CACHE = {}


def save_cache():

    with open(CACHE_FILE, "w") as f:
        json.dump(GEO_CACHE, f)


# =========================================================
# GOOGLE API KEY
# =========================================================
GOOGLE_API_KEY = st.secrets.get(
    "GOOGLE_API_KEY",
    ""
)


# =========================================================
# ADDRESS CLEANUP
# =========================================================
def clean_address(addr):

    if pd.isna(addr):
        return ""

    addr = str(addr).strip()

    addr = re.sub(
        r"\s+",
        " ",
        addr
    )

    return addr


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

        if response.get("status") == "OK":

            loc = response["results"][0]["geometry"]["location"]

            return {
                "lat": loc["lat"],
                "lon": loc["lng"]
            }

    except:
        return None

    return None


# =========================================================
# OSM FALLBACK
# =========================================================
def osm_geocode(address):

    try:

        url = (
            "https://nominatim.openstreetmap.org/search"
            f"?q={quote(address)}"
            "&format=json"
            "&limit=1"
            "&countrycodes=us"
        )

        response = requests.get(
            url,
            headers={
                "User-Agent": "crm-dispatch"
            },
            timeout=10
        ).json()

        if response:

            return {
                "lat": float(response[0]["lat"]),
                "lon": float(response[0]["lon"])
            }

    except:
        return None

    return None


# =========================================================
# PRODUCTION GEOCODER
# =========================================================
def geocode(address):

    address = clean_address(address)

    if not address:
        return None

    # CACHE
    if address in GEO_CACHE:
        return GEO_CACHE[address]

    attempts = [

        address,

        address + ", USA",

        address + ", Mississippi",

        address.replace("Dr.", "Drive"),

        address.replace("St.", "Street"),

        address.replace("Ct.", "Court")

    ]

    for attempt in attempts:

        result = google_geocode(attempt)

        if result:

            GEO_CACHE[address] = result
            save_cache()

            return result

        result = osm_geocode(attempt)

        if result:

            GEO_CACHE[address] = result
            save_cache()

            return result

        time.sleep(0.2)

    return None


# =========================================================
# DISTANCE FALLBACK
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
# NAVIGATION LINK
# =========================================================
def nav_link(address):

    return (
        "https://www.google.com/maps/search/?api=1&query="
        + quote(address)
    )


# =========================================================
# CHUNKED GOOGLE ROUTES
# =========================================================
def build_route_links(addresses):

    links = []

    if len(addresses) < 2:
        return links

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
            "&travelmode=driving"
        )

        if waypoints:
            url += f"&waypoints={waypoints}"

        links.append(url)

    return links


# =========================================================
# FILE UPLOAD
# =========================================================
uploaded = st.file_uploader(
    "Upload Customer Excel File",
    type=["xlsx"]
)

df = None

if uploaded:

    try:

        df = pd.read_excel(uploaded)

        st.success(
            f"Loaded {len(df)} customers"
        )

        st.dataframe(df)

    except Exception as e:

        st.error(
            f"Failed to read Excel file: {e}"
        )


# =========================================================
# MAIN
# =========================================================
if df is not None:

    address_col = st.selectbox(
        "Select Address Column",
        df.columns
    )

    depot = st.text_input(
        "Depot Address (start only)"
    )

    df["Include"] = True

    edited = st.data_editor(
        df,
        use_container_width=True
    )

    selected = edited[
        edited["Include"] == True
    ]

    st.info(
        f"Selected customers: {len(selected)}"
    )

    # =====================================================
    # GENERATE
    # =====================================================
    if st.button("🚀 Generate Dispatch"):

        locations = []
        failed = []

        progress = st.progress(0)

        total_rows = len(selected)

        # DEPOT
        depot_geo = None

        if depot.strip():

            depot_geo = geocode(depot)

        # CUSTOMERS
        for idx, (_, row) in enumerate(
            selected.iterrows(),
            start=1
        ):

            addr = clean_address(
                row[address_col]
            )

            geo = geocode(addr)

            if geo:

                locations.append({

                    "address": addr,

                    "lat": geo["lat"],

                    "lon": geo["lon"]

                })

            else:

                failed.append(addr)

            progress_value = min(
                int((idx / max(total_rows, 1)) * 100),
                100
            )

            progress.progress(progress_value)

        # =================================================
        # RESULTS
        # =================================================
        st.success(
            f"Successfully geocoded {len(locations)} addresses"
        )

        if failed:

            st.warning(
                f"{len(failed)} addresses failed geocoding"
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
        # ROUTING MATRIX
        # =================================================
        n = len(locations)

        matrix = np.zeros(
            (n, n),
            dtype=int
        )

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

                    response = requests.get(
                        url,
                        timeout=5
                    ).json()

                    duration = int(
                        response["routes"][0]["duration"] / 60
                    )

                    matrix[i][j] = duration

                except:

                    matrix[i][j] = int(
                        haversine(
                            locations[i],
                            locations[j]
                        ) * 2
                    )

        # =================================================
        # OPTIMIZER
        # =================================================
        manager = pywrapcp.RoutingIndexManager(
            n,
            1,
            0
        )

        routing = pywrapcp.RoutingModel(
            manager
        )

        def distance_callback(from_index, to_index):

            from_node = manager.IndexToNode(
                from_index
            )

            to_node = manager.IndexToNode(
                to_index
            )

            return int(
                matrix[from_node][to_node]
            )

        transit_callback_index = (
            routing.RegisterTransitCallback(
                distance_callback
            )
        )

        routing.SetArcCostEvaluatorOfAllVehicles(
            transit_callback_index
        )

        search_parameters = (
            pywrapcp.DefaultRoutingSearchParameters()
        )

        search_parameters.first_solution_strategy = (
            routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
        )

        search_parameters.time_limit.FromSeconds(20)

        solution = routing.SolveWithParameters(
            search_parameters
        )

        if not solution:

            st.error("Routing failed")

            st.stop()

        # =================================================
        # ROUTE
        # =================================================
        index = routing.Start(0)

        route = []

        while not routing.IsEnd(index):

            node = manager.IndexToNode(index)

            route.append(node)

            index = solution.Value(
                routing.NextVar(index)
            )

        ordered = [
            locations[i]
            for i in route
        ]

        # SAVE
        st.session_state.dispatch = ordered

        with open(SAVE_FILE, "w") as f:
            json.dump(ordered, f)

        st.success(
            "Dispatch generated successfully"
        )


# =========================================================
# DISPATCH BOARD
# =========================================================
if st.session_state.dispatch:

    ordered = st.session_state.dispatch

    st.subheader("🚚 Dispatch Board")

    # =====================================================
    # GOOGLE MAPS ROUTE LINKS
    # =====================================================
    addresses = [
        x["address"]
        for x in ordered
    ]

    route_links = build_route_links(
        addresses
    )

    if route_links:

        st.subheader("🗺️ Google Maps Route")

        for i, link in enumerate(route_links):

            st.markdown(
                f"[Open Route Segment {i+1}]({link})"
            )

    # =====================================================
    # TABLE
    # =====================================================
    table = []

    for i, stop in enumerate(ordered):

        table.append({

            "Stop": i + 1,

            "Address": stop["address"],

            "Navigate": nav_link(
                stop["address"]
            ),

            "Completed": (
                i in st.session_state.completed
            )

        })

    dispatch_df = pd.DataFrame(table)

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
    st.subheader("📍 Active Stops")

    for i, stop in enumerate(ordered):

        st.markdown(
            f"### Stop {i+1}"
        )

        st.write(stop["address"])

        c1, c2, c3 = st.columns(3)

        # ARRIVED
        with c1:

            if i not in st.session_state.arrived:

                if st.button(
                    f"Arrived {i+1}",
                    key=f"a{i}"
                ):

                    st.session_state.arrived[i] = (
                        datetime.now()
                    )

        # COMPLETE
        with c2:

            if i not in st.session_state.completed:

                if st.button(
                    f"Complete {i+1}",
                    key=f"c{i}"
                ):

                    st.session_state.completed.add(i)

                    st.session_state.completed_time[i] = (
                        datetime.now()
                    )

        # NAV
        with c3:

            st.markdown(
                f"[Navigate]({nav_link(stop['address'])})"
            )

        # TIMES
        if i in st.session_state.arrived:

            st.success(
                f"Arrived: "
                f"{st.session_state.arrived[i]}"
            )

        if i in st.session_state.completed_time:

            st.info(
                f"Completed: "
                f"{st.session_state.completed_time[i]}"
            )

        st.divider()

    # =====================================================
    # ACTIVITY REPORT
    # =====================================================
    st.subheader("📊 Dispatch Activity Report")

    report_rows = []

    for i, stop in enumerate(ordered):

        arrival = st.session_state.arrived.get(i)

        completion = st.session_state.completed_time.get(i)

        duration = None

        # ARRIVAL STRING
        if arrival:

            try:

                arrival_str = arrival.strftime(
                    "%I:%M:%S %p"
                )

            except:

                arrival_str = str(arrival)

        else:

            arrival_str = ""

        # COMPLETION STRING
        if completion:

            try:

                completion_str = completion.strftime(
                    "%I:%M:%S %p"
                )

            except:

                completion_str = str(completion)

        else:

            completion_str = ""

        # DURATION
        if arrival and completion:

            try:

                duration = round(
                    (
                        completion - arrival
                    ).total_seconds() / 60,
                    1
                )

            except:

                duration = None

        report_rows.append({

            "Stop": i + 1,

            "Address": stop["address"],

            "Arrival Time": arrival_str,

            "Completion Time": completion_str,

            "Service Minutes": duration

        })

    report_df = pd.DataFrame(report_rows)

    st.dataframe(
        report_df,
        use_container_width=True
    )

    # =====================================================
    # CSV EXPORT
    # =====================================================
    st.download_button(
        "📥 Download Activity Report CSV",
        report_df.to_csv(index=False),
        "dispatch_activity_report.csv",
        "text/csv"
    )

    # =====================================================
    # PRINTABLE HTML REPORT
    # =====================================================
    html_table = report_df.to_html(
        index=False
    )

    print_html = f"""
    <html>

    <head>

    <title>Dispatch Activity Report</title>

    <style>

    body {{
        font-family: Arial, sans-serif;
        margin: 40px;
    }}

    h1 {{
        margin-bottom: 20px;
    }}

    table {{
        border-collapse: collapse;
        width: 100%;
    }}

    th, td {{
        border: 1px solid #cccccc;
        padding: 8px;
        text-align: left;
    }}

    th {{
        background-color: #f2f2f2;
    }}

    </style>

    </head>

    <body>

    <h1>Dispatch Activity Report</h1>

    {html_table}

    </body>

    </html>
    """

    st.download_button(
        "🖨️ Download Printable HTML Report",
        print_html,
        "dispatch_report.html",
        "text/html"
    )
