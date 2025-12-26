# Resort Agentic AI System

Chat-based multi-agent system for a resort with Receptionist, Restaurant, and Room Service agents. Routes guest requests, calls tools, persists data to SQLite, and exposes a lightweight dashboard.

## Features
- Single `/api/chat` endpoint for multi-turn conversations with routing to receptionist, restaurant, or room service agents.
- Optional OpenAI-powered intent parsing and extraction with rule-based fallback for offline use.
- SQLite persistence for conversations, restaurant orders, and room service requests.
- Menu and resort info served from config; room availability pulled from the database.
- Dashboard (`/dashboard`) for restaurant and room-service activity, backed by `/api/dashboard`.

## Architecture
- **FastAPI** app at `app/main.py` mounts endpoints and seeds rooms on startup.
- **Agents** (`app/agents/*`): orchestrator routes to department-specific agents; each agent performs domain logic and writes to the DB.
- **Data**: SQLite models in `app/models.py`; menu/config under `app/data`.
- **LLM client**: `app/agents/llm_client.py` uses `OPENAI_API_KEY` if set, otherwise falls back to keyword heuristics.
- **Dashboard**: static HTML/JS in `app/static/dashboard.html` pulling from `/api/dashboard`.

## Prerequisites
- Python 3.11+ recommended
- (Optional) OpenAI API key in `OPENAI_API_KEY` for richer parsing/routing

## Setup
```bash
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Create your environment file
cat > .env <<'EOF'
# Optional: OpenAI key for richer intent parsing. Leave blank to stay heuristic-only.
OPENAI_API_KEY=
OPENAI_MODEL=gpt-4o-mini
# SQLite by default; replace with Postgres URL if needed.
DATABASE_URL=sqlite:///./resort.db
DEBUG=false
EOF
```

## Running the agent server
```bash
uvicorn app.main:app --reload --port 8000
```
- API docs: http://localhost:8000/docs
- Health checks: http://localhost:8000/health and http://localhost:8000/api/llm-health
- Chat UI: http://localhost:8000/chat

## Chat endpoint
- `POST /api/chat`
- Body:
```json
{
  "message": "Can I get two coffees and a cake?",
  "room_number": "201",
  "conversation_id": "optional-uuid"
}
```
- Response contains routed department, agent reply, conversation id, and any created order/request.

Quick curl:
```bash
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"Please clean my room and leave extra towels","room_number":"102"}'
```
- Multi-department example: `{"message":"Send two pizzas and extra towels to room 201"}`.

## Dashboard
- Open http://localhost:8000/dashboard to view restaurant orders and room service requests (auto-refreshing).
- Data source: `GET /api/dashboard` (JSON with restaurant_orders and room_service_requests).

## Data model
- **RestaurantOrder**: id, room_number, items (JSON array of name/quantity/price), total_amount, status, timestamps.
- **RoomServiceRequest**: id, room_number, request_type, status, timestamps.
- **ConversationMessage**: stored per turn to maintain context (currently not replayed to the LLM, but available for extension).
- **Room**: room_number, availability; seeded on startup.

## Sample flows
1. Ask for info: `"What time is check-in and is the gym open?"` → receptionist responds from config.
2. Order food: `"Send two Margherita Pizzas to room 201"` → restaurant agent logs order, returns bill, shows on dashboard.
3. Room service: `"Need laundry pickup in 301"` → room service agent logs a request.
4. Availability: `"Do you have rooms open tonight?"` → receptionist reads from the rooms table.

## Notes
- Agents fall back to keyword heuristics when `OPENAI_API_KEY` is not set.
- Conversation IDs persist across turns if you pass the same `conversation_id` in subsequent calls.
- Update statuses directly in the DB (SQLite file at `resort.db` by default) if you need to simulate workflow progress.
- Rooms seed automatically on startup if the table is empty.
