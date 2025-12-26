from sqlalchemy.orm import Session

from app.agents.types import AgentResult
from app.data.resort_info import RECEPTION_INFO
from app.models import Room


class ReceptionistAgent:
    def __init__(self, db: Session) -> None:
        self.db = db

    def handle(self, message: str, room_number: str | None, conversation_id: str) -> AgentResult:
        text = message.lower()
        reply = self._route_reception(text)
        return AgentResult(reply=reply, department="receptionist")

    def _route_reception(self, text: str) -> str:
        if "check-in" in text or "check in" in text:
            return f"Check-in time is {RECEPTION_INFO['check_in_time']}."
        if "check-out" in text or "check out" in text:
            return f"Check-out time is {RECEPTION_INFO['check_out_time']}."
        if "gym" in text:
            return RECEPTION_INFO["facilities"]["gym"]
        if "spa" in text:
            return RECEPTION_INFO["facilities"]["spa"]
        if "pool" in text or "swimming" in text:
            return RECEPTION_INFO["facilities"]["swimming_pool"]
        if "available" in text or "availability" in text or "room" in text:
            return self._room_availability()
        return (
            "Hi there! I can help with check-in/out times, facilities (gym, spa, pool), and room availability. "
            "Let me know what you need."
        )

    def _room_availability(self) -> str:
        rooms = self.db.query(Room).filter(Room.available.is_(True)).all()
        if not rooms:
            return "All rooms are currently occupied. I can waitlist your request."
        room_numbers = ", ".join(r.room_number for r in rooms)
        return f"Available rooms right now: {room_numbers}. Would you like me to reserve one?"
