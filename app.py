# =========================================================
# app.py
# FULL CRM + DISPATCH + SQLITE IMPORT FOUNDATION
# =========================================================

import streamlit as st
import pandas as pd
import sqlite3
import requests
import json
import os
import re
import time

from urllib.parse import quote
from datetime import datetime


# =========================================================
# PAGE CONFIG
# =========================================================
st.set_page_config(
    page_title="Time Out Lawncare CRM",
    page_icon="🌿",
    layout="wide"
)

st.title("🌿 Time Out Lawncare CRM + Dispatch")


# =========================================================
# DATABASE
# =========================================================
DB_FILE = "crm.db"

conn = sqlite3.connect(
    "crm.db",
    check_same_thread=False,
    timeout=30
)

cursor = conn.cursor()


# =========================================================
# CREATE TABLES
# =========================================================
cursor.execute("""

CREATE TABLE IF NOT EXISTS customers (

    id INTEGER PRIMARY KEY AUTOINCREMENT,

    customer_name TEXT,

    address TEXT,

    city TEXT,

    state TEXT,

    zip TEXT,

    phone TEXT,

    email TEXT,

    notes TEXT,

    service_type TEXT,

    lawn_sqft REAL,

    price REAL,

    lat REAL,

    lon REAL,

    active INTEGER DEFAULT 1
)

""")

cursor.execute("""

CREATE TABLE IF NOT EXISTS applications (

    id INTEGER PRIMARY KEY AUTOINCREMENT,

    customer_name TEXT,

    service_date TEXT,

    applicator TEXT,

    treatment_type TEXT,

    lawn_sqft REAL,

    product_name TEXT,

    application_rate TEXT,

    quantity_used TEXT,

    notes TEXT
)

""")

cursor.execute("""

CREATE TABLE IF NOT EXISTS services (

    id INTEGER PRIMARY KEY AUTOINCREMENT,

    service_name TEXT,

    price REAL
)

""")

cursor.execute("""

CREATE TABLE IF NOT EXISTS chemicals (

    id INTEGER PRIMARY KEY AUTOINCREMENT,

    product_name TEXT,

    chemical_type TEXT,

    cost REAL,

    application_rate TEXT
)

""")

conn.commit()

cursor.execute("""
CREATE TABLE IF NOT EXISTS herbicides (

    id INTEGER PRIMARY KEY AUTOINCREMENT,

    product_name TEXT,
    epa_number TEXT,
    common_name TEXT,
    moa TEXT,
    active_ingredients TEXT,
    manufacturer_rates TEXT,
    fall_rate TEXT,
    spring_jan_rate TEXT,
    spring_apr_rate TEXT

)
""")

conn.commit()

# =========================================================
# GOOGLE API
# =========================================================
GOOGLE_API_KEY = st.secrets.get(
    "GOOGLE_API_KEY",
    ""
)


# =========================================================
# GEOCODING
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


def geocode(address):

    if not GOOGLE_API_KEY:
        return None, None

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

        if response["status"] == "OK":

            loc = response["results"][0]["geometry"]["location"]

            return loc["lat"], loc["lng"]

    except Exception as e:

        st.error(
            f"Customer skipped: {e}"
        )

    return None, None


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

    c1, c2 = st.columns(2)

with c1:

    if st.button(
        "🗑️ Clear Customers",
        key="clear_customers"
    ):

        cursor.execute(
            "DELETE FROM customers"
        )

        conn.commit()

        st.success(
            "Customers cleared"
        )

with c2:

    if st.button(
        "🗑️ Clear Applications",
        key="clear_applications"
    ):

        cursor.execute(
            "DELETE FROM applications"
        )

        conn.commit()

        st.success(
            "Applications cleared"
        ) 

    st.header("📥 Import Existing Workbook")

    uploaded = st.file_uploader(
        "Upload Excel Workbook",
        type=["xlsx"]
    )

    if uploaded:

        workbook = pd.ExcelFile(uploaded)

        st.success(
            f"Workbook loaded with "
            f"{len(workbook.sheet_names)} sheets"
        )

        st.write(workbook.sheet_names)

    if uploaded and "Herbicide_Data" in workbook.sheet_names:
        st.subheader("Herbicide_Data")

        tp_df = pd.read_excel(
            workbook,
            sheet_name="Herbicide_Data",
            header=None
        )

        st.dataframe(
            tp_df.head(25)
        )
    
        if "Herbicide_Data" in workbook.sheet_names:

            herb_df = pd.read_excel(
            workbook,
            sheet_name="Herbicide_Data"
        )

        st.subheader("Herbicide Data Preview")

        st.dataframe(
            herb_df.head()
        )

        if st.button("Import Herbicides"):

            cursor.execute(
                "DELETE FROM herbicides"
            )

            conn.commit()

            imported = 0

            for _, row in herb_df.iterrows():

                if pd.isna(row.get("Name")):
                    continue

                cursor.execute(
                    """
                    INSERT INTO herbicides (

                        product_name,
                        epa_number,
                        common_name,
                        moa,
                        active_ingredients,
                        manufacturer_rates,
                        fall_rate,
                        spring_jan_rate,
                        spring_apr_rate

                    )

                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(row.get("Name", "")),
                        str(row.get("EPA Number", "")),
                        str(row.get("Common Name", "")),
                        str(row.get("MOA", "")),
                        str(row.get("Active Ingredients", "")),
                        str(row.get("Mfgr. Rates", "")),
                        str(row.get("Application Rates Oz. per Acre (Fall)", "")),
                        str(row.get("Application Rates Oz. per Acre (Spring - Jan)", "")),
                        str(row.get("Application Rates Oz. per Acre (Spring - Apr)", ""))
                    )
                )

                imported += 1

            conn.commit()

            st.success(
                f"Imported {imported} herbicides"
            )

    
        # =================================================
        # IMPORT CUSTOMERS
        # =================================================
    if uploaded and "Customer_Data" in workbook.sheet_names:

            customer_df = pd.read_excel(
                workbook,
                sheet_name="Customer_Data"
            )

            st.subheader("Customer_Data Preview")

            st.dataframe(
                customer_df.head()
            )

            if st.button(
                "Import Customers",
                key="import_customers"
            ):

                cursor.execute(
                    "DELETE FROM customers"
                )

                conn.commit()

                imported = 0

            for _, row in customer_df.iterrows():

                    try:

                        customer_name = str(
                            row.get("Customer Name", "")
                        )

                        address = clean_address(
                            row.get("Address", "")
                        )

                        city = str(
                            row.get("City", "")
                        )

                        state = str(
                            row.get("State", "")
                        )

                        zip_code = str(
                            row.get("Zip", "")
                        )

                        phone = str(
                            row.get("Phone", "")
                        )

                        email = str(
                            row.get("Email", "")
                        )

                        notes = str(
                            row.get("Notes", "")
                        )

                        lawn_sqft = row.get(
                            "Sq Ft",
                            None
                        )

                        full_address = (
                            f"{address}, "
                            f"{city}, "
                            f"{state} "
                            f"{zip_code}"
                        )

                        lat, lon = geocode(
                            full_address
                        )

                        cursor.execute("""

                        INSERT INTO customers (

                            customer_name,
                            address,
                            city,
                            state,
                            zip,
                            phone,
                            email,
                            notes,
                            lawn_sqft,
                            lat,
                            lon

                        )

                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)

                        """, (

                            customer_name,
                            address,
                            city,
                            state,
                            zip_code,
                            phone,
                            email,
                            notes,
                            lawn_sqft,
                            lat,
                            lon

                        ))

                        imported += 1

                    except Exception as e:

                            st.error(
                                f"Failed to import customer: "
                                f"{customer_name}"
                            )    

                            st.write(str(e))
 
            conn.commit()

            st.success(
                f"Imported {imported} customers"
            )

        # =================================================
        # IMPORT APPLICATIONS
        # =================================================
    if uploaded and "Applications" in workbook.sheet_names:

            app_df = pd.read_excel(
                workbook,
                sheet_name="Applications"
            )

            st.subheader("Applications Columns")

            st.write(list(app_df.columns))

            st.subheader("Applications Preview")

            st.dataframe(
                app_df.head()
            )

            if st.button(
                "Import Applications",
                key="import_applications"
            ):

                cursor.execute(
                    "DELETE FROM applications"
                )

                conn.commit()

                imported = 0

                app_df = app_df.dropna(
                    subset=[
                        "Customer Name",
                        "Application Date"
                    ],
                    how="all"
                )

                for _, row in app_df.iterrows():

                    try:

                        cursor.execute(
                            """

                            INSERT INTO applications (

                                customer_name,
                                service_date,
                                applicator,
                                treatment_type,
                                lawn_sqft,
                                product_name,
                                application_rate,
                                quantity_used,
                                notes

                            )

                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)

                            """,
                            (
                                str(row.get("Customer Name", "")),
                                str(row.get("Application Date", "")),
                                str(row.get("Applicator", "")),
                                str(row.get("Treatment Type", "")),
                                row.get("Size of Area Treated", None),
                                str(row.get("Brand Name 1", "")),
                                str(row.get("Rate per Acre", "")),
                                str(row.get("Total Amount Applied (Oz)", "")),
                                ""
                            )
                        )

                        imported += 1

                    except Exception as e:

                        st.warning(
                            f"Skipped row: {e}"
                        )

                conn.commit()

                st.success(
                    f"Imported {imported} applications"
                )

# =========================================================
# IMPORT HERBICIDES
# =========================================================

if uploaded and "Herbicide_Data" in workbook.sheet_names:

    herb_df = pd.read_excel(
        workbook,
        sheet_name="Herbicide_Data"
    )

    st.subheader("🌱 Herbicide Data")

    st.dataframe(
        herb_df.head()
    )

    if st.button(
    "Import Herbicides",
    key="import_herbicides_btn"
    ):

        cursor.execute(
            "DELETE FROM herbicides"
        )

        conn.commit()

        imported = 0

        for _, row in herb_df.iterrows():

            product_name = str(
                row.get("Name", "")
            ).strip()

            if (
                product_name == ""
                or product_name.lower() == "nan"
            ):
                continue

            try:

                cursor.execute(
                    """
                    INSERT INTO herbicides (

                        product_name,
                        epa_number,
                        common_name,
                        moa,
                        active_ingredients,
                        manufacturer_rates,
                        fall_rate,
                        spring_jan_rate,
                        spring_apr_rate

                    )

                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        product_name,
                        str(row.get("EPA Number", "")),
                        str(row.get("Common Name", "")),
                        str(row.get("MOA", "")),
                        str(row.get("Active Ingredients", "")),
                        str(row.get("Mfgr. Rates", "")),
                        str(row.get("Application Rates Oz. per Acre (Fall)", "")),
                        str(row.get("Application Rates Oz. per Acre (Spring - Jan)", "")),
                        str(row.get("Application Rates Oz. per Acre (Spring - Apr)", ""))
                    )
                )

                imported += 1

            except Exception as e:

                st.warning(
                    f"Skipped row: {e}"
                )

        conn.commit()

        st.success(
            f"Imported {imported} herbicides"
        )
# =========================================================
# DISPATCH
# =========================================================
with tab3:

    st.header("🚚 Dispatch Generator")

    dispatch_df = pd.read_sql_query("""

    SELECT *
    FROM customers
    WHERE active = 1

    """, conn)

    dispatch_df["Include"] = False

    edited = st.data_editor(
        dispatch_df,
        use_container_width=True
    )

    selected = edited[
        edited["Include"] == True
    ]

    st.info(
        f"{len(selected)} customers selected"
    )

    if st.button("Generate Route"):

        if len(selected) == 0:

            st.warning(
                "No customers selected"
            )

        else:

            st.success(
                "Route generation module ready"
            )

            st.dataframe(
                selected[
                    [

                        "customer_name",

                        "address",

                        "city",

                        "phone",

                        "service_type"

                    ]
                ]
            )


# =========================================================
# REPORTS
# =========================================================
with tab4:

    st.header("📊 Reports")
    st.subheader("Application Diagnostics")

    app_count = pd.read_sql_query(
        """
        SELECT COUNT(*) AS total
        FROM applications
        """,
        conn
    )

    st.write("Application Count")
    st.dataframe(app_count)

    duplicate_check = pd.read_sql_query(
        """
        SELECT
            customer_name,
            service_date,
            COUNT(*) AS cnt
        FROM applications
        GROUP BY
            customer_name,
            service_date
        HAVING COUNT(*) > 1
        ORDER BY cnt DESC
        LIMIT 20
        """,
        conn
    )

    st.write("Potential Duplicate Records")

    st.dataframe(duplicate_check)

    st.subheader("🌱 Herbicides")

    herb_df = pd.read_sql_query(
        """
        SELECT *
        FROM herbicides
        ORDER BY product_name
        """,
        conn
    )

    st.dataframe(
        herb_df,
        use_container_width=True
    )

    herbicide_count = pd.read_sql_query(
    """
    SELECT COUNT(*) AS total
    FROM herbicides
    """,
    conn
    )

    st.metric(
        "Herbicides",
        herbicide_count.iloc[0]["total"]
    )

    # =====================================================
    # CUSTOMER COUNT
    # =====================================================
    customer_df = pd.read_sql_query(
        """
        SELECT *
        FROM customers
        """,
        conn
    )

    st.write(
        f"Actual rows in customers table: {len(customer_df)}"
    )

    # =====================================================
    # APPLICATION COUNT
    # =====================================================
    total_apps = pd.read_sql_query("""

    SELECT COUNT(*) AS total
    FROM applications

    """, conn).iloc[0]["total"]

    st.metric(
        "Total Applications",
        total_apps
    )

    if st.button("Clear Applications Table"):

        cursor.execute(
            "DELETE FROM applications"
    )

    conn.commit()

    st.success("Applications table cleared")
    # =====================================================
    # APPLICATION HISTORY
    # =====================================================
    st.subheader("Application History")

    history_df = pd.read_sql_query("""

    SELECT *
    FROM applications
    ORDER BY service_date DESC

    """, conn)

    st.dataframe(
        history_df,
        use_container_width=True
    )

    st.download_button(

        "📥 Download Application History CSV",

        history_df.to_csv(index=False),

        "application_history.csv",

        "text/csv"

    )
    
