"""Check the 11 risk-score cases to inspect legitimate vs fraud indicators."""

import duckdb

con = duckdb.connect()
parquet = "data/transactions_trimmed.parquet"
cases_path = "data/case_pack.csv"
identity_path = "data/identity.csv"

con.execute(f"""
    CREATE TEMP TABLE cases AS SELECT * FROM read_csv_auto('{cases_path}', header=true);
    CREATE TEMP TABLE tx AS SELECT * FROM read_parquet('{parquet}');
    CREATE TEMP TABLE id AS SELECT * FROM read_csv_auto('{identity_path}', header=true);
    
    CREATE TEMP TABLE risk_cases AS
    SELECT 
        c.case_id,
        c.opened_at,
        c.risk_score,
        c.card_id,
        c.customer_id,
        t.TransactionID,
        t.TransactionAmt,
        t.ProductCD,
        t.channel,
        t.addr1,
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
    WHERE c.trigger_type = 'risk_score'
    ORDER BY c.case_id;
""")

rows = con.execute("SELECT * FROM risk_cases").fetchall()
cols = [d[0] for d in con.execute("SELECT * FROM risk_cases LIMIT 1").description]

for r in rows:
    d = dict(zip(cols, r))
    base_regions = con.execute(f"""
        SELECT DISTINCT addr1 FROM tx 
        WHERE customer_id = '{d['customer_id']}' AND ts < '{d['opened_at']}' AND addr1 IS NOT NULL
    """).fetchall()
    home_regs = [x[0] for x in base_regions]
    is_home_reg = d['addr1'] in home_regs
    
    # Check device fan-out
    dev_str = d.get('DeviceInfo') or ''
    # Check if proxy
    proxy = d.get('id_23')
    
    print(f"Case {d['case_id']}: Amt=${d['TransactionAmt']}, Prod={d['ProductCD']}, Chan={d['channel']}, Addr1={d['addr1']} (In home regions: {is_home_reg})")
    print(f"   Score={d['risk_score']}, Device={dev_str}, id_15={d['id_15']}, Proxy={proxy}")
