from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel


class ChatRequest(BaseModel):
    message: str
    room_number: Optional[str] = None
    conversation_id: Optional[str] = None


class OrderItem(BaseModel):
    name: str
    quantity: int = 1
    price: float


class RestaurantOrderOut(BaseModel):
    id: int
    room_number: str
    items: List[OrderItem]
    total_amount: float
    status: str
    created_at: datetime


class RoomServiceRequestOut(BaseModel):
    id: int
    room_number: str
    request_type: str
    status: str
    created_at: datetime


class ChatResponse(BaseModel):
    conversation_id: str
    department: str
    reply: str
    order: Optional[RestaurantOrderOut] = None
    room_service_request: Optional[RoomServiceRequestOut] = None


class DashboardResponse(BaseModel):
    restaurant_orders: List[RestaurantOrderOut]
    room_service_requests: List[RoomServiceRequestOut]


class StatusUpdate(BaseModel):
    status: str
