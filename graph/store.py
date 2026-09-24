"""Unified GraphStore interface with TigerGraph and local DuckDB+NetworkX implementations."""

from __future__ import annotations

import os
import json
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

import duckdb
import networkx as nx
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

try:
    import pyTigerGraph as tg
except ImportError:
    tg = None


class GraphStore(ABC):
    """Abstract interface for graph and vector fraud investigations."""

    @abstractmethod
    def card_baseline(self, card_id: str, before_ts: str) -> dict[str, Any]:
        """Historical baseline of amounts, products, channels, regions, devices, emails before before_ts."""
        pass

    @abstractmethod
    def card_window(self, card_id: str, start_ts: str, end_ts: str) -> list[dict[str, Any]]:
        """Transactions on card within [start_ts, end_ts]."""
        pass

    @abstractmethod
    def get_transaction(self, txn_id: str) -> dict[str, Any]:
        """Fetch exact transaction record by ID."""
        pass

    @abstractmethod
    def device_neighbors(self, device_id: str, window_days: int = 30) -> dict[str, Any]:
        """Cards, customers, transactions, and closed cases linked to this device."""
        pass

    @abstractmethod
    def region_neighbors(self, region: str, window_days: int = 30) -> dict[str, Any]:
        """Cards and transactions active in this billing region."""
        pass

    @abstractmethod
    def email_neighbors(self, domain: str) -> dict[str, Any]:
        """Cards and transactions sharing this recipient email domain."""
        pass

    @abstractmethod
    def similar_closed_cases(
        self,
        card_id: str,
        customer_id: str,
        device_id: str,
        region: str,
        query_text: str = "",
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """Hybrid retrieval: structured graph filters + semantic vector similarity."""
        pass

    @abstractmethod
    def detect_rings(self, trailing_days: int = 30) -> list[dict[str, Any]]:
        """Graph algorithm (Connected Components) to detect multi-card rings."""
        pass

    @abstractmethod
    def write_case(self, case_data: dict[str, Any]) -> bool:
        """Write investigated case back into graph memory. Returns True if remote write succeeded."""
        pass


class LocalGraphStore(GraphStore):
    """Deterministic, high-performance in-memory Graph & Vector store using DuckDB, NetworkX, and TF-IDF."""

    def __init__(self, data_dir: Path | str = "data"):
        self.data_dir = Path(data_dir).resolve()
        self.con = duckdb.connect()
        self._init_tables()
        self._init_vector_store()
        self._init_graph_algorithms()
        self.memory_file = self.data_dir / "local_graph_memory.json"
        self._load_local_memory()

    def _init_tables(self) -> None:
        parquet = str((self.data_dir / "transactions_trimmed.parquet").resolve()).replace("'", "''")
        identity = str((self.data_dir / "identity.csv").resolve()).replace("'", "''")
        case_pack = str((self.data_dir / "case_pack.csv").resolve()).replace("'", "''")
        history = str((self.data_dir / "closed_cases_history.csv").resolve()).replace("'", "''")

        self.con.execute(f"""
            CREATE OR REPLACE TEMP TABLE tx AS
            SELECT *, CAST(TransactionID AS VARCHAR) AS transaction_id,
                   CAST(TransactionAmt AS DOUBLE) AS amount,
                   ProductCD AS product_cd
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

            CREATE OR REPLACE TEMP TABLE enriched_tx AS
            SELECT t.*, c.card_id,
                   md5(COALESCE(i.DeviceInfo, '') || '|' || COALESCE(i.id_30, '') || '|' ||
                       COALESCE(i.id_31, '') || '|' || COALESCE(i.id_33, '')) AS device_id,
                   COALESCE(i.DeviceType, '') AS device_type,
                   COALESCE(i.DeviceInfo, '') AS device_info,
                   COALESCE(i.id_30, '') AS os,
                   COALESCE(i.id_31, '') AS browser,
                   COALESCE(i.id_33, '') AS screen,
                   COALESCE(i.id_15, '') AS id_15,
                   COALESCE(i.id_23, '') AS id_23,
                   COALESCE(i.id_34, '') AS id_34
            FROM tx t
            LEFT JOIN card_map c ON c.customer_id = t.customer_id
                AND c.card1 = CAST(t.card1 AS VARCHAR)
            LEFT JOIN read_csv_auto('{identity}', header=true) i
                ON CAST(i.TransactionID AS VARCHAR) = t.transaction_id;
        """)

    def _init_vector_store(self) -> None:
        """Index closed-case narratives, README patterns, policy rules, and FinCEN guidance."""
        rows = self.con.execute("""
            SELECT case_id, customer_id, card_id, outcome, pattern, exposure_usd, analyst_notes
            FROM history
        """).fetchall()

        self.doc_ids = []
        self.doc_texts = []
        self.doc_metadata = []

        for r in rows:
            case_id, cust, card, outcome, pattern, exp, notes = r
            text = f"Case {case_id}: {outcome} {pattern}. Card {card}, customer {cust}. Exposure ${exp:.2f}. Notes: {notes}"
            self.doc_ids.append(case_id)
            self.doc_texts.append(text)
            self.doc_metadata.append({
                "type": "closed_case",
                "case_id": case_id,
                "customer_id": cust,
                "card_id": card,
                "outcome": outcome,
                "pattern": pattern,
                "exposure_usd": float(exp or 0.0),
                "notes": notes,
            })

        # Patterns and Policy
        guidance = [
            ("POLICY-R1", "Policy R1: Weak signal verification", "If case rests on single weak signal and fraud probability < 0.70, verify with customer or step-up auth before blocking."),
            ("POLICY-R2", "Policy R2: Customer denial block", "Customer denies transaction: BLOCK_CARD and CREATE_CASE. Add FILE_REPORT if exposure > $1000 or shared device/region/ring."),
            ("POLICY-R5", "Policy R5: Card testing sequence", "Three or more small online authorizations under $5 within an hour followed by larger purchase. DECLINE_TRANSACTION and STEP_UP_AUTH. BLOCK_CARD if >$100 cleared."),
            ("POLICY-R6", "Policy R6: Shared origin ring", "Several cards show fraud from same device profile, billing region, or recipient email. CREATE_CASE, FILE_REPORT, MONITOR_CONNECTED_CARDS."),
            ("POLICY-R7", "Policy R7: Disputed recurring charge", "Disputed charge matches recurring monthly amount and merchant. CREATE_CASE, VERIFY_WITH_CUSTOMER, WARN_CUSTOMER. Do not block."),
            ("POLICY-R9", "Policy R9: Undocumented coordinated ring", "Abuse fitting no standard category across customers. CREATE_CASE, FILE_REPORT, ESCALATE_TO_ANALYST, describe pattern in narrative."),
            ("FINCEN-SAR", "FinCEN SAR Narrative Standard", "Comprehensive SAR narrative must detail who, what, when, where, how, and why. Include dates, dollar amounts, devices, cards, and regulatory basis."),
        ]
        for gid, title, body in guidance:
            self.doc_ids.append(gid)
            self.doc_texts.append(f"{title}. {body}")
            self.doc_metadata.append({"type": "guidance", "case_id": gid, "title": title, "notes": body})

        self.vectorizer = TfidfVectorizer(max_features=2500, stop_words="english")
        self.doc_matrix = self.vectorizer.fit_transform(self.doc_texts)

    def _init_graph_algorithms(self) -> None:
        """Build bipartite Card-Device and Card-Region graph for Connected Components ring detection."""
        rows = self.con.execute("""
            SELECT card_id, device_id, CAST(addr1 AS VARCHAR) AS region, R_emaildomain, ts
            FROM enriched_tx
            WHERE card_id IS NOT NULL
        """).fetchall()

        self.ring_graph = nx.Graph()
        for r in rows:
            card, dev, reg, email, ts = r
            if card:
                self.ring_graph.add_node(f"card:{card}", kind="card", card_id=card)
                if dev and dev != "d41d8cd98f00b204e9800998ecf8427e":  # not empty md5
                    self.ring_graph.add_node(f"dev:{dev}", kind="device", device_id=dev)
                    self.ring_graph.add_edge(f"card:{card}", f"dev:{dev}")
                if email:
                    self.ring_graph.add_node(f"email:{email}", kind="email", email=email)
                    self.ring_graph.add_edge(f"card:{card}", f"email:{email}")

        # Compute connected components
        self.components = list(nx.connected_components(self.ring_graph))
        self.card_to_component = {}
        for idx, comp in enumerate(self.components):
            for node in comp:
                if node.startswith("card:"):
                    self.card_to_component[node.split(":", 1)[1]] = idx

    def _load_local_memory(self) -> None:
        self.local_memory = {}
        if self.memory_file.exists():
            try:
                with open(self.memory_file, "r", encoding="utf-8") as f:
                    self.local_memory = json.load(f)
            except Exception:
                self.local_memory = {}

    def card_baseline(self, card_id: str, before_ts: str) -> dict[str, Any]:
        res = self.con.execute(f"""
            SELECT 
                count(*) AS tx_count,
                COALESCE(median(amount), 0.0) AS median_amount,
                COALESCE(quantile_cont(amount, 0.90), 0.0) AS p90_amount,
                COALESCE(max(amount), 0.0) AS max_amount,
                COALESCE(list(DISTINCT product_cd), []) AS products,
                COALESCE(list(DISTINCT channel), []) AS channels,
                COALESCE(list(DISTINCT CAST(addr1 AS VARCHAR)), []) AS regions,
                COALESCE(list(DISTINCT device_id), []) AS devices,
                COALESCE(list(DISTINCT P_emaildomain), []) AS emails
            FROM enriched_tx
            WHERE card_id = '{card_id}' AND ts < '{before_ts}'
        """).fetchone()

        return {
            "tx_count": res[0],
            "median_amount": float(res[1]),
            "p90_amount": float(res[2]),
            "max_amount": float(res[3]),
            "products": [p for p in res[4] if p],
            "channels": [c for c in res[5] if c],
            "regions": [r for r in res[6] if r],
            "devices": [d for d in res[7] if d and d != "d41d8cd98f00b204e9800998ecf8427e"],
            "emails": [e for e in res[8] if e],
        }

    def get_transaction(self, txn_id: str) -> dict[str, Any]:
        cursor = self.con.execute(f"""
            SELECT transaction_id, customer_id, card_id, ts, amount, product_cd,
                   channel, risk_score, addr1, addr2, P_emaildomain, R_emaildomain,
                   device_id, device_info, os, browser, screen, id_15, id_23, id_34,
                   c1, c2, c3, c5, c6, d1, d2, d3, d4, d10,
                   m1, m2, m3, m4, m5, m6
            FROM enriched_tx
            WHERE transaction_id = '{txn_id}'
        """)
        cols = [d[0] for d in cursor.description]
        row = cursor.fetchone()
        return dict(zip(cols, row)) if row else {}

    def card_window(self, card_id: str, start_ts: str, end_ts: str) -> list[dict[str, Any]]:
        cursor = self.con.execute(f"""
            SELECT transaction_id, customer_id, card_id, ts, amount, product_cd,
                   channel, risk_score, addr1, addr2, P_emaildomain, R_emaildomain,
                   device_id, device_info, os, browser, screen, id_15, id_23, id_34,
                   c1, c2, c3, c5, c6, d1, d2, d3, d4, d10,
                   m1, m2, m3, m4, m5, m6
            FROM enriched_tx
            WHERE card_id = '{card_id}' AND ts >= '{start_ts}' AND ts <= '{end_ts}'
            ORDER BY ts ASC
        """)
        cols = [d[0] for d in cursor.description]
        return [dict(zip(cols, row)) for row in cursor.fetchall()]

    def device_neighbors(self, device_id: str, window_days: int = 30) -> dict[str, Any]:
        if not device_id or device_id == "d41d8cd98f00b204e9800998ecf8427e":
            return {"cards": [], "customers": [], "tx_count": 0, "closed_cases": []}

        cards = self.con.execute(f"""
            SELECT DISTINCT card_id FROM enriched_tx
            WHERE device_id = '{device_id}' AND card_id IS NOT NULL
        """).fetchall()
        card_list = [c[0] for c in cards]

        customers = self.con.execute(f"""
            SELECT DISTINCT customer_id FROM enriched_tx
            WHERE device_id = '{device_id}' AND customer_id IS NOT NULL
        """).fetchall()
        cust_list = [c[0] for c in customers]

        tx_count = self.con.execute(f"""
            SELECT count(*) FROM enriched_tx WHERE device_id = '{device_id}'
        """).fetchone()[0]

        # Prior closed cases on these cards
        card_str = ", ".join(f"'{c}'" for c in card_list) if card_list else "''"
        cases = self.con.execute(f"""
            SELECT DISTINCT case_id FROM history
            WHERE card_id IN ({card_str})
        """).fetchall()
        case_list = [c[0] for c in cases]

        return {
            "cards": card_list,
            "customers": cust_list,
            "tx_count": tx_count,
            "closed_cases": case_list,
        }

    def region_neighbors(self, region: str, window_days: int = 30) -> dict[str, Any]:
        if not region:
            return {"cards": [], "customers": [], "tx_count": 0}

        cards = self.con.execute(f"""
            SELECT DISTINCT card_id FROM enriched_tx
            WHERE CAST(addr1 AS VARCHAR) = '{region}' AND card_id IS NOT NULL
        """).fetchall()
        custs = self.con.execute(f"""
            SELECT DISTINCT customer_id FROM enriched_tx
            WHERE CAST(addr1 AS VARCHAR) = '{region}' AND customer_id IS NOT NULL
        """).fetchall()
        tx_count = self.con.execute(f"""
            SELECT count(*) FROM enriched_tx WHERE CAST(addr1 AS VARCHAR) = '{region}'
        """).fetchone()[0]

        return {
            "cards": [c[0] for c in cards],
            "customers": [c[0] for c in custs],
            "tx_count": tx_count,
        }

    def email_neighbors(self, domain: str) -> dict[str, Any]:
        if not domain:
            return {"cards": [], "customers": [], "tx_count": 0}

        cards = self.con.execute(f"""
            SELECT DISTINCT card_id FROM enriched_tx
            WHERE R_emaildomain = '{domain}' AND card_id IS NOT NULL
        """).fetchall()
        return {
            "cards": [c[0] for c in cards],
            "tx_count": len(cards),
        }

    def similar_closed_cases(
        self,
        card_id: str,
        customer_id: str,
        device_id: str,
        region: str,
        query_text: str = "",
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        # 1. Structured graph connections
        structured = set()
        
        # Same card/customer
        if card_id:
            c1 = self.con.execute(f"SELECT case_id FROM history WHERE card_id = '{card_id}'").fetchall()
            for r in c1:
                structured.add(r[0])
        if customer_id:
            c2 = self.con.execute(f"SELECT case_id FROM history WHERE customer_id = '{customer_id}'").fetchall()
            for r in c2:
                structured.add(r[0])

        # Device neighbors
        if device_id and device_id != "d41d8cd98f00b204e9800998ecf8427e":
            dev_cards = self.device_neighbors(device_id)["cards"]
            if dev_cards:
                c_str = ", ".join(f"'{c}'" for c in dev_cards)
                c3 = self.con.execute(f"SELECT case_id FROM history WHERE card_id IN ({c_str})").fetchall()
                for r in c3:
                    structured.add(r[0])

        # 2. Vector search over narratives
        vector_results = []
        if query_text:
            query_vec = self.vectorizer.transform([query_text])
            sims = cosine_similarity(query_vec, self.doc_matrix)[0]
            top_indices = np.argsort(sims)[::-1][: top_k * 2]
            for idx in top_indices:
                meta = self.doc_metadata[idx]
                if meta["type"] == "closed_case" and sims[idx] > 0.15:
                    vector_results.append(meta["case_id"])

        # Combine: prioritize structured graph hits, then vector similarity hits
        ordered_ids = list(structured)
        for cid in vector_results:
            if cid not in ordered_ids:
                ordered_ids.append(cid)

        # Retrieve details
        results = []
        for cid in ordered_ids[:top_k]:
            match = [m for m in self.doc_metadata if m.get("case_id") == cid]
            if match:
                results.append(match[0])

        return results

    def detect_rings(self, trailing_days: int = 30) -> list[dict[str, Any]]:
        rings = []
        for idx, comp in enumerate(self.components):
            cards = [n.split(":", 1)[1] for n in comp if n.startswith("card:")]
            devices = [n.split(":", 1)[1] for n in comp if n.startswith("dev:")]
            if len(cards) > 1:
                rings.append({
                    "ring_id": f"RING-{idx:04d}",
                    "card_count": len(cards),
                    "cards": cards[:15],
                    "devices": devices[:5],
                })
        return rings

    def write_case(self, case_data: dict[str, Any]) -> bool:
        # In Local mode, save to data/local_graph_memory.json
        cid = case_data.get("case_id")
        if not cid:
            return False
        self.local_memory[cid] = case_data
        try:
            with open(self.memory_file, "w", encoding="utf-8") as f:
                json.dump(self.local_memory, f, indent=2)
        except Exception:
            pass
        return False  # False because remote TG write didn't execute


class TigerGraphStore(GraphStore):
    """Production TigerGraph store leveraging pyTigerGraph, GSQL queries, and MCP."""

    def __init__(
        self,
        host: str,
        graph_name: str,
        username: str,
        password: str,
        api_token: Optional[str] = None,
        data_dir: Path | str = "data",
    ):
        self.fallback = LocalGraphStore(data_dir=data_dir)
        self.host = host
        self.graph_name = graph_name
        self.username = username
        self.password = password
        self.api_token = api_token
        self.conn = None
        self._connect()

    def _connect(self) -> None:
        if not tg:
            return
        try:
            self.conn = tg.TigerGraphConnection(
                host=self.host,
                graphname=self.graph_name,
                username=self.username,
                password=self.password,
                apiToken=self.api_token,
            )
            if self.api_token:
                self.conn.apiToken = self.api_token
            else:
                self.conn.getToken()
        except Exception as e:
            self.conn = None

    def is_connected(self) -> bool:
        return self.conn is not None

    def card_baseline(self, card_id: str, before_ts: str) -> dict[str, Any]:
        if self.conn:
            try:
                res = self.conn.runInstalledQuery("card_baseline", {"card_id": card_id, "before_ts": before_ts})
                if res and len(res) > 0:
                    txns = res[0].get("Txns", [])
                    amounts = [t["attributes"]["amount"] for t in txns]
                    return {
                        "tx_count": len(txns),
                        "median_amount": float(np.median(amounts)) if amounts else 0.0,
                        "p90_amount": float(np.percentile(amounts, 90)) if amounts else 0.0,
                        "max_amount": float(max(amounts)) if amounts else 0.0,
                        "products": list(set(t["attributes"]["product_cd"] for t in txns)),
                        "channels": list(set(t["attributes"]["channel"] for t in txns)),
                        "regions": list(set(t["attributes"]["addr1"] for t in txns if t["attributes"].get("addr1"))),
                        "devices": [],
                        "emails": list(set(t["attributes"]["purchaser_email"] for t in txns if t["attributes"].get("purchaser_email"))),
                    }
            except Exception:
                pass
        return self.fallback.card_baseline(card_id, before_ts)

    def get_transaction(self, txn_id: str) -> dict[str, Any]:
        return self.fallback.get_transaction(txn_id)

    def card_window(self, card_id: str, start_ts: str, end_ts: str) -> list[dict[str, Any]]:
        if self.conn:
            try:
                res = self.conn.runInstalledQuery("card_window", {"card_id": card_id, "start_ts": start_ts, "end_ts": end_ts})
                if res and len(res) > 0:
                    return [t["attributes"] for t in res[0].get("Txns", [])]
            except Exception:
                pass
        return self.fallback.card_window(card_id, start_ts, end_ts)

    def device_neighbors(self, device_id: str, window_days: int = 30) -> dict[str, Any]:
        if self.conn:
            try:
                res = self.conn.runInstalledQuery("device_neighbors", {"device_id": device_id, "window_days": window_days})
                if res and len(res) > 0:
                    cards = [c["v_id"] for c in res[0].get("Cards", [])]
                    cases = [cc["v_id"] for cc in res[0].get("Cases", [])]
                    txns = res[0].get("Txns", [])
                    return {
                        "cards": cards,
                        "customers": [],
                        "tx_count": len(txns),
                        "closed_cases": cases,
                    }
            except Exception:
                pass
        return self.fallback.device_neighbors(device_id, window_days)

    def region_neighbors(self, region: str, window_days: int = 30) -> dict[str, Any]:
        if self.conn:
            try:
                res = self.conn.runInstalledQuery("region_neighbors", {"region": region, "window_days": window_days})
                if res and len(res) > 0:
                    cards = [c["v_id"] for c in res[0].get("Cards", [])]
                    txns = res[0].get("Txns", [])
                    return {
                        "cards": cards,
                        "customers": [],
                        "tx_count": len(txns),
                    }
            except Exception:
                pass
        return self.fallback.region_neighbors(region, window_days)

    def email_neighbors(self, domain: str) -> dict[str, Any]:
        if self.conn:
            try:
                res = self.conn.runInstalledQuery("email_neighbors", {"email_domain": domain})
                if res and len(res) > 0:
                    cards = [c["v_id"] for c in res[0].get("Cards", [])]
                    return {"cards": cards, "tx_count": len(cards)}
            except Exception:
                pass
        return self.fallback.email_neighbors(domain)

    def similar_closed_cases(
        self,
        card_id: str,
        customer_id: str,
        device_id: str,
        region: str,
        query_text: str = "",
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        return self.fallback.similar_closed_cases(card_id, customer_id, device_id, region, query_text, top_k)

    def detect_rings(self, trailing_days: int = 30) -> list[dict[str, Any]]:
        return self.fallback.detect_rings(trailing_days)

    def write_case(self, case_data: dict[str, Any]) -> bool:
        cid = case_data.get("case_id")
        self.fallback.write_case(case_data)
        if self.conn:
            try:
                params = {
                    "graph_case_id": case_data.get("graph_case_id", f"CASE-{cid}"),
                    "case_id": cid,
                    "verdict": case_data.get("verdict", "uncertain"),
                    "fraud_probability": float(case_data.get("fraud_probability", 0.5)),
                    "pattern": case_data.get("pattern", "none"),
                    "pattern_description": case_data.get("pattern_description", ""),
                    "status": case_data.get("status", "open"),
                    "exposure_usd": float(case_data.get("exposure_usd", 0.0)),
                    "summary": case_data.get("summary", ""),
                    "affected_txns": case_data.get("affected_txn_ids", []),
                    "connected_cards": case_data.get("connected_card_ids", []),
                    "connected_devices": case_data.get("connected_device_profiles", []),
                    "similar_closed": case_data.get("similar_prior_cases", []),
                }
                res = self.conn.runInstalledQuery("case_write", params)
                return True
            except Exception:
                return False
        return False


def get_graph_store(data_dir: Path | str = "data") -> GraphStore:
    """Factory creating TigerGraphStore if configured and reachable, otherwise LocalGraphStore."""
    host = os.environ.get("TIGERGRAPH_HOST", "")
    graph = os.environ.get("TIGERGRAPH_GRAPH", "FraudGraph")
    user = os.environ.get("TIGERGRAPH_USERNAME", "")
    pwd = os.environ.get("TIGERGRAPH_PASSWORD", "")
    token = os.environ.get("TIGERGRAPH_API_TOKEN")

    if host and not host.startswith("https://your-workspace") and host != "http://localhost":
        tg_store = TigerGraphStore(host, graph, user, pwd, api_token=token, data_dir=data_dir)
        if tg_store.is_connected():
            return tg_store

    return LocalGraphStore(data_dir=data_dir)
