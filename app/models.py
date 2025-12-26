from datetime import datetime
from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String, Text

from app.database import Base


class ConversationMessage(Base):
    __tablename__ = "conversation_messages"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(String, index=True)
    sender = Column(String, index=True)
    department = Column(String, index=True, nullable=True)
    content = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)


class RestaurantOrder(Base):
    __tablename__ = "restaurant_orders"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(String, index=True)
    room_number = Column(String, index=True)
    items_json = Column(Text)
    total_amount = Column(Float)
    status = Column(String, default="Pending")
    created_at = Column(DateTime, default=datetime.utcnow)


class RoomServiceRequest(Base):
    __tablename__ = "room_service_requests"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(String, index=True)
    room_number = Column(String, index=True)
    request_type = Column(String)
    status = Column(String, default="Pending")
    created_at = Column(DateTime, default=datetime.utcnow)


class Room(Base):
    __tablename__ = "rooms"

    room_number = Column(String, primary_key=True, index=True)
    available = Column(Boolean, default=True)
