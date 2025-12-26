from typing import Optional
from sqlalchemy.orm import Session

from app.agents.llm_client import LLMClient
from app.agents.receptionist_agent import ReceptionistAgent
from app.agents.restaurant_agent import RestaurantAgent
from app.agents.room_service_agent import RoomServiceAgent
from app.agents.types import AgentResult
from app.data.menu import MENU
from app.models import ConversationMessage


class AgentOrchestrator:
    def __init__(self, db: Session, llm_client: Optional[LLMClient] = None) -> None:
        self.db = db
        self.llm = llm_client or LLMClient()
        self.receptionist = ReceptionistAgent(db)
        self.restaurant = RestaurantAgent(db, self.llm)
        self.room_service = RoomServiceAgent(db, self.llm)

    def route_department(self, message: str, conversation_id: Optional[str] = None) -> str:
        label = self.llm.classify_department(message)
        if label in {"receptionist", "restaurant", "room_service"}:
            return label

        text = message.lower()
        restaurant_keywords = [
            "menu",
            "order",
            "food",
            "breakfast",
            "lunch",
            "dinner",
            "bill",
            "coffee",
            "tea",
            "juice",
            "drink",
            "beverage",
            "snack",
            "pizza",
            "fries",
            "burger",
            "sandwich",
            "salad",
            "soup",
            "dessert",
            "cake",
        ]
        room_service_keywords = ["clean", "laundry", "towel", "tooth", "pillow", "blanket", "amenity"]

        if any(k in text for k in restaurant_keywords) or self._mentions_menu_item(text):
            return "restaurant"
        if any(k in text for k in room_service_keywords):
            return "room_service"
        if conversation_id:
            last = self._last_department(conversation_id)
            if last:
                return last
        return "receptionist"

    def _mentions_menu_item(self, text: str) -> bool:
        """
        Lightweight heuristic: if message includes any meaningful token from a menu item
        (e.g., "pizza", "fries", "salad"), treat it as restaurant intent. This is intentionally
        permissive so offline routing still works without the LLM.
        """
        import re

        for item in MENU:
            name = item.get("name", "").lower()
            if not name:
                continue
            if name in text:
                return True
            tokens = [t for t in re.split(r"[\s-]+", name) if len(t) > 3]
            for token in tokens:
                if re.search(rf"\\b{re.escape(token)}s?\\b", text):
                    return True
        return False

    def _last_department(self, conversation_id: str) -> Optional[str]:
        """
        Pull the most recent agent department for this conversation to keep multi-turn flows cohesive.
        """
        try:
            last_msg = (
                self.db.query(ConversationMessage)
                .filter(ConversationMessage.conversation_id == conversation_id, ConversationMessage.sender == "agent")
                .order_by(ConversationMessage.created_at.desc())
                .first()
            )
            return last_msg.department if last_msg and last_msg.department else None
        except Exception:
            return None

    def handle(self, message: str, room_number: Optional[str], conversation_id: str) -> AgentResult:
        if not room_number:
            room_number = self._extract_room_number(message)

        rest_intent, rs_intent, rec_intent = self._detect_intents(message)
        intents: list[str] = []
        if rest_intent:
            intents.append("restaurant")
        if rs_intent:
            intents.append("room_service")
        if rec_intent:
            intents.append("receptionist")

        if len(intents) > 1:
            return self._handle_multi(intents, message, room_number, conversation_id)

        # Prefer intent detection outcome if only one is positive.
        if rest_intent and not rs_intent:
            return self.restaurant.handle(message, room_number, conversation_id)
        if rs_intent and not rest_intent:
            return self.room_service.handle(message, room_number, conversation_id)
        if rec_intent and not rest_intent and not rs_intent:
            return self.receptionist.handle(message, room_number, conversation_id)

        department = self.route_department(message, conversation_id)

        if department == "restaurant":
            return self.restaurant.handle(message, room_number, conversation_id)
        if department == "room_service":
            return self.room_service.handle(message, room_number, conversation_id)
        return self.receptionist.handle(message, room_number, conversation_id)

    def _extract_room_number(self, message: str) -> Optional[str]:
        """
        Parse a room number from free text like "room 104".
        """
        import re

        match = re.search(r"\broom\s*(\d{1,4})\b", message.lower())
        if match:
            return match.group(1)
        # If a lone 3-4 digit number exists, assume it's the room.
        numbers = re.findall(r"\b(\d{3,4})\b", message)
        if len(numbers) == 1:
            return numbers[0]
        return None

    def _detect_intents(self, message: str) -> tuple[bool, bool, bool]:
        """
        Detect restaurant / room_service / receptionist intents.
        Prefer LLM multi-intent detection; fallback to heuristics.
        """
        intent_llm = self.llm.detect_intents(message) if self.llm and self.llm.available else None
        if intent_llm:
            return (
                bool(intent_llm.get("restaurant")),
                bool(intent_llm.get("room_service")),
                bool(intent_llm.get("receptionist")),
            )

        text = message.lower()
        rest = self._mentions_menu_item(text) or any(
            kw in text
            for kw in [
                "food",
                "order",
                "menu",
                "coffee",
                "tea",
                "juice",
                "drink",
                "snack",
                "breakfast",
                "lunch",
                "dinner",
                "restaurant",
                "pizza",
                "fries",
                "burger",
                "sandwich",
                "salad",
                "soup",
                "dessert",
                "cake",
            ]
        )
        rs = any(
            kw in text
            for kw in [
                "clean",
                "laundry",
                "towel",
                "tooth",
                "brush",
                "pillow",
                "blanket",
                "amenity",
                "toiletries",
                "toothpaste",
                "toothbrush",
                "housekeeping",
                "room service",
            ]
        )
        rec = any(
            kw in text
            for kw in [
                "check-in",
                "check in",
                "check-out",
                "check out",
                "gym",
                "spa",
                "pool",
                "availability",
                "available",
                "room availability",
            ]
        ) or (not rest and not rs)
        return rest, rs, rec

    def _handle_multi(
        self, intents: list[str], message: str, room_number: Optional[str], conversation_id: str
    ) -> AgentResult:
        replies: list[str] = []
        order_payload = None
        rs_payload = None

        for intent in intents:
            try:
                if intent == "restaurant":
                    res = self.restaurant.handle(message, room_number, conversation_id)
                    replies.append(res.reply)
                    order_payload = order_payload or res.order
                elif intent == "room_service":
                    res = self.room_service.handle(message, room_number, conversation_id)
                    replies.append(res.reply)
                    rs_payload = rs_payload or res.room_service_request
                elif intent == "receptionist":
                    res = self.receptionist.handle(message, room_number, conversation_id)
                    replies.append(res.reply)
            except Exception:
                continue

        combined_reply = "\n".join(replies) if replies else "Request received."
        return AgentResult(
            reply=combined_reply,
            department="multi",
            order=order_payload,
            room_service_request=rs_payload,
        )
