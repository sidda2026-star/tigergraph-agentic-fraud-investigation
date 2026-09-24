"""Install the Phase 2 schema and load generated graph CSVs into TigerGraph."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import pyTigerGraph as tg
from dotenv import load_dotenv


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graph-input-dir", type=Path, default=Path("data/graph"))
    parser.add_argument("--schema", type=Path, default=Path("tigergraph/schema.gsql"))
    parser.add_argument("--loading", type=Path, default=Path("tigergraph/loading.gsql"))
    parser.add_argument("--queries", type=Path, default=Path("tigergraph/queries.gsql"))
    parser.add_argument("--skip-schema", action="store_true")
    return parser.parse_args()


def required(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise SystemExit(f"Missing {name}; set it in .env or the environment.")
    return value


def main() -> None:
    args = parse_args()
    load_dotenv()
    host = required("TIGERGRAPH_HOST")
    graph = required("TIGERGRAPH_GRAPH")
    username = required("TIGERGRAPH_USERNAME")
    password = required("TIGERGRAPH_PASSWORD")
    token = os.getenv("TIGERGRAPH_API_TOKEN")
    connection = tg.TigerGraphConnection(
        host=host,
        graphname=graph,
        username=username,
        password=password,
        apiToken=token,
    )
    if not args.skip_schema:
        connection.gsql(args.schema.read_text(encoding="utf-8"))
    connection.gsql(args.loading.read_text(encoding="utf-8"))
    connection.gsql(args.queries.read_text(encoding="utf-8"))
    for csv_path in sorted(args.graph_input_dir.glob("*.csv")):
        connection.uploadFile(str(csv_path), fileTag=csv_path.name)
    print(f"Installed schema, loading job, and queries on {host}/{graph}")


if __name__ == "__main__":
    main()