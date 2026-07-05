"""
ETL Pipeline: CMS Open Payments (2014-2024) + NPPES Gender Assignment

Downloads raw CMS General Payments data and the NPPES registry,
filters to biotech companies, assigns gender via INNER JOIN on NPI
(no name-based inference), inflation-adjusts all years to 2024 dollars,
and exports a single clean CSV.

Usage:
    python etl.py                    # run ETL only
    python etl.py --push             # run ETL and push CSV to GitHub
    python etl.py --output data/     # custom output directory
"""

import argparse
import duckdb
import gc
import glob
import os
import shutil
import subprocess
import sys
import time
import zipfile


# ----------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------

CPI_U = {
    2014: 236.736, 2015: 237.017, 2016: 240.007, 2017: 245.120,
    2018: 251.107, 2019: 255.657, 2020: 258.811, 2021: 270.970,
    2022: 292.655, 2023: 304.702, 2024: 314.690,
}
INFLATION = {yr: 314.690 / cpi for yr, cpi in CPI_U.items()}

BIOTECH_KEYWORDS = [
    'biotech', 'biotherapeutics', 'biosciences', 'biopharmaceuticals',
    'biologics', 'biopharma', 'bioscience', 'genomics',
    'gene therapy', 'therapeutics', 'oncology',
]

COMPANY_COL = 'Applicable_Manufacturer_or_Applicable_GPO_Making_Payment_Name'

NPPES_URL = 'https://download.cms.gov/nppes/NPPES_Data_Dissemination_March_2026_V2.zip'

STUDY_SPECIALTIES = {
    'Surgery': ['surgery', 'surgical', 'orthopedic', 'orthopaedic'],
    'Oncology': ['oncology', 'hematology/oncology', 'medical oncology', 'surgical oncology'],
    'Cardiology': ['cardiology', 'cardiovascular', 'interventional cardiology'],
    'Neurology': ['neurology', 'neurological', 'neurosurgery'],
}

CSV_FILENAME = 'biotech_payments_2014_2024.csv'


# ----------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------

def download(url, dest):
    """Download a file with wget. Returns True on success."""
    print(f'  Downloading {os.path.basename(dest)}...', end=' ', flush=True)
    result = subprocess.run(
        ['wget', '-q', '--tries=3', '--timeout=300', '-O', dest, url],
        capture_output=True,
    )
    if os.path.exists(dest) and os.path.getsize(dest) > 10000:
        size_gb = os.path.getsize(dest) / 1e9
        print(f'{size_gb:.2f} GB')
        return True
    if os.path.exists(dest):
        os.remove(dest)
    print('FAILED')
    return False


def extract_csv_from_zip(zip_path, extract_dir, year):
    """Extract the General Payments CSV from a CMS ZIP file."""
    with zipfile.ZipFile(zip_path, 'r') as zf:
        candidates = [f for f in zf.namelist() if 'GNRL' in f.upper() and f.endswith('.csv')]
        if not candidates:
            # Fall back to largest CSV in the archive
            all_csvs = [f for f in zf.namelist() if f.endswith('.csv')]
            if not all_csvs:
                return None
            candidates = [max(all_csvs, key=lambda f: zf.getinfo(f).file_size)]

        target = candidates[0]
        zf.extract(target, extract_dir)
        print(f'  Extracted: {target}')
        return os.path.join(extract_dir, target)


def classify_specialty(raw_spec):
    """Map a raw CMS specialty string to one of the four study categories."""
    if not raw_spec:
        return None
    lower = raw_spec.lower()
    for category, keywords in STUDY_SPECIALTIES.items():
        if any(kw in lower for kw in keywords):
            return category
    return None


# ----------------------------------------------------------------
# Main ETL
# ----------------------------------------------------------------

def run_etl(output_dir):
    """Run the full ETL pipeline."""

    raw_dir = os.path.join(output_dir, 'raw')
    pq_dir = os.path.join(output_dir, 'pq')
    nppes_dir = os.path.join(output_dir, 'nppes')
    for d in [raw_dir, pq_dir, nppes_dir]:
        os.makedirs(d, exist_ok=True)

    csv_output = os.path.join(output_dir, CSV_FILENAME)

    # Check if output already exists
    if os.path.exists(csv_output) and os.path.getsize(csv_output) > 1000:
        print(f'Output already exists: {csv_output} ({os.path.getsize(csv_output) / 1e6:.1f} MB)')
        return csv_output

    con = duckdb.connect(os.path.join(output_dir, 'etl.duckdb'))
    con.execute("SET memory_limit='8GB'; SET threads=2")

    # ---- Step 1: NPPES ----
    print('\n=== NPPES Registry ===')
    nppes_pq = os.path.join(nppes_dir, 'nppes_sex.parquet')

    if not os.path.exists(nppes_pq):
        nppes_zip = os.path.join(nppes_dir, 'nppes.zip')
        if not os.path.exists(nppes_zip):
            download(NPPES_URL, nppes_zip)

        if os.path.exists(nppes_zip):
            with zipfile.ZipFile(nppes_zip, 'r') as zf:
                csv_names = [f for f in zf.namelist() if f.endswith('.csv') and 'npidata' in f.lower()]
                if not csv_names:
                    csv_names = sorted(
                        [f for f in zf.namelist() if f.endswith('.csv')],
                        key=lambda f: zf.getinfo(f).file_size, reverse=True,
                    )
                zf.extract(csv_names[0], nppes_dir)
                nppes_csv = os.path.join(nppes_dir, csv_names[0])

            con.execute(f"""
                COPY (
                    SELECT CAST(NPI AS VARCHAR) AS npi, "Provider Sex Code" AS sex
                    FROM read_csv_auto('{nppes_csv}',
                        header=true, sample_size=50000,
                        ignore_errors=true, all_varchar=true)
                    WHERE "Entity Type Code" = '1'
                      AND "Provider Sex Code" IN ('M', 'F')
                ) TO '{nppes_pq}' (FORMAT PARQUET, COMPRESSION ZSTD)
            """)
            os.remove(nppes_csv)
            if os.path.exists(nppes_zip):
                os.remove(nppes_zip)

    count = con.execute(f"SELECT COUNT(*) FROM '{nppes_pq}'").fetchone()[0]
    print(f'  NPPES providers with sex code: {count:,}')

    # ---- Step 2: Open Payments ETL per year ----
    print('\n=== Open Payments ETL ===')
    keyword_sql = ' OR '.join([
        f"UPPER(\"{COMPANY_COL}\") LIKE '%{kw.upper()}%'"
        for kw in BIOTECH_KEYWORDS
    ])
    biotech_where = f'({keyword_sql})'

    combined_pq = os.path.join(pq_dir, 'bio_combined.parquet')
    year_parquets = []

    for year in range(2014, 2025):
        url = f'https://download.cms.gov/openpayments/PGYR{year}_P01232026_01102026.zip'
        zip_path = os.path.join(raw_dir, f'op_{year}.zip')
        year_pq = os.path.join(pq_dir, f'bio_{year}.parquet')
        multiplier = INFLATION.get(year, 1.0)

        print(f'\n--- {year} (x{multiplier:.4f}) ---')

        # Find or download the CSV
        csv_files = glob.glob(os.path.join(raw_dir, f'*{year}*.csv'))
        if not csv_files:
            if not os.path.exists(zip_path):
                if not download(url, zip_path):
                    continue
            try:
                csv_path = extract_csv_from_zip(zip_path, raw_dir, year)
                if not csv_path:
                    print(f'  No CSV found in ZIP')
                    continue
            except Exception as e:
                print(f'  Extract error: {e}')
                continue
            finally:
                if os.path.exists(zip_path):
                    os.remove(zip_path)
            csv_files = [csv_path]

        csv_path = csv_files[0]

        # ETL: filter + join + inflate
        try:
            t0 = time.time()
            con.execute(f"""
                COPY (
                    SELECT
                        CAST(op.Covered_Recipient_NPI AS VARCHAR) AS npi,
                        op.Covered_Recipient_First_Name AS first_name,
                        op.Covered_Recipient_Last_Name AS last_name,
                        op.Covered_Recipient_Specialty_1 AS specialty_raw,
                        op.Recipient_State AS state,
                        op."{COMPANY_COL}" AS company,
                        ROUND(CAST(op.Total_Amount_of_Payment_USDollars AS DOUBLE) * {multiplier}, 2) AS amt,
                        CAST(op.Total_Amount_of_Payment_USDollars AS DOUBLE) AS amt_nominal,
                        op.Nature_of_Payment_or_Transfer_of_Value AS pay_type,
                        nppes.sex AS gender,
                        {year} AS program_year
                    FROM read_csv_auto('{csv_path}',
                        header=true, sample_size=100000,
                        ignore_errors=true, all_varchar=true) op
                    INNER JOIN '{nppes_pq}' nppes
                        ON CAST(op.Covered_Recipient_NPI AS VARCHAR) = nppes.npi
                    WHERE op.Covered_Recipient_Type = 'Covered Recipient Physician'
                      AND {biotech_where}
                ) TO '{year_pq}' (FORMAT PARQUET, COMPRESSION ZSTD)
            """)
            n = con.execute(f"SELECT COUNT(*) FROM '{year_pq}'").fetchone()[0]
            print(f'  {n:,} rows, {time.time() - t0:.0f}s')
            year_parquets.append(year_pq)
        except Exception as e:
            print(f'  ETL error: {e}')

        # Free disk
        os.remove(csv_path)
        gc.collect()

    # ---- Step 3: Combine and export ----
    print('\n=== Combine and Export ===')
    if year_parquets:
        union_query = ' UNION ALL '.join([f"SELECT * FROM '{p}'" for p in year_parquets])
        con.execute(f"COPY ({union_query}) TO '{combined_pq}' (FORMAT PARQUET, COMPRESSION ZSTD)")
        for p in year_parquets:
            os.remove(p)

        # Export CSV
        con.execute(f"""
            COPY (
                SELECT * FROM '{combined_pq}' ORDER BY program_year, gender, state
            ) TO '{csv_output}' (HEADER, DELIMITER ',')
        """)

        n = con.execute(f"SELECT COUNT(*) FROM '{combined_pq}'").fetchone()[0]
        print(f'Exported: {n:,} rows to {csv_output}')
        print(f'File size: {os.path.getsize(csv_output) / 1e6:.1f} MB')

    # ---- Cleanup ----
    con.close()
    if os.path.exists(raw_dir):
        shutil.rmtree(raw_dir)
    if os.path.exists(nppes_dir):
        shutil.rmtree(nppes_dir)
    if os.path.exists(pq_dir):
        shutil.rmtree(pq_dir)
    db_path = os.path.join(output_dir, 'etl.duckdb')
    if os.path.exists(db_path):
        os.remove(db_path)

    print('Cleanup complete. Only the clean CSV remains.')
    return csv_output


def git_push(output_dir):
    """Stage, commit, and push the CSV to the current branch."""
    csv_path = os.path.join(output_dir, CSV_FILENAME)
    if not os.path.exists(csv_path):
        print('No CSV to push.')
        return

    print('\n=== Git Push ===')
    commands = [
        ['git', 'config', 'user.email', 'etl-bot@automated.local'],
        ['git', 'config', 'user.name', 'ETL Bot'],
        ['git', 'add', csv_path],
        ['git', 'commit', '-m', f'ETL: update {CSV_FILENAME}'],
        ['git', 'push'],
    ]
    for cmd in commands:
        print(f'  $ {" ".join(cmd)}')
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0 and 'nothing to commit' not in result.stdout:
            print(f'    stderr: {result.stderr.strip()}')


# ----------------------------------------------------------------
# Entry point
# ----------------------------------------------------------------

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Biotech Payments ETL Pipeline')
    parser.add_argument('--output', default='data', help='Output directory for the CSV')
    parser.add_argument('--push', action='store_true', help='Git push the CSV after ETL')
    args = parser.parse_args()

    os.makedirs(args.output, exist_ok=True)
    csv_path = run_etl(args.output)

    if args.push and csv_path:
        git_push(args.output)

    print('\nDone.')
