import json
import os
from pathlib import Path
from uuid import uuid4
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.agents.llm_client import LLMClient
from app.agents.orchestrator import AgentOrchestrator
from app.database import Base, SessionLocal, engine, get_db
from app.models import ConversationMessage, RestaurantOrder, Room, RoomServiceRequest
from app.schemas import (
    ChatRequest,
    ChatResponse,
    DashboardResponse,
    RestaurantOrderOut,
    RoomServiceRequestOut,
    StatusUpdate,
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
            for number in ["101", "102", "201", "202", "301", "302"]:
                db.add(Room(room_number=number, available=True))
            db.commit()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/menu")
def get_menu():
    return {"menu": MENU}


@app.post("/api/chat", response_model=ChatResponse)
def chat(payload: ChatRequest, db: Session = Depends(get_db)):
    conversation_id = payload.conversation_id or str(uuid4())
    orchestrator = AgentOrchestrator(db)
    label = orchestrator.llm.classify_department(payload.message) if orchestrator.llm else None
    result = orchestrator.handle(payload.message, payload.room_number, conversation_id)
    final_department = result.department
    if final_department == "multi":
        final_department = "multi (restaurant + room_service)"
    logger.info(
        "LLM route=%s -> final=%s room=%s conversation=%s",
        label,
        final_department,
        payload.room_number,
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


@app.get("/api/dashboard", response_model=DashboardResponse)
def dashboard_data(db: Session = Depends(get_db)):
    orders = db.query(RestaurantOrder).order_by(RestaurantOrder.created_at.desc()).all()
    room_requests = db.query(RoomServiceRequest).order_by(RoomServiceRequest.created_at.desc()).all()
    return DashboardResponse(
        restaurant_orders=[_serialize_order(o) for o in orders],
        room_service_requests=[_serialize_room_request(r) for r in room_requests],
    )


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard():
    static_path = Path(__file__).resolve().parent / "static" / "dashboard.html"
    return FileResponse(static_path)


@app.get("/")
def root():
    # Send users to the chat interface by default.
    return RedirectResponse(url="/chat")


@app.get("/chat", response_class=HTMLResponse)
def chat_page():
    static_path = Path(__file__).resolve().parent / "static" / "chat.html"
    return FileResponse(static_path)


def _serialize_order(order: RestaurantOrder) -> dict:
    items = json.loads(order.items_json) if order.items_json else []
    return {
        "id": order.id,
        "room_number": order.room_number,
        "items": items,
        "total_amount": order.total_amount,
        "status": order.status,
        "created_at": order.created_at,
    }


def _serialize_room_request(request: RoomServiceRequest) -> dict:
    return {
        "id": request.id,
        "room_number": request.room_number,
        "request_type": request.request_type,
        "status": request.status,
        "created_at": request.created_at,
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
