# Gender Disparities in Biotech Industry Payments to Physicians

## CMS Open Payments Analysis | 2014 to 2024

---

## Problem Statement

The U.S. healthcare industry transfers billions of dollars annually to physicians through consulting fees, research funding, royalties, and speaking engagements. Since 2014, the CMS Open Payments database has publicly reported these transactions under the Physician Payments Sunshine Act. However, the database does not include physician gender, making it impossible to assess payment equity without external data linkage.

Emerging research has revealed significant gender disparities in these payments. Sullivan et al. (2022) found a thirty-fold gap in mean industry payments between male and female physicians across the top 15 medical companies. Wang et al. (2024) documented similar patterns in urology, while Kabangu et al. (2025) found that female neurosurgeons received just 1.15% of total industry payment dollars despite comprising a growing share of the specialty.

Despite this evidence, no study has examined the **biotech industry** as a distinct sector. Biotech companies operate differently from traditional pharmaceutical or medical device firms, with higher concentration in research-intensive therapies, novel biologics, and gene therapies. This project fills that gap by analyzing biotech-specific payments across a full decade of CMS data.

### Research Questions

1. Is there a statistically significant difference in biotech industry payment distributions between male and female physicians?
2. Which specialties, companies, and geographic regions show the largest gender gaps?
3. Can predictive models detect gender signal from payment characteristics at better-than-chance accuracy?

### Hypotheses

**H0:** There is no significant difference in the distribution of industry payment amounts between male and female physicians from top biotech companies.

**H1:** There is a significant difference, with female physicians receiving systematically lower payments.

---

## Data

| Source | Description | Role |
| --- | --- | --- |
| CMS Open Payments (2014 to 2024) | General Payments CSV per program year | Payment records |
| NPPES NPI Registry | Self-reported Provider Sex Code | Gender assignment |
| BLS CPI-U Tables | Annual average Consumer Price Index | Inflation adjustment |

**Scope:** Biotech companies identified through 11 industry keywords applied to the manufacturer name field. Top companies are queried dynamically from the data (not hardcoded). Analysis is restricted to four DOOIT study protocol specialties: Surgery, Oncology, Cardiology, and Neurology.

**Gender Assignment:** INNER JOIN to NPPES on NPI. Every record in the analysis has a verified, self-reported gender. Unmatched records are dropped. No name-based inference is used.

---

## Methodology

### Data Pipeline

The pipeline processes approximately 50 GB of raw CMS data across 11 program years using DuckDB as a streaming SQL engine inside a Google Colab notebook. For each year, the pipeline:

1. Downloads the General Payments ZIP from CMS
2. Extracts the CSV and scans it lazily through DuckDB (never loads into memory)
3. Applies the biotech keyword filter on the manufacturer name
4. Joins to NPPES on NPI to assign gender (INNER JOIN, drops unmatched)
5. Multiplies payment amounts by the year-specific CPI-U inflation factor to convert to 2024 dollars
6. Writes the filtered records to compressed Parquet
7. Deletes the raw CSV and ZIP to conserve disk space

After all years are processed, the individual Parquet files are combined into a single file and exported as `biotech_payments_2014_2024.csv`.

### Inflation Adjustment

All payment amounts are converted to 2024 dollars using CPI-U annual averages:

| Year | CPI-U | Multiplier |
| --- | --- | --- |
| 2014 | 236.736 | 1.3294 |
| 2016 | 240.007 | 1.3112 |
| 2018 | 251.107 | 1.2532 |
| 2020 | 258.811 | 1.2159 |
| 2022 | 292.655 | 1.0753 |
| 2024 | 314.690 | 1.0000 |

### Specialty Mapping

Raw CMS specialty strings are mapped to four DOOIT study categories using keyword matching:

- **Surgery:** surgery, surgical, orthopedic, orthopaedic
- **Oncology:** oncology, hematology/oncology, medical oncology, surgical oncology
- **Cardiology:** cardiology, cardiovascular, interventional cardiology
- **Neurology:** neurology, neurological, neurosurgery

Records outside these four categories are excluded from the study analysis.

### Statistical Testing

Three tests assess whether the gender payment gap is statistically significant:

- **Mann-Whitney U test** (one-tailed): Non-parametric test appropriate for the heavily right-skewed payment distribution
- **Welch's t-test** (one-tailed): Parametric comparison of means, robust to unequal variances
- **Cohen's d**: Effect size measure to quantify the practical magnitude of the difference

All tests use per-physician total payments (inflation-adjusted, aggregated across all years).

### Predictive Modeling

Two rounds of modeling, each with 5 linear regression and 5 logistic classification models:

**Round 1: Control Models (Minimal Features)**

Purpose: Prove that gender is statistically significant with only basic controls.

- Linear models predict `log1p(payment)` using: `is_female`, specialty dummies, year dummies
- Logistic models predict `is_female` using: `payment amount`, specialty dummies, year dummies
- Model architectures: Linear/Logistic Regression, Ridge, Lasso/Ridge Logistic, ElasticNet/Random Forest, XGBoost, Gradient Boosting

**Round 2: All-Variable Models (Full Controls)**

Purpose: Maximize prediction accuracy and test whether the gender signal persists after adding compositional controls.

- Additional features: state (top 15 + Other), company tier (top 5 / top 20 / other), payment type (top 10 + Other)
- Same 10 model architectures retrained on the expanded feature set
- Linear models always include `is_female` as a required feature
- Logistic models always include `payment amount` as a required feature

**Evaluation:**

The comparison between rounds reveals how much of the gender signal is explained by compositional factors (specialty mix, company, geography, payment type) versus remaining as an independent effect. The `is_female` coefficient from linear models is the primary indicator: if it remains negative and significant after adding all controls, gender has independent explanatory power.

---

## Findings

### Overall Gender Gap

| Metric | Male | Female | F/M Ratio |
| --- | --- | --- | --- |
| Physicians | ~180,500 | ~101,600 | 0.563 |
| Total payment records | ~2.4M | ~1.2M | 0.500 |
| Mean payment (2024 dollars) | ~$482 | ~$330 | 0.685 |
| Median payment (2024 dollars) | ~$155 | ~$112 | 0.723 |
| P95 payment (2024 dollars) | ~$2,840 | ~$1,560 | 0.549 |

Women represent 36% of biotech-paid physicians but receive approximately 31% of total payment dollars. The gap is widest at the top of the distribution (P95 ratio of 0.549), indicating that high-value engagements like consulting, speaking, and royalties are where the disparity concentrates.

### Statistical Tests

| Test | Statistic | p-value | Interpretation |
| --- | --- | --- | --- |
| Mann-Whitney U | U ~ 14.2B | p < 2.2e-308 | Reject H0 |
| Welch's t-test | t ~ -28.4 | p < 1.0e-175 | Reject H0 |
| Cohen's d | 0.18 | Small effect | Significant but modest per-transaction |

The small effect size (d = 0.18) despite extreme statistical significance reflects the massive sample size. The gap is real and systematic but modest at the individual transaction level. It compounds across thousands of transactions per physician over a decade to produce large aggregate disparities.

### Specialty Analysis

| Specialty | F/M Mean Ratio | Interpretation |
| --- | --- | --- |
| Surgery | 0.61 | Largest gap |
| Cardiology | 0.68 | Substantial gap |
| Neurology | 0.72 | Moderate gap |
| Oncology | 0.74 | Narrowest gap (still below parity) |

Surgery shows the largest gap, consistent with Kabangu et al. (2025). Oncology shows the narrowest gap, potentially reflecting the more formalized, research-driven nature of oncology industry engagements.

### Year-over-Year Trend

The F/M median payment ratio has remained stable at approximately 0.70 to 0.73 across all program years from 2014 to 2024. Both male and female medians have risen in inflation-adjusted terms, but the ratio is not converging. The gap is persistent and not self-correcting.

### Company Benchmarking

Of the top 15 biotech companies by payment volume, 13 fall below the 0.90 parity threshold. Only 2 companies exceed parity (F/M ratio above 1.10). This confirms a systemic industry-wide pattern rather than a problem limited to a few firms.

### Predictive Model Results

**Control Models (Minimal Features):**

| Model | Classification AUC | Regression R-squared |
| --- | --- | --- |
| XGBoost | 0.621 | 0.08 |
| Gradient Boosting | 0.614 | n/a |
| Random Forest | 0.598 | n/a |
| Logistic/Linear Regression | 0.583 | 0.06 |

**All-Variable Models (Full Controls):**

| Model | Classification AUC | Regression R-squared |
| --- | --- | --- |
| XGBoost | 0.681 | 0.287 |
| Random Forest | 0.667 | 0.261 |
| Gradient Boosting | 0.652 | n/a |
| Linear Regression | n/a | 0.195 |

**Gender Coefficient:**

- Control models: `is_female` = -0.24 (log scale), equivalent to approximately 21% lower payment
- All-variable models: `is_female` = -0.19 (log scale), equivalent to approximately 17% lower payment
- The coefficient shrinks by about 21% when adding controls, but does not approach zero
- Interpretation: compositional factors (specialty, company, geography) explain some of the gap, but a significant independent gender effect persists

---

## Project Structure

```
.
├── biotech_gender_parity_colab_2014_2024.ipynb   # Main analysis notebook (Google Colab)
├── biotech_payments_2014_2024.csv                 # Clean export (generated by notebook)
├── app.py                                         # Streamlit dashboard (generated by notebook)
├── Final_Project_Proposal_Gender_Disparities_Biotech.docx   # Research proposal
├── DOOIT_Midterm_Presentation.pptx                # Presentation deck
├── Status_Report_Gender_Disparities_Biotech.docx  # Status report with findings
└── README.md                                      # This file
```

## How to Run

1. Open the notebook in Google Colab
2. Enable Internet access in the Colab runtime settings
3. Run all cells sequentially (the pipeline downloads, processes, and deletes data automatically)
4. The clean CSV and Streamlit app are saved to `/content/`

For the Streamlit dashboard:

1. Download `biotech_payments_2014_2024.csv` and `app.py` from the Colab output
2. Push both to a GitHub repository
3. Connect the repository to Streamlit Community Cloud at streamlit.io/cloud
4. Set the main file to `app.py`

## Limitations

- Gender classification is binary (M/F from NPPES) and cannot identify non-binary individuals
- Career stage, academic rank, and publication record are not available in CMS administrative data
- "Biotech company" is not a standard CMS classification; the keyword filter may miss smaller firms
- R-squared values of 0.19 to 0.29 reflect the inherent limitation of administrative data, not model failure
- CMS download URLs for older program years may require verification as CMS periodically updates hosting

## References

Gong, Q., & Hu, X. (2024). Gender composition in the work environment and physicians' income. *Human Resources for Health*, *22*(1), 81. https://doi.org/10.1186/s12960-024-00962-5

Kabangu, J. K., Hernandez, A., Graham, D., Dugan, J. E., & Eden, S. V. (2025). Gender disparities in industry payments to neurosurgeons. *Journal of Neurosurgery*, *142*(5), 1476 to 1484. https://doi.org/10.3171/2024.8.JNS24792

Richardson, E. (2014). The Physician Payments Sunshine Act. *Health Affairs Health Policy Brief*. https://doi.org/10.1377/hpb20141002.272302

Sullivan, B. G., et al. (2022). Assessment of medical industry compensation to US physicians by gender. *JAMA Surgery*, *157*(11), 1017 to 1022. https://doi.org/10.1001/jamasurg.2022.4301

Wang, Y., et al. (2024). Assessment of the gender gap in urology industry payments. *Investigative and Clinical Urology*, *65*(4), 411 to 419. https://doi.org/10.4111/icu.20240021

Wilson, M. (2014). The Sunshine Act: Commercial conflicts of interest and the limits of transparency. *Open Medicine*, *8*(1), e10 to e13.
