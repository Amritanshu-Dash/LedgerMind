"""
_04_prediction.py
-----------------
This is where the main LedgerMind model will be called later.

Right now there is no model.
So we only print what we WOULD send, and return a stub result.

When the model exists, we add the real call in ONE place below.
Do not put model code in the orchestrator.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


def call_prediction_model(analysis: Dict[str, Any], saved: Dict[str, Any]) -> Dict[str, Any]:
    """
    analysis = sense we made from the query
    saved    = what cache_store returned (query id later)

    If analysis failed, or save was skipped, orchestrator should not
    call this. This function assumes it was already a good query.
    """
    payload = {
        "unique_query_id": saved.get("unique_query_id"),
        "intent": analysis.get("intent"),
        "ticker": analysis.get("ticker"),
        "sense_for_model": analysis.get("sense_for_model"),
        "converted_query": analysis.get("converted_query"),
        "attachment_count": analysis.get("attachment_count"),
    }

    print("[PREDICTION STUB] would send this to the model:")
    for key, value in payload.items():
        print(f"  {key}: {value}")

    logger.info("Prediction stub ran for intent=%s", payload["intent"])

    # Later: result = real_model.predict(payload)
    #        return {"status": "ok", "model_result": result}

    return {
        "status": "stub",
        "sent": False,
        "payload": payload,
        "model_result": None,
    }