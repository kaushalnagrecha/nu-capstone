"""
Build a static HTML dashboard with embedded Plotly charts.
Reads from data/biotech_payments_2014_2024.csv and writes to site/index.html.
Designed to be deployed to GitHub Pages.
"""

import os
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots

STUDY_SPECIALTIES = {
    "Surgery": ["surgery", "surgical", "orthopedic", "orthopaedic"],
    "Oncology": ["oncology", "hematology/oncology"],
    "Cardiology": ["cardiology", "cardiovascular"],
    "Neurology": ["neurology", "neurological", "neurosurgery"],
}


def classify_specialty(raw_spec):
    if not isinstance(raw_spec, str):
        return None
    lower = raw_spec.lower()
    for category, keywords in STUDY_SPECIALTIES.items():
        if any(kw in lower for kw in keywords):
            return category
    return None


def build():
    print("Loading data...")
    csv_path = "data/biotech_payments_2014_2024.csv"
    if not os.path.exists(csv_path):
        print(f"ERROR: {csv_path} not found. Run etl.py first.")
        return

    df = pd.read_csv(csv_path)
    df["gender_label"] = df["gender"].map({"M": "Male", "F": "Female"})
    df["spec_cat"] = df["specialty_raw"].apply(classify_specialty)
    study = df[df["spec_cat"].notna()].copy()

    print(f"Loaded {len(study):,} study records from {len(df):,} total")

    # Compute KPIs
    male_pay = study[study["gender"] == "M"]["amt"]
    female_pay = study[study["gender"] == "F"]["amt"]
    pct_f_records = round(100 * len(study[study["gender"] == "F"]) / len(study), 1)
    pct_f_dollars = round(100 * female_pay.sum() / study["amt"].sum(), 1)
    fm_ratio = round(female_pay.median() / male_pay.median(), 3)
    years_covered = study["program_year"].nunique()

    charts = []

    # ---- Chart 1: Gender distribution by state ----
    state_g = study.groupby(["state", "gender_label"]).agg(
        physicians=("npi", "nunique")
    ).reset_index()
    sp = state_g.pivot_table(
        index="state", columns="gender_label", values="physicians", fill_value=0
    ).reset_index()
    if "Female" in sp.columns and "Male" in sp.columns:
        sp["pct_female"] = (100 * sp["Female"] / (sp["Female"] + sp["Male"])).round(1)
        sp = sp[sp["state"].str.len() == 2]
        fig = px.choropleth(
            sp, locations="state", locationmode="USA-states",
            color="pct_female", scope="usa",
            color_continuous_scale="RdBu", range_color=[25, 50],
            title="% Female Physicians by State",
        )
        fig.update_layout(height=450, margin=dict(l=0, r=0, t=40, b=0))
        charts.append(("Gender Distribution by State", fig))

    # ---- Chart 2: Specialty breakdown ----
    spec_g = study.groupby(["spec_cat", "gender_label"]).agg(
        physicians=("npi", "nunique")
    ).reset_index()
    fig = px.bar(
        spec_g, x="spec_cat", y="physicians",
        color="gender_label", barmode="group",
        title="Physicians by Specialty and Gender",
    )
    fig.update_layout(height=400)
    charts.append(("Specialty Breakdown", fig))

    # ---- Chart 3: R/Y/G payment map ----
    state_pay = study.groupby(["state", "gender"]).agg(
        mean_pay=("amt", "mean")
    ).reset_index()
    sp2 = state_pay.pivot_table(
        index="state", columns="gender", values="mean_pay"
    ).reset_index()
    if "F" in sp2.columns and "M" in sp2.columns:
        sp2["fm_ratio"] = (sp2["F"] / sp2["M"]).round(3)
        sp2 = sp2[sp2["state"].str.len() == 2].dropna(subset=["fm_ratio"])
        sp2["gap"] = sp2["fm_ratio"].apply(
            lambda r: "Women paid more" if r > 1.1
            else "Near parity" if r >= 0.9
            else "Women paid less"
        )
        fig = px.choropleth(
            sp2, locations="state", locationmode="USA-states",
            color="gap", scope="usa",
            color_discrete_map={
                "Women paid less": "crimson",
                "Near parity": "gold",
                "Women paid more": "seagreen",
            },
            title="F/M Mean Payment Ratio by State",
        )
        fig.update_layout(height=450, margin=dict(l=0, r=0, t=40, b=0))
        charts.append(("Payment Gap by State", fig))

    # ---- Chart 4: Year trend ----
    yearly = study.groupby(["program_year", "gender_label"]).agg(
        median_pay=("amt", "median"),
    ).reset_index()
    fig = px.line(
        yearly, x="program_year", y="median_pay",
        color="gender_label", markers=True,
        title="Median Payment Trend (2024 dollars)",
    )
    fig.update_layout(height=400)
    charts.append(("Year-over-Year Trend", fig))

    # ---- Chart 5: Company F/M ratio ----
    top_20 = study["company"].value_counts().head(20).index
    co = study[study["company"].isin(top_20)].groupby(
        ["company", "gender"]
    ).agg(mean_pay=("amt", "mean")).reset_index()
    co_p = co.pivot_table(index="company", columns="gender", values="mean_pay").reset_index()
    if "F" in co_p.columns and "M" in co_p.columns:
        co_p["fm_ratio"] = (co_p["F"] / co_p["M"]).round(3)
        co_p = co_p.dropna(subset=["fm_ratio"]).sort_values("fm_ratio")
        co_p["gap"] = co_p["fm_ratio"].apply(
            lambda r: "Women paid more" if r > 1.1
            else "Near parity" if r >= 0.9
            else "Women paid less"
        )
        fig = px.bar(
            co_p, x="fm_ratio", y="company", orientation="h",
            color="gap",
            color_discrete_map={
                "Women paid less": "crimson",
                "Near parity": "gold",
                "Women paid more": "seagreen",
            },
            title="Top 20 Companies: F/M Payment Ratio",
        )
        fig.add_vline(x=1.0, line_dash="dash")
        fig.update_layout(height=550)
        charts.append(("Company Analysis", fig))

    # ---- Chart 6: Payment histogram ----
    sample = study.sample(min(100000, len(study)), random_state=42)
    fig = px.histogram(
        sample, x="amt", color="gender_label",
        nbins=60, log_y=True, barmode="overlay", opacity=0.6,
        title="Payment Amount Distribution (Log Scale)",
    )
    fig.update_layout(height=400)
    charts.append(("Payment Distribution", fig))

    # ---- Build HTML ----
    print("Generating HTML...")

    chart_divs = ""
    for title, fig in charts:
        chart_html = fig.to_html(full_html=False, include_plotlyjs=False)
        chart_divs += f"""
        <section>
            <h2>{title}</h2>
            {chart_html}
        </section>
        """

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Biotech Gender Pay Parity Dashboard</title>
    <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: 'Segoe UI', system-ui, sans-serif; background: #f8fafc; color: #1e293b; }}
        header {{ background: #1e293b; color: white; padding: 2rem; text-align: center; }}
        header h1 {{ font-size: 1.8rem; font-weight: 700; }}
        header p {{ color: #94a3b8; margin-top: 0.5rem; }}
        .kpi-row {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 1rem; padding: 1.5rem 2rem; max-width: 1200px; margin: 0 auto; }}
        .kpi {{ background: white; border-radius: 8px; padding: 1.5rem; text-align: center; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
        .kpi .value {{ font-size: 2rem; font-weight: 700; }}
        .kpi .label {{ font-size: 0.85rem; color: #64748b; margin-top: 0.25rem; }}
        main {{ max-width: 1200px; margin: 0 auto; padding: 0 2rem 3rem; }}
        section {{ background: white; border-radius: 8px; padding: 1.5rem; margin-bottom: 1.5rem; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
        section h2 {{ font-size: 1.1rem; margin-bottom: 1rem; color: #334155; }}
        footer {{ text-align: center; padding: 2rem; color: #94a3b8; font-size: 0.85rem; }}
        @media (max-width: 768px) {{ .kpi-row {{ grid-template-columns: repeat(2, 1fr); }} }}
    </style>
</head>
<body>
    <header>
        <h1>Biotech Gender Pay Parity Dashboard</h1>
        <p>CMS Open Payments 2014 to 2024 | NPPES Gender Verification | Inflation-Adjusted to 2024 Dollars</p>
    </header>

    <div class="kpi-row">
        <div class="kpi">
            <div class="value">{len(study):,}</div>
            <div class="label">Payment Records ({pct_f_records}% female)</div>
        </div>
        <div class="kpi">
            <div class="value">${study['amt'].sum() / 1e6:.0f}M</div>
            <div class="label">Total Payments ({pct_f_dollars}% female)</div>
        </div>
        <div class="kpi">
            <div class="value">{fm_ratio}</div>
            <div class="label">F/M Median Payment Ratio</div>
        </div>
        <div class="kpi">
            <div class="value">{years_covered}</div>
            <div class="label">Program Years Analyzed</div>
        </div>
    </div>

    <main>
        {chart_divs}
    </main>

    <footer>
        Data: CMS Open Payments (2014 to 2024) | Gender: NPPES Provider Sex Code (INNER JOIN only)
        | Analysis: DOOIT / Northeastern University
    </footer>
</body>
</html>"""

    os.makedirs("site", exist_ok=True)
    with open("site/index.html", "w") as f:
        f.write(html)

    size_kb = os.path.getsize("site/index.html") / 1024
    print(f"Dashboard written to site/index.html ({size_kb:.0f} KB)")
    print(f"Charts: {len(charts)}")


if __name__ == "__main__":
    build()
