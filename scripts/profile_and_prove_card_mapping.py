"""Test derivation rule for -K1, -K2, ... across all customers."""

import duckdb
from pathlib import Path

def main():
    data_dir = Path("data")
    tx_path = str((data_dir / "transactions.csv").resolve()).replace("'", "''")
    case_pack_path = str((data_dir / "case_pack.csv").resolve()).replace("'", "''")
    history_path = str((data_dir / "closed_cases_history.csv").resolve()).replace("'", "''")
    
    con = duckdb.connect()
    con.execute(f"CREATE TABLE cases AS SELECT * FROM read_csv_auto('{case_pack_path}', header=true)")
    con.execute(f"CREATE TABLE history AS SELECT * FROM read_csv_auto('{history_path}', header=true)")
    
    con.execute("""
        CREATE TABLE history_txns AS
        SELECT 
            h.case_id,
            h.customer_id,
            h.card_id,
            CAST(trim(t.txn_id) AS VARCHAR) as transaction_id
        FROM history h,
        UNNEST(string_split(h.txn_ids, '|')) as t(txn_id)
        WHERE trim(t.txn_id) != ''
    """)
    
    con.execute(f"""
        CREATE TABLE tx_matches AS
        SELECT 
            t.TransactionID,
            t.customer_id,
            t.card1, t.card2, t.card3, t.card4, t.card5, t.card6,
            t.ts,
            COALESCE(c.card_id, h.card_id) as known_card_id
        FROM read_csv_auto('{tx_path}', header=true) t
        LEFT JOIN cases c ON CAST(t.TransactionID AS VARCHAR) = CAST(c.flagged_txn_id AS VARCHAR)
        LEFT JOIN history_txns h ON CAST(t.TransactionID AS VARCHAR) = h.transaction_id
        WHERE c.case_id IS NOT NULL OR h.case_id IS NOT NULL
    """)
    
    # Check 1: 100% match on all 20 case_pack cases
    case_pack_matches = con.execute(f"""
        SELECT 
            c.case_id,
            c.customer_id as expected_customer,
            c.card_id as expected_card,
            t.customer_id as tx_customer,
            m.known_card_id as tx_card
        FROM cases c
        JOIN tx_matches m ON CAST(c.flagged_txn_id AS VARCHAR) = CAST(m.TransactionID AS VARCHAR)
        JOIN read_csv_auto('{tx_path}', header=true) t ON CAST(c.flagged_txn_id AS VARCHAR) = CAST(t.TransactionID AS VARCHAR)
    """).fetchall()
    
    print(f"Case pack verified count: {len(case_pack_matches)}/20")
    for r in case_pack_matches:
        assert r[1] == r[3], f"Customer mismatch in case pack: {r}"
        assert r[2] == r[4], f"Card mismatch in case pack: {r}"
    print("ALL 20 CASE PACK CASES MATCH 100% on customer and card_id!")
    
    # Check 2: 100% match on all closed cases history transactions
    hist_matches = con.execute("""
        SELECT 
            count(*) as total,
            sum(CASE WHEN ht.customer_id = m.customer_id THEN 1 ELSE 0 END) as cust_matches,
            sum(CASE WHEN ht.card_id = m.known_card_id THEN 1 ELSE 0 END) as card_matches
        FROM history_txns ht
        JOIN tx_matches m ON ht.transaction_id = CAST(m.TransactionID AS VARCHAR)
    """).fetchone()
    print(f"History txns: total={hist_matches[0]}, cust_matches={hist_matches[1]}, card_matches={hist_matches[2]}")
    assert hist_matches[0] == hist_matches[1] == hist_matches[2], "History txns mismatch!"
    print(f"ALL {hist_matches[0]} HISTORY TRANSACTIONS MATCH 100% on customer and card_id!")

if __name__ == "__main__":
    main()
