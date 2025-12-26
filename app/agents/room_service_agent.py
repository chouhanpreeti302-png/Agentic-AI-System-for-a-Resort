from typing import Dict, Optional
from sqlalchemy.orm import Session

from app.agents.llm_client import LLMClient
from app.agents.types import AgentResult
from app.models import RoomServiceRequest, ConversationMessage


class RoomServiceAgent:
    def __init__(self, db: Session, llm_client: LLMClient) -> None:
        self.db = db
        self.llm = llm_client

    def handle(self, message: str, room_number: str | None, conversation_id: str) -> AgentResult:
        request_payload = self._extract_request(message)
        if not request_payload:
            if room_number:
                request_payload = self._recover_request_from_history(conversation_id)
        if not request_payload:
            return AgentResult(
                reply=(
                    "I can schedule cleaning, laundry, or deliver amenities like towels, toiletries, toothpaste, pillows, "
                    "and blankets. What do you need?"
                ),
                department="room_service",
            )
        if not room_number:
            room_number = self._fallback_room_number(conversation_id)
        if not room_number:
            return AgentResult(
                reply="Please confirm your room number so I can dispatch the request.",
                department="room_service",
            )

        record = self._save_request(request_payload["request_type"], room_number, conversation_id)
        reply = (
            f"{record['request_type'].title()} request logged for room {room_number}. "
            f"Status: {record['status']}."
        )
        return AgentResult(reply=reply, department="room_service", room_service_request=record)

    def _extract_request(self, message: str) -> Optional[Dict]:
        from_llm = self.llm.extract_room_service(message) if self.llm else None
        if from_llm and from_llm.get("request_type"):
            normalized = self._normalize_request_type(from_llm["request_type"])
            if normalized:
                return {"request_type": normalized}

        parsed = self._simple_parse(message)
        if parsed:
            parsed["request_type"] = self._normalize_request_type(parsed["request_type"]) or parsed["request_type"]
        return parsed

    def _simple_parse(self, message: str) -> Optional[Dict]:
        text = message.lower()
        if "laundry" in text:
            return {"request_type": "laundry"}
        if "clean" in text or "housekeeping" in text:
            return {"request_type": "cleaning"}
        if "towel" in text or "towels" in text:
            return {"request_type": "towels"}
        for keyword in ["toiletries", "toothpaste", "toothbrush", "brush", "pillow", "blanket"]:
            if keyword in text:
                return {"request_type": keyword}
        return None

    def _normalize_request_type(self, request_type) -> Optional[str]:
        # Accept strings, dicts, lists; gracefully ignore unsupported shapes.
        if request_type is None:
            return None
        if isinstance(request_type, list):
            # take the first non-empty element
            request_type = next((x for x in request_type if x), "")
        if isinstance(request_type, dict):
            # look for a 'request_type' field or the first string value
            val = request_type.get("request_type")
            if isinstance(val, str):
                request_type = val
            else:
                request_type = next((v for v in request_type.values() if isinstance(v, str)), "")
        if not isinstance(request_type, str):
            return None
        request_type = request_type.strip()
        mapping = {
            "blanket": "blanket",
            "blankets": "blanket",
            "pillow": "pillow",
            "pillows": "pillow",
            "toiletry": "toiletries",
            "toiletries": "toiletries",
            "toothpaste": "toothpaste",
            "toothbrush": "toothbrush",
            "brush": "toothbrush",
            "laundry": "laundry",
            "clean": "cleaning",
            "cleaning": "cleaning",
            "housekeeping": "cleaning",
            "towel": "towels",
            "towels": "towels",
        }
        return mapping.get(request_type.lower())

    def _save_request(self, request_type: str, room_number: str, conversation_id: str) -> Dict:
        record = RoomServiceRequest(
            conversation_id=conversation_id,
            room_number=room_number,
            request_type=request_type,
            status="Pending",
        )
        self.db.add(record)
        self.db.commit()
        self.db.refresh(record)
        return {
            "id": record.id,
            "room_number": room_number,
            "request_type": request_type,
            "status": record.status,
            "created_at": record.created_at,
        }

    def _fallback_room_number(self, conversation_id: str) -> Optional[str]:
        """
        Reuse the last known room for this conversation to support multi-turn flows like
        \"also grab towels\" without repeating the room number.
        """
        try:
            from app.models import RestaurantOrder, RoomServiceRequest  # local import to avoid cycles

            last_request = (
                self.db.query(RoomServiceRequest)
                .filter(RoomServiceRequest.conversation_id == conversation_id)
                .order_by(RoomServiceRequest.created_at.desc())
                .first()
            )
            if last_request and last_request.room_number:
                return last_request.room_number

            last_order = (
                self.db.query(RestaurantOrder)
                .filter(RestaurantOrder.conversation_id == conversation_id)
                .order_by(RestaurantOrder.created_at.desc())
                .first()
            )
            if last_order and last_order.room_number:
                return last_order.room_number
        except Exception:
            return None
        return None

    def _recover_request_from_history(self, conversation_id: str) -> Optional[Dict]:
        """
        If the user already stated the request in a previous message and is now just giving the room number,
        recover the last request type from recent user messages.
        """
        try:
            messages = (
                self.db.query(ConversationMessage)
                .filter(ConversationMessage.conversation_id == conversation_id, ConversationMessage.sender == "user")
                .order_by(ConversationMessage.created_at.desc())
                .limit(5)
                .all()
            )
            for msg in messages:
                parsed = self._simple_parse(msg.content or "")
                if parsed:
                    parsed["request_type"] = self._normalize_request_type(parsed["request_type"]) or parsed["request_type"]
                    return parsed
        except Exception:
            return None
        return None
