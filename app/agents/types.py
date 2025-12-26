from dataclasses import dataclass
from typing import Optional


@dataclass
class AgentResult:
    reply: str
    department: str
    order: Optional[dict] = None
    room_service_request: Optional[dict] = None
