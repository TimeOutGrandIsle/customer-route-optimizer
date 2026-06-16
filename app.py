# =========================================================
# app.py
# FULL CRM + DISPATCH + SQLITE IMPORT FOUNDATION
# =========================================================

import streamlit as st
import pandas as pd
import sqlite3
import requests
import re
import numpy as np

from urllib.parse import quote
from math import radians, sin, cos, sqrt, atan2

from ortools.constraint_solver import routing_enums_pb2, pywrapcp

from datetime import datetime

# =========================================================
# PAGE CONFIG
# =========================================================
st.set_page_config(
    page_title="Time Out Lawncare",
    page_icon="🌿",
    layout="wide"
)

st.title("🌿 Time Out Lawncare")

# =========================================================
# DEPOT CONFIG
# =========================================================
DEPOT_ADDRESS = "303 East Brandon Court, Brandon, MS 39042"
DEPOT_NAME = "DEPOT - Time Out Lawncare"

# =========================================================
# DATABASE
# =========================================================
conn = sqlite3.connect("crm.db", check_same_thread=False, timeout=30)
cursor = conn.cursor()

# =========================================================
# GOOGLE API + HELPERS
# =========================================================
GOOGLE_API_KEY = st.secrets.get("GOOGLE_API_KEY", "AIzaSyAw6RmDnY3jChsSdWmfGuDWa2ejvLt3NlU")

def clean_address(addr):
    if pd.isna(addr): return ""
    addr = str(addr).strip()
    return re.sub(r"\s+", " ", addr)

def geocode(address):
    if not GOOGLE_API_KEY: return None, None
    try:
        url = f"https://maps.googleapis.com/maps/api/geocode/json?address={quote(address)}&key={GOOGLE_API_KEY}"
        response = requests.get(url, timeout=10).json()
        if response["status"] == "OK":
            loc = response["results"][0]["geometry"]["location"]
            return loc["lat"], loc["lng"]
    except:
        pass
    return None, None

# Geocode Depot
DEPOT_LAT, DEPOT_LON = geocode(DEPOT_ADDRESS)

def haversine_distance(lat1, lon1, lat2, lon2):
    R = 3959
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat/2)**2 + cos(radians(lat1))*cos(radians(lat2))*sin(dlon/2)**2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    return R * c

def build_distance_matrix(route_df):
    locations = route_df[["lat", "lon"]].values
    size = len(locations)
    matrix = np.zeros((size, size))
    for i in range(size):
        for j in range(size):
            if i == j: continue
            dist = haversine_distance(locations[i][0], locations[i][1], locations[j][0], locations[j][1])
            matrix[i][j] = max(1, int(dist * 1000))
    return matrix

def solve_route(distance_matrix):
    try:
        manager = pywrapcp.RoutingIndexManager(len(distance_matrix), 1, 0)
        routing = pywrapcp.RoutingModel(manager)

        def distance_callback(from_index, to_index):
            from_node = manager.IndexToNode(from_index)
            to_node = manager.IndexToNode(to_index)
            return int(distance_matrix[from_node][to_node])

        transit_index = routing.RegisterTransitCallback(distance_callback)
        routing.SetArcCostEvaluatorOfAllVehicles(transit_index)

        search_params = pywrapcp.DefaultRoutingSearchParameters()
        search_params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC

        solution = routing.SolveWithParameters(search_params)
        if not solution: return None

        index = routing.Start(0)
        route = []
        while not routing.IsEnd(index):
            route.append(manager.IndexToNode(index))
            index = solution.Value(routing.NextVar(index))
        return route
    except Exception as e:
        st.error(f"Routing error: {e}")
        return None

# =========================================================
# TABS
# =========================================================
tab1, tab2, tab3, tab4 = st.tabs([
    "📥 Import Workbook",
    "👥 CRM",
    "🚚 Dispatch",
    "📊 Reports"
])

# =========================================================
# IMPORT WORKBOOK
# =========================================================
with tab1:
    st.header("📥 Import Existing Workbook")

    # Upgrade buttons - now only here
    if st.button("Upgrade Applications Table"):
        try:
            columns_to_add = [
                "product2_name", "product2_rate", "product2_qty",
                "product3_name", "product3_rate", "product3_qty",
                "product4_name", "product4_rate", "product4_qty",
                "product5_name", "product5_rate", "product5_qty",
                "due_date", "scheduled_date", "status"
            ]
            for col in columns_to_add:
                cursor.execute(f"ALTER TABLE applications ADD COLUMN {col} TEXT")
            conn.commit()
            st.success("Applications table upgraded")
        except Exception:
            st.info("Tables already upgraded")

    if st.button("Add Timing Columns"):
        try:
            cursor.execute("ALTER TABLE applications ADD COLUMN arrived_time TEXT")
            cursor.execute("ALTER TABLE applications ADD COLUMN completed_time TEXT")
            cursor.execute("ALTER TABLE applications ADD COLUMN route_number INTEGER")
            cursor.execute("ALTER TABLE applications ADD COLUMN stop_number INTEGER")
            conn.commit()
            st.success("✅ Timing columns added!")
        except Exception:
            st.info("Timing columns already exist")

    c1, c2 = st.columns(2)
    with c1:
        if st.button("🗑️ Clear Customers", key="clear_customers"):
            cursor.execute("DELETE FROM customers")
            conn.commit()
            st.success("Customers cleared")
            st.rerun()
    with c2:
        if st.button("🗑️ Clear Applications", key="clear_applications"):
            cursor.execute("DELETE FROM applications")
            conn.commit()
            st.success("Applications cleared")
            st.rerun()

    uploaded = st.file_uploader("Upload Excel Workbook", type=["xlsx"])

    if uploaded:
        workbook = pd.ExcelFile(uploaded)
        st.success(f"Workbook loaded with {len(workbook.sheet_names)} sheets")
        st.write(workbook.sheet_names)

        # Customer Data Import
        if "Customer_Data" in workbook.sheet_names:
            customer_df = pd.read_excel(workbook, sheet_name="Customer_Data")
            st.subheader("Customer_Data Preview")
            st.write(f"Customer Rows Found: {len(customer_df)}")
            st.dataframe(customer_df.head())

            if st.button("Import Customers", key="import_customers"):
                cursor.execute("DELETE FROM customers")
                conn.commit()
                imported = 0
                for _, row in customer_df.iterrows():
                    try:
                        customer_name = str(row.get("Customer Name", "")).strip()
                        if not customer_name:
                            continue

                        address = ""
                        for col in ["Address", "address", "Street", "street", "Street Address"]:
                            if col in customer_df.columns and pd.notna(row.get(col)):
                                address = clean_address(row.get(col))
                                break

                        city = str(row.get("City", "")).strip()
                        state = str(row.get("State", "")).strip()
                        zip_code = str(row.get("Zip", "")).strip()
                        phone = str(row.get("Phone", "")).strip()
                        email = str(row.get("Email", "")).strip()
                        notes = str(row.get("Notes", "")).strip()
                        lawn_sqft = row.get("Sq Ft", None)

                        lat, lon = geocode(f"{address}, {city}, {state} {zip_code}")

                        cursor.execute("""
                            INSERT INTO customers (customer_name, address, city, state, zip, phone, email, notes, lawn_sqft, lat, lon)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (customer_name, address, city, state, zip_code, phone, email, notes, lawn_sqft, lat, lon))
                        imported += 1
                    except Exception as e:
                        st.error(f"Error importing {customer_name}: {e}")
                conn.commit()
                st.success(f"✅ Imported {imported} customers")
                st.rerun()

# =========================================================
# CRM TAB
# =========================================================
with tab2:
    st.header("👥 Customer CRM")

    customer_df = pd.read_sql_query("SELECT * FROM customers", conn)

    search = st.text_input("Search Customers")
    if search:
        customer_df = customer_df[customer_df["customer_name"].str.contains(search, case=False, na=False)]

    st.dataframe(customer_df, use_container_width=True)

    customer_list = sorted(customer_df["customer_name"].dropna().unique().tolist())

    selected_customer = st.selectbox("Select Customer", customer_list, key="customer_select")

    if selected_customer:
        detail_df = pd.read_sql_query(
            "SELECT * FROM customers WHERE customer_name = ?",
            conn, params=(selected_customer,)
        )

        if not detail_df.empty:
            customer = detail_df.iloc[0]

            st.subheader("Customer Detail")
            c1, c2 = st.columns(2)
            with c1:
                st.write(f"**Name:** {customer['customer_name']}")
                st.write(f"**Phone:** {customer['phone']}")
                st.write(f"**Email:** {customer['email']}")
            with c2:
                st.write(f"**Address:** {customer['address']}")
                st.write(f"{customer['city']}, {customer['state']} {customer['zip']}")
                st.write(f"**Lawn Sq Ft:** {customer.get('lawn_sqft', '')}")
            st.write(f"**Notes:** {customer['notes']}")

            st.subheader("Actions")
            c1, c2, c3 = st.columns(3)
            with c1:
                edit_customer = st.button("✏️ Edit Customer", key=f"edit_{selected_customer}")
            with c2:
                delete_customer = st.button("🗑️ Delete Customer", key=f"delete_{selected_customer}")
            with c3:
                if st.button("🧾 New Application", key=f"newapp_{selected_customer}"):
                    st.session_state["new_application"] = True

            # NEW APPLICATION
            if st.session_state.get("new_application", False):
                st.subheader("🧾 New Application")
                with st.form("new_application_form"):
                    service_date = st.text_input("Service Date")
                    applicator = st.text_input("Applicator")
                    treatment_type = st.text_input("Treatment Type")
                    lawn_sqft = st.text_input("Lawn Sq Ft", value=str(customer.get("lawn_sqft", "")))

                    st.subheader("Scheduling")
                    due_date = st.text_input("Due Date")
                    scheduled_date = st.text_input("Scheduled Date")
                    status = st.selectbox("Status", ["Pending", "Scheduled", "Completed", "Cancelled"])

                    st.subheader("Products")
                    product_name = st.text_input("Product 1")
                    application_rate = st.text_input("Rate 1")
                    quantity_used = st.text_input("Quantity 1")

                    product2_name = st.text_input("Product 2")
                    product2_rate = st.text_input("Rate 2")
                    product2_qty = st.text_input("Quantity 2")

                    product3_name = st.text_input("Product 3")
                    product3_rate = st.text_input("Rate 3")
                    product3_qty = st.text_input("Quantity 3")

                    product4_name = st.text_input("Product 4")
                    product4_rate = st.text_input("Rate 4")
                    product4_qty = st.text_input("Quantity 4")

                    product5_name = st.text_input("Product 5")
                    product5_rate = st.text_input("Rate 5")
                    product5_qty = st.text_input("Quantity 5")

                    notes = st.text_area("Notes")

                    create_application = st.form_submit_button("💾 Create Application")

                if create_application:
                    cursor.execute("""
                        INSERT INTO applications (
                            customer_name, service_date, applicator, treatment_type, lawn_sqft,
                            due_date, scheduled_date, status,
                            product_name, application_rate, quantity_used,
                            product2_name, product2_rate, product2_qty,
                            product3_name, product3_rate, product3_qty,
                            product4_name, product4_rate, product4_qty,
                            product5_name, product5_rate, product5_qty, notes
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        selected_customer, service_date, applicator, treatment_type, lawn_sqft,
                        due_date, scheduled_date, status,
                        product_name, application_rate, quantity_used,
                        product2_name, product2_rate, product2_qty,
                        product3_name, product3_rate, product3_qty,
                        product4_name, product4_rate, product4_qty,
                        product5_name, product5_rate, product5_qty, notes
                    ))
                    conn.commit()
                    st.success("✅ Application created successfully!")
                    st.session_state["new_application"] = False
                    st.rerun()

            if delete_customer:
                cursor.execute("DELETE FROM customers WHERE customer_name = ?", (selected_customer,))
                conn.commit()
                st.success("Customer deleted")
                st.rerun()

            if edit_customer:
                st.session_state["editing_customer"] = selected_customer

            if st.session_state.get("editing_customer") == selected_customer:
                st.subheader("✏️ Edit Customer")
                with st.form(f"edit_form_{selected_customer}"):
                    new_phone = st.text_input("Phone", value=str(customer["phone"]))
                    new_email = st.text_input("Email", value=str(customer["email"]))
                    new_notes = st.text_area("Notes", value=str(customer["notes"]))
                    if st.form_submit_button("💾 Save"):
                        cursor.execute("""
                            UPDATE customers SET phone=?, email=?, notes=? WHERE customer_name=?
                        """, (new_phone, new_email, new_notes, selected_customer))
                        conn.commit()
                        st.success("Customer updated")
                        st.rerun()

    # Application History
    st.subheader("Application History")
    if selected_customer:
        history_df = pd.read_sql_query("""
            SELECT * FROM applications 
            WHERE customer_name = ? 
            ORDER BY service_date DESC
        """, conn, params=(selected_customer,))

        st.write(f"Applications Found: {len(history_df)}")

        for _, app in history_df.iterrows():
            title = f"{app.get('service_date')} | {app.get('treatment_type')}"
            with st.expander(title):
                c1, c2 = st.columns(2)
                with c1:
                    st.write(f"**Applicator:** {app.get('applicator')}")
                    st.write(f"**Lawn Sq Ft:** {app.get('lawn_sqft')}")
                with c2:
                    st.write(f"**Status:** {app.get('status', '')}")
                    st.write(f"**Due Date:** {app.get('due_date', '')}")

                st.markdown("### Products Used")
                products = [
                    (app.get("product_name"), app.get("application_rate"), app.get("quantity_used")),
                    (app.get("product2_name"), app.get("product2_rate"), app.get("product2_qty")),
                    (app.get("product3_name"), app.get("product3_rate"), app.get("product3_qty")),
                    (app.get("product4_name"), app.get("product4_rate"), app.get("product4_qty")),
                    (app.get("product5_name"), app.get("product5_rate"), app.get("product5_qty"))
                ]
                found_product = False
                for product, rate, qty in products:
                    if pd.notna(product) and str(product).strip() and str(product).lower() != "nan":
                        found_product = True
                        st.write(f"• {product}")
                        st.write(f"   Rate: {rate}")
                        st.write(f"   Quantity: {qty}")
                if not found_product:
                    st.info("No product data found")

                if pd.notna(app.get("notes")) and str(app.get("notes")).strip():
                    st.markdown("### Notes")
                    st.write(app["notes"])

        # Application Editor
        if len(history_df) > 0:
            history_df["display"] = history_df["service_date"].astype(str) + " | " + history_df["treatment_type"].astype(str)
            selected_application = st.selectbox(
                "Select Application To Edit", history_df["display"].tolist(), key=f"app_select_{selected_customer}"
            )
            selected_row = history_df[history_df["display"] == selected_application]
            if not selected_row.empty:
                application = selected_row.iloc[0]
                st.subheader("📝 Edit Application")
                with st.form(f"app_form_{application['id']}"):
                    service_date = st.text_input("Service Date", value=str(application.get("service_date", "")))
                    applicator = st.text_input("Applicator", value=str(application.get("applicator", "")))
                    treatment_type = st.text_input("Treatment Type", value=str(application.get("treatment_type", "")))
                    lawn_sqft = st.text_input("Lawn Sq Ft", value=str(application.get("lawn_sqft", "")))

                    st.subheader("Scheduling")
                    due_date = st.text_input("Due Date", value=str(application.get("due_date", "")))
                    scheduled_date = st.text_input("Scheduled Date", value=str(application.get("scheduled_date", "")))
                    status_options = ["Pending", "Scheduled", "Completed", "Cancelled"]
                    current_status = str(application.get("status", "Completed"))
                    if current_status not in status_options:
                        current_status = "Completed"
                    status = st.selectbox("Status", status_options, index=status_options.index(current_status))

                    st.subheader("Products")
                    product_name = st.text_input("Product 1", value=str(application.get("product_name", "")))
                    application_rate = st.text_input("Rate 1", value=str(application.get("application_rate", "")))
                    quantity_used = st.text_input("Quantity 1", value=str(application.get("quantity_used", "")))

                    product2_name = st.text_input("Product 2", value=str(application.get("product2_name", "")))
                    product2_rate = st.text_input("Rate 2", value=str(application.get("product2_rate", "")))
                    product2_qty = st.text_input("Quantity 2", value=str(application.get("product2_qty", "")))

                    product3_name = st.text_input("Product 3", value=str(application.get("product3_name", "")))
                    product3_rate = st.text_input("Rate 3", value=str(application.get("product3_rate", "")))
                    product3_qty = st.text_input("Quantity 3", value=str(application.get("product3_qty", "")))

                    product4_name = st.text_input("Product 4", value=str(application.get("product4_name", "")))
                    product4_rate = st.text_input("Rate 4", value=str(application.get("product4_rate", "")))
                    product4_qty = st.text_input("Quantity 4", value=str(application.get("product4_qty", "")))

                    product5_name = st.text_input("Product 5", value=str(application.get("product5_name", "")))
                    product5_rate = st.text_input("Rate 5", value=str(application.get("product5_rate", "")))
                    product5_qty = st.text_input("Quantity 5", value=str(application.get("product5_qty", "")))

                    notes = st.text_area("Notes", value=str(application.get("notes", "")))

                    c1, c2 = st.columns(2)
                    with c1:
                        save_application = st.form_submit_button("💾 Save Changes")
                    with c2:
                        delete_application = st.form_submit_button("🗑️ Delete Application")

                if save_application:
                    cursor.execute("""
                        UPDATE applications SET
                            service_date=?, applicator=?, treatment_type=?, lawn_sqft=?,
                            due_date=?, scheduled_date=?, status=?,
                            product_name=?, application_rate=?, quantity_used=?,
                            product2_name=?, product2_rate=?, product2_qty=?,
                            product3_name=?, product3_rate=?, product3_qty=?,
                            product4_name=?, product4_rate=?, product4_qty=?,
                            product5_name=?, product5_rate=?, product5_qty=?,
                            notes=?
                        WHERE id=?
                    """, (
                        service_date, applicator, treatment_type, lawn_sqft,
                        due_date, scheduled_date, status,
                        product_name, application_rate, quantity_used,
                        product2_name, product2_rate, product2_qty,
                        product3_name, product3_rate, product3_qty,
                        product4_name, product4_rate, product4_qty,
                        product5_name, product5_rate, product5_qty,
                        notes, int(application["id"])
                    ))
                    conn.commit()
                    st.success("Application updated")
                    st.rerun()

                if delete_application:
                    cursor.execute("DELETE FROM applications WHERE id=?", (int(application["id"]),))
                    conn.commit()
                    st.success("Application deleted")
                    st.rerun()

    # Add Customer
    st.divider()
    st.subheader("➕ Add Customer")
    with st.form("add_customer_form"):
        c1, c2 = st.columns(2)
        with c1:
            name = st.text_input("Customer Name")
            address = st.text_input("Address")
            city = st.text_input("City")
            state = st.text_input("State", value="MS")
        with c2:
            zip_code = st.text_input("Zip")
            phone = st.text_input("Phone")
            email = st.text_input("Email")
            lawn_sqft = st.number_input("Lawn Sq Ft", min_value=0.0)
        notes = st.text_area("Notes")
        if st.form_submit_button("Add Customer"):
            full_address = f"{address}, {city}, {state} {zip_code}"
            lat, lon = geocode(full_address)
            cursor.execute("""
                INSERT INTO customers (customer_name, address, city, state, zip, phone, email, notes, lawn_sqft, lat, lon)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (name, address, city, state, zip_code, phone, email, notes, lawn_sqft, lat, lon))
            conn.commit()
            st.success("Customer added successfully")
            st.rerun()

# =========================================================
# DISPATCH TAB WITH DEPOT
# =========================================================
with tab3:
    st.header("🚚 Dispatch")

    dispatch_df = pd.read_sql_query("""
        SELECT
            a.id,
            a.customer_name,
            a.treatment_type,
            a.due_date,
            a.scheduled_date,
            a.status,
            c.address,
            c.city,
            c.state,
            c.lat,
            c.lon

        FROM applications a

        LEFT JOIN customers c
            ON TRIM(LOWER(a.customer_name))
            = TRIM(LOWER(c.customer_name))

        WHERE a.status IN (
            'Pending',
            'Scheduled'
        )

""", conn)

    dispatch_df["full_address"] = dispatch_df.apply(
        lambda x:
            f"{x.get('address','')}, "
            f"{x.get('city','')}, "
            f"{x.get('state','')}",
        axis=1
    )

    c1, c2 = st.columns(2)
    with c1:
        status_filter = st.selectbox("Status Filter", ["All", "Pending", "Scheduled", "Completed", "Cancelled"])
    with c2:
        search_customer = st.text_input("Search Customer")

    filtered_df = dispatch_df.copy()
    if status_filter != "All":
        filtered_df = filtered_df[filtered_df["status"] == status_filter].copy()
    if search_customer:
        filtered_df = filtered_df[filtered_df["customer_name"].str.contains(search_customer, case=False, na=False)].copy()

    st.write(f"Applications Found: {len(filtered_df)}")

    display_df = filtered_df[["customer_name", "full_address", "due_date", "scheduled_date", "treatment_type", "status"]].copy()
    display_df["Select for Route"] = False

    edited_df = st.data_editor(
        display_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Select for Route": st.column_config.CheckboxColumn("Select for Route", default=False),
            "full_address": st.column_config.TextColumn("Full Address", width="large")
        }
    )

    selected_routes = edited_df[edited_df["Select for Route"] == True]

    st.write(f"**Selected Stops:** {len(selected_routes)}")

    if len(selected_routes) > 0:
        st.subheader("Selected Stops")
        st.dataframe(selected_routes[["customer_name", "full_address", "due_date", "scheduled_date", "treatment_type"]], use_container_width=True)

        if st.button("🚚 Generate Optimized Route", type="primary"):
            if len(selected_routes) < 1:
                st.warning("Select at least 1 stop.")
            else:
                selected_indices = selected_routes.index
                selected_ids = filtered_df.loc[selected_indices, "id"].tolist()

                placeholders = ",".join(["?"] * len(selected_ids))

                route_df = pd.read_sql_query(f"""
                    SELECT a.id,
                            a.customer_name,

                            a.arrived_time,
                            a.completed_time,

                            c.address,
                            c.city,
                            c.state,
                            c.lat,
                            c.lon
                    FROM applications a
                    LEFT JOIN customers c ON TRIM(LOWER(a.customer_name)) = TRIM(LOWER(c.customer_name))
                    WHERE a.id IN ({placeholders})
                """, conn, params=selected_ids)

                route_df = route_df.dropna(subset=["lat", "lon"]).reset_index(drop=True)

                # Add Depot
                depot_row = pd.DataFrame([{
                    "id": 0,
                    "customer_name": DEPOT_NAME,
                    "address": DEPOT_ADDRESS,
                    "city": "Brandon",
                    "state": "MS",
                    "lat": DEPOT_LAT,
                    "lon": DEPOT_LON
                }])
                route_df = pd.concat([depot_row, route_df], ignore_index=True)

                if len(route_df) < 2:
                    st.warning("Not enough valid coordinates.")
                else:
                    distance_matrix = build_distance_matrix(route_df)
                    route_order = solve_route(distance_matrix)

                    if route_order is None:
                        st.error("No feasible route found.")
                    else:
                        optimized_route = route_df.iloc[route_order].reset_index(drop=True)
                        
                        # Remove depot from displayed route

                        optimized_route = optimized_route[
                            optimized_route["id"] != 0
                        ].reset_index(drop=True)
                        
                        optimized_route = optimized_route[
                            optimized_route["id"] != 0
                        ].reset_index(drop=True)
                        
                        MAX_STOPS = 10

                        optimized_route["route_number"] = (
                            optimized_route.index // MAX_STOPS
                        ) + 1
 
                        
                        st.session_state["optimized_route"] = optimized_route 

                        optimized_route["stop_number"] = (
                            optimized_route.index + 1
                        )
                       
                        optimized_route["Stop"] = (
                            optimized_route.groupby(
                                "route_number"
                            ).cumcount()
                        ) + 1
           
        if "optimized_route" in st.session_state:

            optimized_route = st.session_state["optimized_route"]

            # st.subheader("🚚 Optimized Routes")

            max_route = optimized_route["route_number"].max()

            for route_num in sorted(
                optimized_route["route_number"].unique()
            ):

                st.subheader(
                    "🚚 Optimized Routes"
                )
                
                max_route = optimized_route["route_number"].max()
                

                for route_num in sorted(
                    optimized_route["route_number"].unique()
                ):

                    st.markdown("---")

                    st.subheader(
                        f"🚚 Route {route_num}"
                    )

                    if route_num == 1:

                        st.info(
                            "🏠 Start at Depot"
                        )

                    route_chunk = optimized_route[
                        optimized_route["route_number"]
                        == route_num
                    ]

                    for _, stop in route_chunk.iterrows():

                        st.write(
                            f"### Stop {stop['stop_number']}"
                        )

                        st.write(
                            stop["customer_name"]
                        )
                        
                        arrived = stop.get(
                            "arrived_time",
                            ""
                        )

                        completed = stop.get(
                            "completed_time",
                            ""
                        )

                        if pd.notna(arrived) and str(arrived).strip():

                            st.caption(
                                f"📍 Arrived: {arrived}"
                            )

                        if pd.notna(completed) and str(completed).strip():

                            st.caption(
                                f"✅ Completed: {completed}"
                            )

                        st.write(
                            f"{stop['address']}, "
                            f"{stop['city']}, "
                            f"{stop['state']}"
                        )

                        address = (
                            f"{stop['address']}, "
                            f"{stop['city']}, "
                            f"{stop['state']}"
                        )

                        nav_url = (
                            "https://www.google.com/maps/search/"
                            f"?api=1&query={address}"
                        )
                        
                        # st.info(
                            # "🏠 Return to Depot"
                        # )
                        
                        
                        c1, c2, c3 = st.columns(3)

                        with c1:

                            st.link_button(
                                "🧭 Navigate",
                                nav_url,
                                key=f"nav_{stop['id']}"
                            )

                        with c2:

                            if st.button(
                                "📍 Arrived",
                                key=f"arrive_{stop['id']}"
                            ):

                                arrival_time = datetime.now().strftime(
                                    "%Y-%m-%d %H:%M:%S"
                                )

                                cursor.execute(
                                    """
                                    UPDATE applications
                                    SET arrived_time=?
                                    WHERE id=?
                                    """,
                                    (
                                        arrival_time,
                                        int(stop["id"])
                                    )
                                )

                                conn.commit()

                                st.success(
                                    f"Arrived at {stop['customer_name']}"
                                )

                                # st.rerun()

                        with c3:

                            if st.button(
                                "✅ Complete",
                                key=f"complete_{stop['id']}"
                            ):

                                completed_time = datetime.now().strftime(
                                    "%Y-%m-%d %H:%M:%S"
                                )

                                cursor.execute(
                                    """
                                    UPDATE applications
                                    SET

                                        completed_time=?,
                                        status='Completed'

                                    WHERE id=?
                                    """,
                                    (
                                        completed_time,
                                        int(stop["id"])
                                    )
                                )

                                conn.commit()

                                st.success(
                                    f"Completed {stop['customer_name']}"
                                )

                                # st.rerun()
                                
                if route_num == max_route:

                    st.info(
                        "🏠 Return to Depot"
                    )

                else:

                    next_stop = (
                        route_num * MAX_STOPS
                    ) + 1

                    st.info(
                        f"➡ Continue to Stop {next_stop}"
                    )
                    

                # Google Maps with Depot
                st.subheader("🗺️ Open in Google Maps")
                waypoints = [f"{row['lat']},{row['lon']}" for _, row in optimized_route.iterrows() 
                           if pd.notna(row.get('lat')) and pd.notna(row.get('lon'))]
                if waypoints:
                    origin = waypoints[0]
                    destination = waypoints[0]  # Return to depot
                    midpoints = "|".join(waypoints[1:-1]) if len(waypoints) > 2 else ""
                    maps_url = f"https://www.google.com/maps/dir/?api=1&origin={origin}&destination={destination}&travelmode=driving"
                    if midpoints:
                        maps_url += f"&waypoints={midpoints}"
                    st.markdown(f"[🚗 Open Optimized Route in Google Maps]({maps_url})")
                    st.map(optimized_route.rename(columns={"lat": "latitude", "lon": "longitude"}))
                    
                    # st.write(
                        # optimized_route.columns.tolist()
                    # )
                    for idx, row in optimized_route.iterrows():

                        cursor.execute(
                            """
                            UPDATE applications
                            SET

                                route_number=?,
                                stop_number=?

                            WHERE id=?
                            """,
                            (
                                int(row["route_number"]),
                                int(row["stop_number"]),
                                int(row["id"])
                            )
                        )

                    conn.commit()
         
    st.divider()
    st.subheader("Today's Scheduled Applications")
    today_df = pd.read_sql_query("""
        SELECT customer_name, treatment_type, scheduled_date, status
        FROM applications WHERE status='Scheduled' ORDER BY scheduled_date
    """, conn)
    st.dataframe(today_df, use_container_width=True)

# =========================================================
# REPORTS TAB
# =========================================================
with tab4:
    st.header("📊 Reports")
    st.subheader("🚚 Completed Routes Report")

    try:
        route_data = pd.read_sql_query("""
            SELECT 
                route_number,
                stop_number,
                customer_name,
                arrived_time,
                completed_time,
                status,
                treatment_type
            FROM applications 
            WHERE arrived_time IS NOT NULL 
               OR completed_time IS NOT NULL
            ORDER BY route_number, stop_number
        """, conn)

        if len(route_data) > 0:
            route_data["arrived_time"] = pd.to_datetime(route_data["arrived_time"], errors='coerce')
            route_data["completed_time"] = pd.to_datetime(route_data["completed_time"], errors='coerce')

            route_data["Total Time on Site (min)"] = (
                route_data["completed_time"] - route_data["arrived_time"]
            ).dt.total_seconds() / 60
            route_data["Total Time on Site (min)"] = route_data["Total Time on Site (min)"].round(1)

            display_df = route_data[[
                "route_number", 
                "stop_number", 
                "customer_name", 
                "arrived_time", 
                "completed_time",
                "Total Time on Site (min)",
                "treatment_type",
                "status"
            ]].copy()

            display_df["arrived_time"] = display_df["arrived_time"].dt.strftime("%Y-%m-%d %H:%M")
            display_df["completed_time"] = display_df["completed_time"].dt.strftime("%Y-%m-%d %H:%M")

            st.success(f"Showing {len(display_df)} completed stops")

            for route_num in sorted(display_df["route_number"].dropna().unique()):
                chunk = display_df[display_df["route_number"] == route_num]
                st.markdown(f"### Route {int(route_num)}")
                st.caption(f"**Total Time on Site:** {chunk['Total Time on Site (min)'].sum():.1f} minutes")
                st.dataframe(chunk.drop(columns=["route_number"]), use_container_width=True, hide_index=True)
                st.markdown("---")

            # CSV Export Button
            if st.button("📥 Export Report to CSV", type="primary"):
                csv = display_df.to_csv(index=False)
                st.download_button(
                    label="⬇️ Download Completed Routes Report (.csv)",
                    data=csv,
                    file_name=f"completed_routes_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                    mime="text/csv"
                )

        else:
            st.info("No completed stops with timing data yet.")

    except Exception as e:
        st.error(f"Error loading report: {e}")
        if st.button("🔧 Create Missing Timing Columns"):
            try:
                cursor.execute("ALTER TABLE applications ADD COLUMN arrived_time TEXT")
                cursor.execute("ALTER TABLE applications ADD COLUMN completed_time TEXT")
                cursor.execute("ALTER TABLE applications ADD COLUMN route_number INTEGER")
                cursor.execute("ALTER TABLE applications ADD COLUMN stop_number INTEGER")
                conn.commit()
                st.success("✅ Columns added! Refresh the page.")
                st.rerun()
            except Exception as ex:
                st.info("Columns already exist.")

    # Summary Metrics
    st.subheader("📈 Summary Metrics")
    col1, col2, col3 = st.columns(3)
    with col1:
        total = pd.read_sql_query("SELECT COUNT(*) as c FROM applications WHERE completed_time IS NOT NULL", conn).iloc[0]["c"]
        st.metric("Total Completed Stops", total)
    with col2:
        today = pd.read_sql_query("SELECT COUNT(*) as c FROM applications WHERE completed_time IS NOT NULL AND DATE(completed_time) = DATE('now')", conn).iloc[0]["c"]
        st.metric("Completed Today", today)
    with col3:
        avg = pd.read_sql_query("""
            SELECT AVG((julianday(completed_time) - julianday(arrived_time)) * 1440) as avg 
            FROM applications WHERE arrived_time IS NOT NULL AND completed_time IS NOT NULL
        """, conn).iloc[0]["avg"]
        st.metric("Avg Time on Site", f"{avg:.1f} min" if pd.notna(avg) else "N/A")

# =========================================================
# TESTING
# =========================================================


