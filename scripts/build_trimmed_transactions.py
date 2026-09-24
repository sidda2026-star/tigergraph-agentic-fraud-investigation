"""Build the Phase 1 transaction extract without loading the source CSV into memory."""

from __future__ import annotations

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
    "C1",
    "C2",
    "C3",
    "C5",
    "C6",
    "D1",
    "D2",
    "D3",
    "D4",
    "D10",
    "M1",
    "M2",
    "M3",
    "M4",
    "M5",
    "M6",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/transactions_trimmed.parquet"),
    )
    parser.add_argument(
        "--csv-output",
        type=Path,
        help="Also write a CSV copy of the filtered extract.",
    )
    return parser.parse_args()


def sql_string(path: Path) -> str:
    return str(path.resolve()).replace("'", "''")


def main() -> None:
    args = parse_args()
    data_dir = args.data_dir.resolve()
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    transactions = sql_string(data_dir / "transactions.csv")
    case_pack = sql_string(data_dir / "case_pack.csv")
    closed_cases = sql_string(data_dir / "closed_cases_history.csv")
    output_path = sql_string(output)

    columns = ",\n        ".join(BASE_COLUMNS + SIGNAL_COLUMNS)
    connection = duckdb.connect()
    try:
        connection.execute(
            f"""
            CREATE OR REPLACE TEMP TABLE target_customers AS
            SELECT DISTINCT customer_id
            FROM read_csv_auto('{case_pack}', header = true)
            UNION
            SELECT DISTINCT customer_id
            FROM read_csv_auto('{closed_cases}', header = true);

            COPY (
                SELECT
                    {columns}
                FROM read_csv_auto('{transactions}', header = true)
                WHERE customer_id IN (SELECT customer_id FROM target_customers)
            ) TO '{output_path}' (FORMAT PARQUET, COMPRESSION ZSTD);
            """
        )

        if args.csv_output:
            csv_output = args.csv_output.resolve()
            csv_output.parent.mkdir(parents=True, exist_ok=True)
            csv_path = sql_string(csv_output)
            connection.execute(
                f"""
                COPY (SELECT * FROM read_parquet('{output_path}'))
                TO '{csv_path}' (HEADER, DELIMITER ',');
                """
            )

        count = connection.execute(
            f"SELECT COUNT(*) FROM read_parquet('{output_path}')"
        ).fetchone()[0]
        customer_count = connection.execute(
            "SELECT COUNT(*) FROM target_customers"
        ).fetchone()[0]
    finally:
        connection.close()

    print(f"Wrote {count:,} transactions for {customer_count:,} customers to {output}")
    if args.csv_output:
        print(f"Wrote CSV copy to {args.csv_output.resolve()}")


if __name__ == "__main__":
    main()
