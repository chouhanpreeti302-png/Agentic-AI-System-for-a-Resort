import json
from typing import Any, Dict, List, Optional

from app.config import settings

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None


class LLMClient:
    def __init__(self) -> None:
        self.client = None
        self.last_error: Optional[str] = None
        if OpenAI and settings.openai_api_key:
            self.client = OpenAI(api_key=settings.openai_api_key)
        else:
            self.last_error = "OpenAI client not initialized (missing key or library)."

    @property
    def available(self) -> bool:
        return self.client is not None

    def classify_department(self, message: str) -> Optional[str]:
        if not self.available:
            return None
        try:
            response = self.client.chat.completions.create(
                model=settings.openai_model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Classify the guest message into exactly one label: receptionist, restaurant, room_service. "
                            "restaurant = any food/drink/menu/order/billing intent (coffee, tea, juice, snacks, meals). "
                            "room_service = cleaning, laundry, towels, toiletries, toothpaste, toothbrush, pillow, blankets, amenities. "
                            "receptionist = general FAQs (check-in/out, gym, spa, pool) or room availability. "
                            "Return only the label."
                        ),
                    },
                    {"role": "user", "content": message},
                ],
                temperature=0,
                max_tokens=4,
            )
            self.last_request_id = getattr(response, "id", None) or getattr(response, "request_id", None) or (
                getattr(response, "http_response", None)
                and getattr(response.http_response, "headers", {}).get("x-request-id")
            )
            label = response.choices[0].message.content.strip().lower()
            return label.split()[0]
        except Exception as exc:
            self.last_error = str(exc)
            return None

    def extract_order(self, message: str) -> Optional[Dict[str, Any]]:
        if not self.available:
            return None
        try:
            response = self.client.chat.completions.create(
                model=settings.openai_model,
                response_format={"type": "json_object"},
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Extract restaurant order details. "
                            "Return JSON with fields: items (list of {name, quantity}), special_notes (string, optional)."
                        ),
                    },
                    {"role": "user", "content": message},
                ],
                temperature=0,
            )
            self.last_request_id = getattr(response, "id", None) or getattr(response, "request_id", None) or (
                getattr(response, "http_response", None)
                and getattr(response.http_response, "headers", {}).get("x-request-id")
            )
            return json.loads(response.choices[0].message.content)
        except Exception as exc:
            self.last_error = str(exc)
            return None

    def extract_room_service(self, message: str) -> Optional[Dict[str, Any]]:
        if not self.available:
            return None
        try:
            response = self.client.chat.completions.create(
                model=settings.openai_model,
                response_format={"type": "json_object"},
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Extract room service request. "
                            "Return JSON with fields: request_type (cleaning, laundry, toiletries, toothpaste, toothbrush, pillow, blankets, towels), "
                            "and quantity if applicable."
                        ),
                    },
                    {"role": "user", "content": message},
                ],
                temperature=0,
            )
            self.last_request_id = getattr(response, "id", None) or getattr(response, "request_id", None) or (
                getattr(response, "http_response", None)
                and getattr(response.http_response, "headers", {}).get("x-request-id")
            )
            return json.loads(response.choices[0].message.content)
        except Exception as exc:
            self.last_error = str(exc)
            return None

    def health(self) -> Dict[str, Any]:
        """
        Return a simple health payload without raising exceptions.
        """
        return {
            "available": self.available,
            "model": settings.openai_model,
            "last_request_id": getattr(self, "last_request_id", None),
            "last_error": self.last_error,
        }

    def detect_intents(self, message: str) -> Optional[Dict[str, bool]]:
        """
        Ask the LLM to identify which departments are relevant in the message.
        Returns a dict like {"restaurant": bool, "room_service": bool, "receptionist": bool}.
        """
        if not self.available:
            return None
        try:
            response = self.client.chat.completions.create(
                model=settings.openai_model,
                response_format={"type": "json_object"},
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Given a guest message, indicate which departments are needed. "
                            "Return JSON with booleans: restaurant, room_service, receptionist. "
                            "restaurant for food/menu/orders/billing; room_service for cleaning/laundry/amenities "
                            "(towels, toothpaste, toothbrush, pillow, blankets); receptionist for general FAQs or room availability. "
                            "Set true for all that apply; false otherwise."
                        ),
                    },
                    {"role": "user", "content": message},
                ],
                temperature=0,
            )
            self.last_request_id = getattr(response, "id", None) or getattr(response, "request_id", None) or (
                getattr(response, "http_response", None)
                and getattr(response.http_response, "headers", {}).get("x-request-id")
            )
            return json.loads(response.choices[0].message.content)
        except Exception as exc:
            self.last_error = str(exc)
            return None
