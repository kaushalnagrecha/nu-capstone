"""
Biotech Gender Pay Parity Dashboard
Streamlit app for interactive exploration of CMS Open Payments data.

Deploy to Streamlit Community Cloud:
    1. Push this file + biotech_payments_2014_2024.csv to a GitHub repo
    2. Go to streamlit.io/cloud and connect the repo
    3. Set main file to app.py
"""

import streamlit as st
import os
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots

st.set_page_config(page_title="Biotech Gender Pay Parity", layout="wide")

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


@st.cache_data
def load_data():
    import zipfile as zf_mod
    zip_path = "data/biotech_payments_2014_2024.zip"
    csv_path = "data/biotech_payments_2014_2024.csv"

    if os.path.exists(zip_path) and not os.path.exists(csv_path):
        with zf_mod.ZipFile(zip_path, 'r') as zf:
            csv_name = [f for f in zf.namelist() if f.endswith('.csv')][0]
            zf.extract(csv_name, 'data')
            csv_path = os.path.join('data', csv_name)

    df = pd.read_csv(csv_path)
    df["gender_label"] = df["gender"].map({"M": "Male", "F": "Female"})
    df["spec_cat"] = df["specialty_raw"].apply(classify_specialty)
    return df


df = load_data()
study = df[df["spec_cat"].notna()].copy()

# ---- KPI Row ----
male_payments = study[study["gender"] == "M"]["amt"]
female_payments = study[study["gender"] == "F"]["amt"]
female_pct_records = round(100 * len(study[study["gender"] == "F"]) / len(study), 1)
female_pct_dollars = round(100 * female_payments.sum() / study["amt"].sum(), 1)
fm_overall = round(female_payments.median() / male_payments.median(), 3)

col1, col2, col3, col4 = st.columns(4)
col1.metric("Records", f"{len(study):,}", f"{female_pct_records}% female")
col2.metric("Total Payments", f"${study['amt'].sum() / 1e6:.0f}M", f"{female_pct_dollars}% female")
col3.metric("F/M Median Ratio", f"{fm_overall}")
col4.metric("Years Covered", f"{study['program_year'].nunique()}")

st.divider()

# ---- Tabs ----
tab_gender, tab_payment, tab_trend, tab_company = st.tabs([
    "Gender Distribution", "Payment Distribution", "Trends", "Company Analysis"
])

# ---- Tab 1: Gender Distribution ----
with tab_gender:
    st.subheader("Gender Distribution")

    left, right = st.columns(2)

    with left:
        # Map: % female by state
        state_g = study.groupby(["state", "gender_label"]).agg(
            physicians=("npi", "nunique")
        ).reset_index()
        state_p = state_g.pivot_table(
            index="state", columns="gender_label", values="physicians", fill_value=0
        ).reset_index()

        if "Female" in state_p.columns and "Male" in state_p.columns:
            state_p["pct_female"] = (
                100 * state_p["Female"] / (state_p["Female"] + state_p["Male"])
            ).round(1)
            state_p = state_p[state_p["state"].str.len() == 2]

            fig = px.choropleth(
                state_p,
                locations="state", locationmode="USA-states",
                color="pct_female", scope="usa",
                color_continuous_scale="RdBu",
                range_color=[25, 50],
                title="% Female Physicians by State",
            )
            fig.update_layout(height=400)
            st.plotly_chart(fig, use_container_width=True)

    with right:
        # Specialty bar
        spec_g = study.groupby(["spec_cat", "gender_label"]).agg(
            physicians=("npi", "nunique")
        ).reset_index()
        fig = px.bar(
            spec_g, x="spec_cat", y="physicians",
            color="gender_label", barmode="group",
            title="Physicians by Specialty and Gender",
        )
        fig.update_layout(height=400)
        st.plotly_chart(fig, use_container_width=True)

# ---- Tab 2: Payment Distribution ----
with tab_payment:
    st.subheader("Payment Distribution")

    left, right = st.columns(2)

    with left:
        # R/Y/G map
        state_pay = study.groupby(["state", "gender"]).agg(
            mean_pay=("amt", "mean")
        ).reset_index()
        sp = state_pay.pivot_table(
            index="state", columns="gender", values="mean_pay"
        ).reset_index()

        if "F" in sp.columns and "M" in sp.columns:
            sp["fm_ratio"] = (sp["F"] / sp["M"]).round(3)
            sp = sp[sp["state"].str.len() == 2].dropna(subset=["fm_ratio"])
            sp["gap"] = sp["fm_ratio"].apply(
                lambda r: "Women paid more"
                if r > 1.1
                else "Near parity"
                if r >= 0.9
                else "Women paid less"
            )

            fig = px.choropleth(
                sp,
                locations="state", locationmode="USA-states",
                color="gap", scope="usa",
                color_discrete_map={
                    "Women paid less": "crimson",
                    "Near parity": "gold",
                    "Women paid more": "seagreen",
                },
                title="F/M Payment Ratio by State",
            )
            fig.update_layout(height=400)
            st.plotly_chart(fig, use_container_width=True)

    with right:
        # Specialty payment
        spec_pay = study.groupby(["spec_cat", "gender_label"]).agg(
            mean_pay=("amt", "mean"),
            median_pay=("amt", "median"),
        ).reset_index()
        fig = px.bar(
            spec_pay, x="spec_cat", y="mean_pay",
            color="gender_label", barmode="group",
            title="Mean Payment by Specialty and Gender (2024 dollars)",
        )
        fig.update_layout(height=400)
        st.plotly_chart(fig, use_container_width=True)

    # Histogram
    sample = study.sample(min(100000, len(study)), random_state=42)
    fig = px.histogram(
        sample, x="amt", color="gender_label",
        nbins=60, log_y=True, barmode="overlay", opacity=0.6,
        title="Payment Amount Distribution (Log Scale)",
    )
    st.plotly_chart(fig, use_container_width=True)

# ---- Tab 3: Trends ----
with tab_trend:
    st.subheader("Year-over-Year Trends")

    yearly = study.groupby(["program_year", "gender_label"]).agg(
        mean_pay=("amt", "mean"),
        median_pay=("amt", "median"),
        records=("amt", "count"),
        physicians=("npi", "nunique"),
    ).reset_index()

    left, right = st.columns(2)
    with left:
        fig = px.line(
            yearly, x="program_year", y="median_pay",
            color="gender_label", markers=True,
            title="Median Payment by Year (2024 dollars)",
        )
        st.plotly_chart(fig, use_container_width=True)

    with right:
        fig = px.line(
            yearly, x="program_year", y="physicians",
            color="gender_label", markers=True,
            title="Unique Physicians by Year",
        )
        st.plotly_chart(fig, use_container_width=True)

# ---- Tab 4: Company Analysis ----
with tab_company:
    st.subheader("Company-Level Gender Gap")

    top_n = st.slider("Number of companies to show", 10, 30, 20)
    top_companies = study["company"].value_counts().head(top_n).index

    co_data = study[study["company"].isin(top_companies)].groupby(
        ["company", "gender"]
    ).agg(mean_pay=("amt", "mean")).reset_index()

    co_pivot = co_data.pivot_table(
        index="company", columns="gender", values="mean_pay"
    ).reset_index()

    if "F" in co_pivot.columns and "M" in co_pivot.columns:
        co_pivot["fm_ratio"] = (co_pivot["F"] / co_pivot["M"]).round(3)
        co_pivot = co_pivot.dropna(subset=["fm_ratio"]).sort_values("fm_ratio")
        co_pivot["gap"] = co_pivot["fm_ratio"].apply(
            lambda r: "Women paid more"
            if r > 1.1
            else "Near parity"
            if r >= 0.9
            else "Women paid less"
        )

        fig = px.bar(
            co_pivot, x="fm_ratio", y="company", orientation="h",
            color="gap",
            color_discrete_map={
                "Women paid less": "crimson",
                "Near parity": "gold",
                "Women paid more": "seagreen",
            },
            title=f"Top {top_n} Companies: F/M Mean Payment Ratio",
        )
        fig.add_vline(x=1.0, line_dash="dash")
        fig.update_layout(height=max(400, top_n * 25))
        st.plotly_chart(fig, use_container_width=True)
