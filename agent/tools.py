"""Deterministic graph investigation tools and features computed via GraphStore."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional
from graph.store import GraphStore


def parse_dt(ts_val: Any) -> datetime:
    if isinstance(ts_val, datetime):
        return ts_val
    s = str(ts_val).split(".")[0]
    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S")


class InvestigationToolkit:
    """Computes deterministic fraud investigation features from GraphStore and counts tool calls."""

    def __init__(self, store: GraphStore):
        self.store = store
        self.tool_calls_count = 0

    def _call(self, method_name: str, *args, **kwargs) -> Any:
        self.tool_calls_count += 1
        method = getattr(self.store, method_name)
        return method(*args, **kwargs)

    def get_baseline(self, card_id: str, flagged_ts: str) -> dict[str, Any]:
        """Compute card's historical baseline before the flagged transaction."""
        return self._call("card_baseline", card_id, str(flagged_ts))

    def get_window(self, card_id: str, flagged_ts: str, hours: int = 72) -> list[dict[str, Any]]:
        """Fetch transactions within +/- hours around flagged_ts."""
        dt = parse_dt(flagged_ts)
        start_ts = (dt - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
        end_ts = (dt + timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
        return self._call("card_window", card_id, start_ts, end_ts)

    def get_device_intelligence(self, device_id: str, flagged_tx: dict[str, Any]) -> dict[str, Any]:
        """Assess device fan-out, proxy attributes, and touched closed cases."""
        intel = {
            "device_id": device_id,
            "device_profile": "",
            "is_new": False,
            "is_proxy": False,
            "proxy_type": "",
            "fan_out_cards": 1,
            "fan_out_customers": 1,
            "connected_cards": [],
            "touched_closed_cases": [],
            "is_undocumented_ring_device": False,
        }

        dinfo = flagged_tx.get("device_info") or ""
        os_str = flagged_tx.get("os") or ""
        browser = flagged_tx.get("browser") or ""
        screen = flagged_tx.get("screen") or ""
        profile_str = f"{dinfo} | {os_str} | {browser} | {screen}".strip(" |")
        intel["device_profile"] = profile_str

        id_15 = str(flagged_tx.get("id_15") or "").lower()
        if "new" in id_15:
            intel["is_new"] = True

        id_23 = str(flagged_tx.get("id_23") or "").lower()
        if id_23 and id_23 not in ("none", "nan", ""):
            intel["is_proxy"] = True
            intel["proxy_type"] = id_23

        # Undocumented ring signature: Samsung SM-G935F, Android 7.0, Chrome, anonymous proxy
        if "sm-g935f" in dinfo.lower() and ("android" in os_str.lower() or "chrome" in browser.lower()):
            intel["is_undocumented_ring_device"] = True

        if device_id and device_id != "d41d8cd98f00b204e9800998ecf8427e":
            dev_data = self._call("device_neighbors", device_id)
            cards = dev_data.get("cards", [])
            intel["fan_out_cards"] = max(1, len(cards))
            intel["fan_out_customers"] = max(1, len(dev_data.get("customers", [])))
            intel["connected_cards"] = [c for c in cards if c != flagged_tx.get("card_id")]
            intel["touched_closed_cases"] = dev_data.get("closed_cases", [])

        return intel

    def get_region_intelligence(
        self,
        region: str,
        card_id: str,
        flagged_ts: str,
        window_txns: list[dict[str, Any]],
        baseline: dict[str, Any],
    ) -> dict[str, Any]:
        """Analyze billing region: new region check, multi-day cluster, trip vs clone."""
        intel = {
            "region": region,
            "is_new_region": False,
            "is_trip": False,
            "is_clone": False,
            "shared_other_cards": 0,
            "home_regions": baseline.get("regions", []),
        }

        if region and region not in baseline.get("regions", []):
            intel["is_new_region"] = True

            # Analyze window transactions to differentiate trip vs clone
            home_regions = set(baseline.get("regions", []))
            new_reg_txns = [t for t in window_txns if str(t.get("addr1")) == str(region)]
            home_txns = [t for t in window_txns if str(t.get("addr1")) in home_regions and str(t.get("addr1")) != str(region)]

            # Check dates of new region
            dates = set(str(t["ts"])[:10] for t in new_reg_txns if t.get("ts"))
            if len(dates) >= 2 and len(home_txns) == 0:
                intel["is_trip"] = True
            elif len(home_txns) > 0 and len(new_reg_txns) > 0:
                intel["is_clone"] = True

            reg_data = self._call("region_neighbors", region)
            other_cards = [c for c in reg_data.get("cards", []) if c != card_id]
            intel["shared_other_cards"] = len(other_cards)

        return intel

    def check_card_testing(self, window_txns: list[dict[str, Any]]) -> dict[str, Any]:
        """Detect card testing signature: 3+ tiny online authorizations (<$5) within an hour, then larger purchase."""
        online_txns = [
            t for t in window_txns
            if t.get("channel") == "online" or (t.get("product_cd") and t.get("product_cd") != "W")
        ]
        if len(online_txns) < 4:
            return {"is_card_testing": False, "tiny_txns": [], "large_txns": []}

        # Check for 3+ tiny authorizations within 60 minutes
        for i in range(len(online_txns) - 3):
            sub = online_txns[i : i + 3]
            try:
                t0 = parse_dt(sub[0]["ts"])
                t2 = parse_dt(sub[2]["ts"])
                if (t2 - t0).total_seconds() <= 3600:
                    amounts = [float(x.get("amount") or 0.0) for x in sub]
                    if all(a <= 5.0 for a in amounts):
                        # Look for subsequent larger transaction
                        subsequent = online_txns[i + 3 :]
                        large = [x for x in subsequent if float(x.get("amount") or 0.0) >= 15.0]
                        if large:
                            return {
                                "is_card_testing": True,
                                "tiny_txns": [x["transaction_id"] for x in sub],
                                "large_txns": [x["transaction_id"] for x in large],
                            }
            except Exception:
                continue

        return {"is_card_testing": False, "tiny_txns": [], "large_txns": []}

    def check_recurring(self, card_id: str, flagged_tx: dict[str, Any], baseline: dict[str, Any]) -> bool:
        """Check if flagged transaction matches monthly recurring subscription pattern (Rule R7)."""
        amt = float(flagged_tx.get("amount") or 0.0)
        pcd = flagged_tx.get("product_cd")
        flagged_ts = flagged_tx.get("ts", "")
        if not flagged_ts:
            return False

        # Look for transactions ~30 days, ~60 days, ~90 days earlier with exact same amount and product
        dt = parse_dt(flagged_ts)
        window_90d = self.store.card_window(
            card_id,
            (dt - timedelta(days=95)).strftime("%Y-%m-%d %H:%M:%S"),
            (dt - timedelta(days=25)).strftime("%Y-%m-%d %H:%M:%S"),
        )
        matches = [
            t for t in window_90d
            if abs(float(t.get("amount") or 0.0) - amt) < 0.05 and t.get("product_cd") == pcd
        ]
        return len(matches) >= 1

    def check_takeover(self, window_txns: list[dict[str, Any]], baseline: dict[str, Any]) -> bool:
        """Check for mixed channel anomalies, M-flag mismatches, and rating anomalies."""
        channels = set(t.get("channel") for t in window_txns if t.get("channel"))
        has_mixed = len(channels) > 1 and "online" in channels and "in_person" in channels

        # Check match flag mismatches M1-M6
        m_mismatches = 0
        for t in window_txns:
            for m_key in ("m1", "m2", "m3", "m4", "m5", "m6"):
                val = str(t.get(m_key) or "").lower()
                if val in ("f", "false", "0"):
                    m_mismatches += 1

        return has_mixed or m_mismatches >= 3

    def get_ring_detection(self, card_id: str, device_id: str, recipient_email: str) -> dict[str, Any]:
        """Query graph algorithm connected components and email neighbors."""
        rings = self._call("detect_rings")
        matched_ring = None
        for r in rings:
            if card_id in r.get("cards", []):
                matched_ring = r
                break

        email_data = {"cards": []}
        if recipient_email:
            email_data = self._call("email_neighbors", recipient_email)

        return {
            "in_ring": matched_ring is not None,
            "ring_details": matched_ring,
            "shared_email_cards": [c for c in email_data.get("cards", []) if c != card_id],
        }

    def get_memory(
        self,
        card_id: str,
        customer_id: str,
        device_id: str,
        region: str,
        query_text: str = "",
    ) -> list[dict[str, Any]]:
        """Retrieve similar closed cases using hybrid graph + vector search."""
        return self._call("similar_closed_cases", card_id, customer_id, device_id, region, query_text, top_k=5)
