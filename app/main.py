import json
import os
import hashlib
from pathlib import Path
from uuid import uuid4
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from sqlalchemy.orm import Session

from app.agents.llm_client import LLMClient
from app.agents.orchestrator import AgentOrchestrator
from app.database import Base, SessionLocal, engine, get_db
from app.models import ConversationMessage, RestaurantOrder, Room, RoomServiceRequest, User
from app.schemas import (
    AuthResponse,
    ChatRequest,
    ChatResponse,
    DashboardResponse,
    RestaurantOrderOut,
    RoomServiceRequestOut,
    StatusUpdate,
    UserCreate,
    UserLogin,
    UserOut,
    UserServiceHistory,
    InvoiceResponse,
)
from app.data.menu import MENU
import logging


app = FastAPI(title="Resort Agentic System")
logger = logging.getLogger("uvicorn.error")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup_event():
    Base.metadata.create_all(bind=engine)
    _seed_rooms()


def _seed_rooms():
    with SessionLocal() as db:
        if db.query(Room).count() == 0:
            for number in range(101, 120):
                db.add(Room(room_number=str(number), available=True))
            for number in range(201, 230):
                db.add(Room(room_number=str(number), available=True))
            for number in range(301, 340):
                db.add(Room(room_number=str(number), available=True))
            db.commit()


def _hash_password(password: str) -> str:
    salt = uuid4().hex
    digest = hashlib.sha256(f"{salt}{password}".encode("utf-8")).hexdigest()
    return f"{salt}${digest}"


def _verify_password(password: str, stored: str) -> bool:
    try:
        salt, digest = stored.split("$", 1)
    except ValueError:
        return False
    candidate = hashlib.sha256(f"{salt}{password}".encode("utf-8")).hexdigest()
    return candidate == digest


def _extract_requested_room(message: str) -> str | None:
    import re

    match = re.search(r"\broom\s*(\d{3})\b", message.lower())
    if match:
        return match.group(1)
    return None


def _is_room_booking_request(message: str) -> bool:
    text = message.lower()
    keywords = [
        "book",
        "reserve",
        "room",
        "availability",
        "check in",
        "check-in",
        "available",
        "vacancy",
        "need a room",
        "looking for a room",
        "get a room",
        "want a room",
        "room for the night",
        "room tonight",
        "stay",
        "accommodation",
        "lodging",
        "room booking",
        "room reservation",
    ]
    return any(k in text for k in keywords)


def _is_billing_request(message: str) -> bool:
    text = message.lower()
    keywords = [
        "bill",
        "invoice",
        "pay",
        "payment",
        "total",
        "checkout",
        "charge",
        "settle",
    ]
    return any(k in text for k in keywords)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/menu")
def get_menu():
    return {"menu": MENU}


@app.post("/api/chat", response_model=ChatResponse)
def chat(payload: ChatRequest, db: Session = Depends(get_db)):
    conversation_id = payload.conversation_id or str(uuid4())
    user = db.query(User).filter(User.id == payload.user_id).first() if payload.user_id else None
    if user and _is_billing_request(payload.message):
        reply = "Invoice summary is in the sidebar. A staff member will assist you with the bill shortly."
        db.add(
            ConversationMessage(
                conversation_id=conversation_id,
                sender="user",
                department="receptionist",
                content=payload.message,
            )
        )
        db.add(
            ConversationMessage(
                conversation_id=conversation_id,
                sender="agent",
                department="receptionist",
                content=reply,
            )
        )
        db.commit()
        return ChatResponse(
            conversation_id=conversation_id,
            department="receptionist",
            reply=reply,
            order=None,
            room_service_request=None,
        )
    if user and not user.room_number:
        requested_room = payload.room_number or _extract_requested_room(payload.message)
        if _is_room_booking_request(payload.message) or requested_room:
            room = None
            if requested_room:
                room = (
                    db.query(Room)
                    .filter(Room.room_number == str(requested_room), Room.available.is_(True))
                    .first()
                )
                if not room:
                    requested_floor = int(str(requested_room)[0])
                    if requested_floor < 3:
                        better_room = (
                            db.query(Room)
                            .filter(Room.available.is_(True), Room.room_number.like(f"{requested_floor + 1}%"))
                            .order_by(Room.room_number.asc())
                            .first()
                        )
                        room = better_room
            if not room:
                room = db.query(Room).filter(Room.available.is_(True)).order_by(Room.room_number.asc()).first()
            if not room:
                reply = "Sorry, no rooms are available right now. Please check back later."
            else:
                room.available = False
                user.room_number = room.room_number
                db.commit()
                if requested_room and str(requested_room) != room.room_number:
                    reply = (
                        f"That room is already booked. I've allocated you a better room: {room.room_number}."
                    )
                else:
                    reply = f"Room {room.room_number} is booked for you. You can now use the chat for requests."
        else:
            reply = "Please book a room first so I can assist. Say 'book a room' to get started."

        db.add(
            ConversationMessage(
                conversation_id=conversation_id,
                sender="user",
                department="receptionist",
                content=payload.message,
            )
        )
        db.add(
            ConversationMessage(
                conversation_id=conversation_id,
                sender="agent",
                department="receptionist",
                content=reply,
            )
        )
        db.commit()

        return ChatResponse(
            conversation_id=conversation_id,
            department="receptionist",
            reply=reply,
            order=None,
            room_service_request=None,
        )

    room_number = payload.room_number or (user.room_number if user else None)
    orchestrator = AgentOrchestrator(db)
    label = orchestrator.llm.classify_department(payload.message) if orchestrator.llm else None
    result = orchestrator.handle(payload.message, room_number, conversation_id)
    final_department = result.department
    if final_department == "multi":
        final_department = "multi (restaurant + room_service)"
    logger.info(
        "LLM route=%s -> final=%s room=%s conversation=%s",
        label,
        final_department,
        room_number,
        conversation_id,
    )

    db.add(
        ConversationMessage(
            conversation_id=conversation_id,
            sender="user",
            department=result.department,
            content=payload.message,
        )
    )
    db.add(
        ConversationMessage(
            conversation_id=conversation_id,
            sender="agent",
            department=result.department,
            content=result.reply,
        )
    )
    db.commit()

    order_out = RestaurantOrderOut(**result.order) if result.order else None
    room_service_out = RoomServiceRequestOut(**result.room_service_request) if result.room_service_request else None

    return ChatResponse(
        conversation_id=conversation_id,
        department=result.department,
        reply=result.reply,
        order=order_out,
        room_service_request=room_service_out,
    )


@app.post("/api/register", response_model=AuthResponse)
def register_user(payload: UserCreate, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.email == payload.email.lower()).first()
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered.")
    user = User(
        id=str(uuid4()),
        full_name=payload.full_name.strip(),
        email=payload.email.lower(),
        password_hash=_hash_password(payload.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return AuthResponse(user=_serialize_user(user))


@app.post("/api/login", response_model=AuthResponse)
def login_user(payload: UserLogin, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email.lower()).first()
    if not user or not _verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password.")
    return AuthResponse(user=_serialize_user(user))


@app.delete("/api/users/{user_id}")
def delete_user(user_id: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    if user.room_number:
        room = db.query(Room).filter(Room.room_number == user.room_number).first()
        if room:
            room.available = True
        db.query(RestaurantOrder).filter(RestaurantOrder.room_number == user.room_number).delete()
        db.query(RoomServiceRequest).filter(RoomServiceRequest.room_number == user.room_number).delete()
    db.delete(user)
    db.commit()
    return {"status": "deleted"}


@app.get("/api/users/{user_id}/history", response_model=UserServiceHistory)
def user_history(user_id: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    if not user.room_number:
        return UserServiceHistory(room_number=None, restaurant_orders=[], room_service_requests=[])

    orders = (
        db.query(RestaurantOrder)
        .filter(RestaurantOrder.room_number == user.room_number)
        .order_by(RestaurantOrder.created_at.desc())
        .all()
    )
    room_services = (
        db.query(RoomServiceRequest)
        .filter(RoomServiceRequest.room_number == user.room_number)
        .order_by(RoomServiceRequest.created_at.desc())
        .all()
    )
    return UserServiceHistory(
        room_number=user.room_number,
        restaurant_orders=[_serialize_order(o) for o in orders],
        room_service_requests=[_serialize_room_request(r) for r in room_services],
    )


@app.get("/api/users/{user_id}/invoice", response_model=InvoiceResponse)
def user_invoice(user_id: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    orders = []
    total = 0.0
    if user.room_number:
        orders = (
            db.query(RestaurantOrder)
            .filter(RestaurantOrder.room_number == user.room_number)
            .order_by(RestaurantOrder.created_at.desc())
            .all()
        )
        total = sum(o.total_amount or 0 for o in orders)
    return InvoiceResponse(
        user=_serialize_user(user),
        room_number=user.room_number,
        restaurant_orders=[_serialize_order(o) for o in orders],
        total_amount=total,
    )


@app.get("/api/dashboard", response_model=DashboardResponse)
def dashboard_data(db: Session = Depends(get_db)):
    orders = db.query(RestaurantOrder).order_by(RestaurantOrder.created_at.desc()).all()
    room_requests = db.query(RoomServiceRequest).order_by(RoomServiceRequest.created_at.desc()).all()
    users = db.query(User).order_by(User.created_at.desc()).all()
    return DashboardResponse(
        restaurant_orders=[_serialize_order(o) for o in orders],
        room_service_requests=[_serialize_room_request(r) for r in room_requests],
        users=[_serialize_user(u) for u in users],
    )


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard():
    static_path = Path(__file__).resolve().parent / "static" / "dashboard.html"
    return FileResponse(static_path)


@app.get("/", response_class=HTMLResponse)
def landing_page():
    static_path = Path(__file__).resolve().parent / "static" / "landing.html"
    return FileResponse(static_path)


@app.get("/landing", response_class=HTMLResponse)
def landing_page_alias():
    static_path = Path(__file__).resolve().parent / "static" / "landing.html"
    return FileResponse(static_path)


@app.get("/chat", response_class=HTMLResponse)
def chat_page():
    static_path = Path(__file__).resolve().parent / "static" / "chat.html"
    return FileResponse(static_path)


@app.get("/login", response_class=HTMLResponse)
def login_page():
    static_path = Path(__file__).resolve().parent / "static" / "login.html"
    return FileResponse(static_path)


@app.get("/register", response_class=HTMLResponse)
def register_page():
    static_path = Path(__file__).resolve().parent / "static" / "register.html"
    return FileResponse(static_path)


def _serialize_order(order: RestaurantOrder) -> dict:
    items = json.loads(order.items_json) if order.items_json else []
    return {
        "id": order.id,
        "display_id": order.display_id,
        "room_number": order.room_number,
        "items": items,
        "total_amount": order.total_amount,
        "status": order.status,
        "created_at": order.created_at,
    }


def _serialize_room_request(request: RoomServiceRequest) -> dict:
    return {
        "id": request.id,
        "display_id": request.display_id,
        "room_number": request.room_number,
        "request_type": request.request_type,
        "status": request.status,
        "created_at": request.created_at,
    }


def _serialize_user(user: User) -> dict:
    return {
        "id": user.id,
        "full_name": user.full_name,
        "email": user.email,
        "room_number": user.room_number,
        "created_at": user.created_at,
    }


@app.get("/api/llm-health")
def llm_health(message: str = "Restaurant or room service?"):
    key = os.getenv("OPENAI_API_KEY")
    client = LLMClient()
    label = None
    error = None
    model_name = None
    if client.available:
        try:
            label = client.classify_department(message)
        except Exception as exc:
            error = str(exc)
        model_name = getattr(client.client, "model", None) or os.getenv("OPENAI_MODEL")
    else:
        error = client.last_error

    return {
        "has_OPENAI_API_KEY": bool(key),
        "model": model_name,
        "label": label,
        "available": client.available,
        "last_request_id": getattr(client, "last_request_id", None),
        "last_error": error or client.last_error,
        "cwd": os.getcwd(),
    }


def _validate_status(status: str) -> str:
    allowed = {"Pending", "In Progress", "Completed"}
    if status not in allowed:
        raise ValueError(f"Status must be one of: {', '.join(allowed)}")
    return status


@app.post("/api/orders/{order_id}/status")
def update_order_status(order_id: int, payload: StatusUpdate, db: Session = Depends(get_db)):
    status = _validate_status(payload.status)
    order = db.query(RestaurantOrder).filter(RestaurantOrder.id == order_id).first()
    if not order:
        return {"updated": False, "reason": "Order not found"}
    order.status = status
    db.add(order)
    db.commit()
    db.refresh(order)
    return {"updated": True, "order": _serialize_order(order)}


@app.post("/api/room-service/{request_id}/status")
def update_room_service_status(request_id: int, payload: StatusUpdate, db: Session = Depends(get_db)):
    status = _validate_status(payload.status)
    req = db.query(RoomServiceRequest).filter(RoomServiceRequest.id == request_id).first()
    if not req:
        return {"updated": False, "reason": "Request not found"}
    req.status = status
    db.add(req)
    db.commit()
    db.refresh(req)
    return {"updated": True, "room_service_request": _serialize_room_request(req)}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
