"""TigerGraph and local data loaders for fraud investigation datasets."""

import os
import argparse
from pathlib import Path
import duckdb

BASE_COLUMNS = [
    "TransactionID",
    "customer_id",
    "ts",
    "TransactionAmt",
    "ProductCD",
    "card1",
    "card2",
    "card3",
    "card4",
    "card5",
    "card6",
    "addr1",
    "addr2",
    "P_emaildomain",
    "R_emaildomain",
    "risk_score",
    "channel",
]

SIGNAL_COLUMNS = [
    "C1", "C2", "C3", "C5", "C6",
    "D1", "D2", "D3", "D4", "D10",
    "M1", "M2", "M3", "M4", "M5", "M6",
]

def quote(path: Path) -> str:
    return str(path.resolve()).replace("'", "''")

def build_trimmed_parquet(data_dir: Path, output_parquet: Path) -> None:
    """Filter large transactions CSV to customers involved in cases & history."""
    if output_parquet.exists() and output_parquet.stat().st_size > 0:
        return
        
    transactions = quote(data_dir / "transactions.csv")
    case_pack = quote(data_dir / "case_pack.csv")
    closed_cases = quote(data_dir / "closed_cases_history.csv")
    output_path = quote(output_parquet)
    
    output_parquet.parent.mkdir(parents=True, exist_ok=True)
    columns = ",\n        ".join(BASE_COLUMNS + SIGNAL_COLUMNS)
    
    con = duckdb.connect()
    try:
        con.execute(f"""
            CREATE OR REPLACE TEMP TABLE target_customers AS
            SELECT DISTINCT customer_id FROM read_csv_auto('{case_pack}', header = true)
            UNION
            SELECT DISTINCT customer_id FROM read_csv_auto('{closed_cases}', header = true);

            COPY (
                SELECT {columns}
                FROM read_csv_auto('{transactions}', header = true)
                WHERE customer_id IN (SELECT customer_id FROM target_customers)
            ) TO '{output_path}' (FORMAT PARQUET, COMPRESSION ZSTD);
        """)
    finally:
        con.close()

def build_graph_inputs(data_dir: Path, output_dir: Path) -> None:
    """Create normalized CSVs ready for bulk loading into TigerGraph."""
    output_dir.mkdir(parents=True, exist_ok=True)
    parquet = quote(data_dir / "transactions_trimmed.parquet")
    identity = quote(data_dir / "identity.csv")
    case_pack = quote(data_dir / "case_pack.csv")
    history = quote(data_dir / "closed_cases_history.csv")
    
    con = duckdb.connect()
    try:
        con.execute(f"""
            CREATE OR REPLACE TEMP TABLE tx AS
            SELECT *, CAST(TransactionID AS VARCHAR) AS transaction_id
            FROM read_parquet('{parquet}');
            
            CREATE OR REPLACE TEMP TABLE cases AS
            SELECT * FROM read_csv_auto('{case_pack}', header=true);
            
            CREATE OR REPLACE TEMP TABLE history AS
            SELECT * FROM read_csv_auto('{history}', header=true);
            
            CREATE OR REPLACE TEMP TABLE known_cards AS
            SELECT DISTINCT c.customer_id, c.card_id, CAST(t.card1 AS VARCHAR) AS card1
            FROM cases c JOIN tx t ON CAST(c.flagged_txn_id AS VARCHAR) = t.transaction_id
            UNION
            SELECT DISTINCT h.customer_id, h.card_id, CAST(t.card1 AS VARCHAR) AS card1
            FROM history h JOIN tx t ON CAST(h.first_fraud_txn_id AS VARCHAR) = t.transaction_id
            WHERE h.first_fraud_txn_id IS NOT NULL;
            
            CREATE OR REPLACE TEMP TABLE card_map AS
            SELECT customer_id, card1, card_id FROM known_cards
            UNION ALL
            SELECT a.customer_id, a.card1,
                   a.customer_id || '-K' || CAST(
                       COALESCE(m.max_card_number, 0) +
                       ROW_NUMBER() OVER (PARTITION BY a.customer_id ORDER BY a.card1)
                       AS VARCHAR) AS card_id
            FROM (SELECT DISTINCT customer_id, CAST(card1 AS VARCHAR) AS card1 FROM tx) a
            LEFT JOIN (
                SELECT customer_id,
                       MAX(CAST(regexp_extract(card_id, '-K([0-9]+)', 1) AS INTEGER)) AS max_card_number
                FROM known_cards GROUP BY customer_id
            ) m USING (customer_id)
            WHERE NOT EXISTS (
                SELECT 1 FROM known_cards k
                WHERE k.customer_id = a.customer_id AND k.card1 = a.card1
            );
            
            CREATE OR REPLACE TEMP TABLE tx_enriched AS
            SELECT t.*, c.card_id,
                   md5(COALESCE(i.DeviceInfo, '') || '|' || COALESCE(i.id_30, '') || '|' ||
                       COALESCE(i.id_31, '') || '|' || COALESCE(i.id_33, '')) AS device_id,
                   COALESCE(i.DeviceType, '') AS device_type,
                   COALESCE(i.DeviceInfo, '') AS device_info,
                   COALESCE(i.id_30, '') AS os,
                   COALESCE(i.id_31, '') AS browser,
                   COALESCE(i.id_33, '') AS screen
            FROM tx t
            LEFT JOIN card_map c ON c.customer_id = t.customer_id
                AND c.card1 = CAST(t.card1 AS VARCHAR)
            LEFT JOIN read_csv_auto('{identity}', header=true) i
                ON CAST(i.TransactionID AS VARCHAR) = t.transaction_id;
        """)
        
        exports = {
            "customers.csv": "SELECT DISTINCT customer_id, 'dataset' AS source FROM tx_enriched",
            "cards.csv": "SELECT DISTINCT card_id, customer_id, CAST(card1 AS VARCHAR) AS card1, CAST(card4 AS VARCHAR) AS card4, CAST(card6 AS VARCHAR) AS card6 FROM tx_enriched WHERE card_id IS NOT NULL",
            "transactions.csv": "SELECT transaction_id, customer_id, card_id, ts, TransactionAmt AS amount, ProductCD AS product_cd, CAST(addr1 AS VARCHAR) AS addr1, CAST(addr2 AS VARCHAR) AS addr2, P_emaildomain AS purchaser_email, R_emaildomain AS recipient_email, channel, risk_score, C1 AS c1, C2 AS c2, C3 AS c3, C5 AS c5, C6 AS c6, D1 AS d1, D2 AS d2, D3 AS d3, D4 AS d4, D10 AS d10, CAST(M1 AS VARCHAR) AS m1, CAST(M2 AS VARCHAR) AS m2, CAST(M3 AS VARCHAR) AS m3, CAST(M4 AS VARCHAR) AS m4, CAST(M5 AS VARCHAR) AS m5, CAST(M6 AS VARCHAR) AS m6 FROM tx_enriched",
            "devices.csv": "SELECT DISTINCT device_id, device_info || ' | ' || os || ' | ' || browser || ' | ' || screen, device_type, device_info, os, browser, screen FROM tx_enriched WHERE device_id IS NOT NULL",
            "emails.csv": "SELECT DISTINCT P_emaildomain FROM tx_enriched WHERE P_emaildomain IS NOT NULL AND P_emaildomain <> '' UNION SELECT DISTINCT R_emaildomain FROM tx_enriched WHERE R_emaildomain IS NOT NULL AND R_emaildomain <> ''",
            "regions.csv": "SELECT DISTINCT CAST(addr1 AS VARCHAR) FROM tx_enriched WHERE addr1 IS NOT NULL",
            "closed_cases.csv": "SELECT case_id, customer_id, card_id, opened_at, closed_at, outcome, pattern, exposure_usd, report_filed = 'Yes', analyst_notes FROM history",
            "case_transactions.csv": "SELECT h.case_id, CAST(trim(txn_id) AS VARCHAR) FROM history h, unnest(string_split(h.txn_ids, '|')) AS x(txn_id) WHERE trim(txn_id) <> ''",
            "case_cards.csv": "SELECT h.case_id, h.card_id, h.card_id FROM history h UNION ALL SELECT h.case_id, h.card_id, trim(x.card_id) FROM history h, unnest(string_split(h.connected_card_ids, '|')) AS x(card_id) WHERE trim(x.card_id) <> ''",
        }
        for filename, query in exports.items():
            path = quote(output_dir / filename)
            con.execute(f"COPY ({query}) TO '{path}' (HEADER, DELIMITER ',')")
    finally:
        con.close()

if __name__ == "__main__":
    data_path = Path("data")
    build_trimmed_parquet(data_path, data_path / "transactions_trimmed.parquet")
    build_graph_inputs(data_path, data_path / "graph")
    print("Graph inputs built successfully.")
