import json
import re
from uuid import uuid4
from typing import Dict, List, Optional
from sqlalchemy.orm import Session

from app.agents.llm_client import LLMClient
from app.agents.types import AgentResult
from app.data.menu import MENU, FALLBACK_MENU
from app.models import RestaurantOrder, ConversationMessage


class RestaurantAgent:
    def __init__(self, db: Session, llm_client: LLMClient) -> None:
        self.db = db
        self.llm = llm_client
        # Combine parsed menu with fallback items so we still understand common dishes if the XLSX is missing entries.
        self.menu_lookup = {}
        for item in [*MENU, *FALLBACK_MENU]:
            name = item.get("name")
            if name and name.lower() not in self.menu_lookup:
                self.menu_lookup[name.lower()] = item

    def handle(self, message: str, room_number: str | None, conversation_id: str) -> AgentResult:
        text = message.lower()
        if "menu" in text or "options" in text:
            return AgentResult(reply=self._menu_text(), department="restaurant")

        order_payload, needs_qty_confirm = self._extract_order(message)
        if not order_payload or not order_payload.get("items"):
            if room_number:
                order_payload, needs_qty_confirm = self._recover_order_from_history(conversation_id)
        if not order_payload or not order_payload.get("items"):
            return AgentResult(
                reply="I can place your food order. Tell me items and quantities or ask for the menu.",
                department="restaurant",
            )

        if needs_qty_confirm:
            items = ", ".join(f"1x {i['name']}" for i in order_payload["items"])
            return AgentResult(
                reply=f"I can place this order: {items}. Confirm quantities or adjust?",
                department="restaurant",
            )

        if not room_number:
            room_number = self._fallback_room_number(conversation_id)
        if not room_number:
            return AgentResult(
                reply="Please share your room number so I can place the order.",
                department="restaurant",
            )

        order = self._save_order(order_payload["items"], room_number, conversation_id)
        reply = (
            f"Order placed for room {room_number}. Total is ₹{order['total_amount']:.2f}. "
            "Anything else you'd like to add?"
        )
        return AgentResult(reply=reply, department="restaurant", order=order)

    def _extract_order(self, message: str) -> tuple[Optional[Dict], bool]:
        from_llm = self.llm.extract_order(message) if self.llm else None
        if from_llm and from_llm.get("items"):
            return from_llm, False
        return self._simple_parse(message)

    def _simple_parse(self, message: str) -> tuple[Optional[Dict], bool]:
        text = message.lower()
        items: List[Dict] = []
        for item in self.menu_lookup.values():
            if self._matches_item(text, item["name"]):
                quantity = self._find_quantity(text, item["name"])
                items.append({"name": item["name"], "quantity": quantity})
        # Only prompt for confirmation when multiple items lack explicit quantities.
        needs_qty_confirm = len(items) > 1 and not self._has_explicit_quantity(text)
        return ({"items": items} if items else None, needs_qty_confirm)

    def _matches_item(self, text: str, item_name: str) -> bool:
        """
        Quick heuristic match: full name or any meaningful token from the dish name.
        Helps offline parsing when users mention short forms like "pizza" or "fries".
        """
        name_lower = item_name.lower()
        if name_lower in text:
            return True

        # Split on whitespace or hyphens and match any meaningful token (plural-insensitive).
        tokens = [token for token in re.split(r"[\s-]+", name_lower) if len(token) > 3]
        for token in tokens:
            if re.search(rf"\b{re.escape(token)}s?\b", text):
                return True
        return False

    def _find_quantity(self, text: str, item_name: str) -> int:
        """
        Pull quantity near the item name (e.g., '2 pizzas', 'coffee x3').
        Falls back to the first number/word seen in the message, defaults to 1.
        """
        number_words = {
            "one": 1,
            "two": 2,
            "three": 3,
            "four": 4,
            "five": 5,
        }
        name_lower = item_name.lower()
        escaped_name = re.escape(name_lower)

        patterns = [
            rf"(?P<num>\d+)\s*(?:x\s*)?{escaped_name}",
            rf"{escaped_name}\s*(?:x\s*)?(?P<num>\d+)",
            rf"(?P<word>{'|'.join(number_words.keys())})\s+{escaped_name}",
            rf"{escaped_name}\s+(?P<word>{'|'.join(number_words.keys())})",
        ]

        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                value = match.groupdict().get("num") or match.groupdict().get("word")
                return self._coerce_quantity(value)

        # If nothing item-specific was found, fall back to default quantity.
        for word, qty in number_words.items():
            if word in text:
                return qty
        return 1

    def _has_explicit_quantity(self, text: str) -> bool:
        """
        Detect whether the user provided any numeric hint (1-20 or number words) to avoid auto-assuming quantities.
        Ignore larger numbers to avoid misreading room numbers as quantities.
        """
        number_words = ["one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"]
        if any(w in text for w in number_words):
            return True
        for match in re.finditer(r"\d+", text):
            try:
                val = int(match.group())
                if 1 <= val <= 20:
                    return True
            except ValueError:
                continue
        return False

    def _menu_text(self) -> str:
        items = [f"- {i['name']} (₹{i.get('price', 0):.2f})" for i in self.menu_lookup.values()]
        return "Here is the menu:\n" + "\n".join(items)

    def _save_order(self, items: List[Dict], room_number: str, conversation_id: str) -> Dict:
        priced_items: List[Dict] = []
        total = 0.0
        for entry in items:
            menu_item = self.menu_lookup.get(entry["name"].lower())
            price = menu_item["price"] if menu_item else 0.0
            quantity = self._coerce_quantity(entry.get("quantity", 1))
            priced_items.append({"name": entry["name"], "quantity": quantity, "price": price})
            total += price * quantity

        record = RestaurantOrder(
            conversation_id=conversation_id,
            room_number=room_number,
            items_json=json.dumps(priced_items),
            total_amount=total,
            status="Pending",
            display_id=None,
        )
        self.db.add(record)
        if not record.display_id:
            record.display_id = f"RES-{room_number}-{uuid4().hex[:6].upper()}"
        self.db.commit()
        self.db.refresh(record)

        return {
            "id": record.id,
            "display_id": record.display_id,
            "room_number": room_number,
            "items": priced_items,
            "total_amount": total,
            "status": record.status,
            "created_at": record.created_at,
        }

    def _coerce_quantity(self, raw: object) -> int:
        """
        Convert LLM/user-provided quantities into a safe positive int.
        Defaults to 1 for invalid, zero, or negative inputs.
        """
        number_words = {
            "one": 1,
            "two": 2,
            "three": 3,
            "four": 4,
            "five": 5,
        }
        if isinstance(raw, (int, float)) and raw > 0:
            return min(int(raw), 20)

        if isinstance(raw, str):
            cleaned = raw.strip().lower()
            if cleaned.isdigit():
                val = int(cleaned)
                return val if 0 < val <= 20 else 1
            if cleaned in number_words:
                return number_words[cleaned]
            digits = re.search(r"\d+", cleaned)
            if digits:
                val = int(digits.group())
                return val if 0 < val <= 20 else 1

        return 1

    def _fallback_room_number(self, conversation_id: str) -> Optional[str]:
        """
        Reuse the last known room for this conversation to support multi-turn flows like
        \"add fries\" without repeating the room number.
        """
        try:
            from app.models import RestaurantOrder, RoomServiceRequest  # local import to avoid cycles

            last_order = (
                self.db.query(RestaurantOrder)
                .filter(RestaurantOrder.conversation_id == conversation_id)
                .order_by(RestaurantOrder.created_at.desc())
                .first()
            )
            if last_order and last_order.room_number:
                return last_order.room_number

            last_request = (
                self.db.query(RoomServiceRequest)
                .filter(RoomServiceRequest.conversation_id == conversation_id)
                .order_by(RoomServiceRequest.created_at.desc())
                .first()
            )
            if last_request and last_request.room_number:
                return last_request.room_number
        except Exception:
            return None
        return None

    def _recover_order_from_history(self, conversation_id: str) -> tuple[Optional[Dict], bool]:
        """
        If the user already specified items in a previous message and is now just providing the room number,
        recover the last order from recent user messages.
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
                parsed, needs_confirm = self._simple_parse(msg.content or "")
                if parsed and parsed.get("items"):
                    return parsed, needs_confirm
        except Exception:
            return None, False
        return None, False
