from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, EmailStr


class ChatRequest(BaseModel):
    message: str
    room_number: Optional[str] = None
    conversation_id: Optional[str] = None
    user_id: Optional[str] = None


class OrderItem(BaseModel):
    name: str
    quantity: int = 1
    price: float


class RestaurantOrderOut(BaseModel):
    id: int
    display_id: Optional[str] = None
    room_number: str
    items: List[OrderItem]
    total_amount: float
    status: str
    created_at: datetime


class RoomServiceRequestOut(BaseModel):
    id: int
    display_id: Optional[str] = None
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


class UserCreate(BaseModel):
    full_name: str
    email: EmailStr
    password: str


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    id: str
    full_name: str
    email: EmailStr
    room_number: Optional[str] = None
    created_at: datetime


class AuthResponse(BaseModel):
    user: UserOut


class DashboardResponse(BaseModel):
    restaurant_orders: List[RestaurantOrderOut]
    room_service_requests: List[RoomServiceRequestOut]
    users: List[UserOut]


class UserServiceHistory(BaseModel):
    room_number: Optional[str] = None
    restaurant_orders: List[RestaurantOrderOut] = []
    room_service_requests: List[RoomServiceRequestOut] = []


class InvoiceResponse(BaseModel):
    user: UserOut
    room_number: Optional[str] = None
    restaurant_orders: List[RestaurantOrderOut] = []
    total_amount: float = 0.0


class StatusUpdate(BaseModel):
    status: str
