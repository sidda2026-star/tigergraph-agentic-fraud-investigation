"""Inspect details of all 20 exam cases to ensure accurate ground-truth feature discovery."""

import duckdb
from pathlib import Path

def main():
    con = duckdb.connect()
    parquet = "data/transactions_trimmed.parquet"
    cases_path = "data/case_pack.csv"
    identity_path = "data/identity.csv"
    
    con.execute(f"""
        CREATE TEMP TABLE cases AS SELECT * FROM read_csv_auto('{cases_path}', header=true);
        CREATE TEMP TABLE tx AS SELECT * FROM read_parquet('{parquet}');
        CREATE TEMP TABLE id AS SELECT * FROM read_csv_auto('{identity_path}', header=true);
        
        CREATE TEMP TABLE details AS
        SELECT 
            c.case_id,
            c.opened_at,
            c.trigger_type,
            c.trigger_text,
            c.risk_score as alert_risk_score,
            c.card_id,
            c.customer_id,
            t.TransactionID,
            t.TransactionAmt,
            t.ProductCD,
            t.channel,
            t.addr1,
            t.addr2,
            t.P_emaildomain,
            t.R_emaildomain,
            i.DeviceInfo,
            i.id_15,
            i.id_23,
            i.id_30,
            i.id_31,
            i.id_33
        FROM cases c
        JOIN tx t ON CAST(c.flagged_txn_id AS VARCHAR) = CAST(t.TransactionID AS VARCHAR)
        LEFT JOIN id i ON CAST(t.TransactionID AS VARCHAR) = CAST(i.TransactionID AS VARCHAR)
        ORDER BY c.case_id;
    """)
    
    rows = con.execute("SELECT * FROM details").fetchall()
    cols = [d[0] for d in con.execute("SELECT * FROM details LIMIT 1").description]
    
    for r in rows:
        d = dict(zip(cols, r))
        # Check baseline regions for this card
        base_regions = con.execute(f"""
            SELECT DISTINCT addr1 FROM tx 
            WHERE customer_id = '{d['customer_id']}' AND ts < '{d['opened_at']}' AND addr1 IS NOT NULL
        """).fetchall()
        d['home_regions'] = [x[0] for x in base_regions]
        
        # Check window transactions for this card
        win_txns = con.execute(f"""
            SELECT TransactionID, ts, TransactionAmt, ProductCD, channel, addr1, risk_score
            FROM tx 
            WHERE customer_id = '{d['customer_id']}' 
              AND ts BETWEEN (CAST('{d['opened_at']}' AS TIMESTAMP) - INTERVAL 3 DAYS)
                         AND (CAST('{d['opened_at']}' AS TIMESTAMP) + INTERVAL 3 DAYS)
            ORDER BY ts
        """).fetchall()
        d['n_win_txns'] = len(win_txns)
        d['win_txns'] = win_txns
        
        print(f"=== {d['case_id']} ({d['trigger_type']}) ===")
        print(f"Amt: ${d['TransactionAmt']}, Prod: {d['ProductCD']}, Chan: {d['channel']}, Addr1: {d['addr1']} (Home: {d['home_regions']})")
        print(f"Device: {d['DeviceInfo']}, id_15: {d['id_15']}, id_23: {d['id_23']}")
        print(f"Trigger text: {d['trigger_text']}")
        print(f"Window txns ({d['n_win_txns']}):")
        for wt in win_txns:
            print(f"   {wt[0]} | {wt[1]} | ${wt[2]} | {wt[3]} | {wt[4]} | addr1={wt[5]} | score={wt[6]}")
        print()

if __name__ == "__main__":
    main()
