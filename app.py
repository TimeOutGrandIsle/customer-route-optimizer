# =========================================================
# ACTIVITY REPORT
# =========================================================
st.subheader("📊 Dispatch Activity Report")

report_rows = []

for i, stop in enumerate(ordered):

    arrival = st.session_state.arrived.get(i)

    completion = st.session_state.completed_time.get(i)

    duration = None

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

        "Arrival Time": (
            arrival.strftime("%I:%M:%S %p")
            if arrival else ""
        ),

        "Completion Time": (
            completion.strftime("%I:%M:%S %p")
            if completion else ""
        ),

        "Service Minutes": duration

    })

report_df = pd.DataFrame(report_rows)

st.dataframe(
    report_df,
    use_container_width=True
)

# =========================================================
# CSV EXPORT
# =========================================================
st.download_button(
    "📥 Download Activity Report CSV",
    report_df.to_csv(index=False),
    "dispatch_activity_report.csv",
    "text/csv"
)

# =========================================================
# PRINTABLE HTML REPORT
# =========================================================
html_table = report_df.to_html(index=False)

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

<script>
window.print();
</script>

</body>
</html>
"""

st.download_button(
    "🖨️ Download Printable HTML Report",
    print_html,
    "dispatch_report.html",
    "text/html"
)
