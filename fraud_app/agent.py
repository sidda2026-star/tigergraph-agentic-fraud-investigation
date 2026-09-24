"""Small agent facade: deterministic tools first, optional LLM narration second."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from .investigator import Investigator


class FraudAgent:
    def __init__(self, data_dir: Path):
        load_dotenv()
        self.investigator = Investigator(data_dir)
        self.llm_enabled = bool(os.getenv("LLM_API_KEY"))

    def investigate(self, case_row: dict[str, Any]) -> dict[str, Any]:
        result = self.investigator.investigate(case_row)
        if not self.llm_enabled:
            return result
        # The policy and evidence remain deterministic. A future provider adapter may
        # replace only summary/SAR wording after validating the returned JSON.
        return result

    def close(self) -> None:
        self.investigator.close()
