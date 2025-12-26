# Resort Agentic AI System

Chat-based multi-agent system for a resort with Receptionist, Restaurant, and Room Service agents. Routes guest requests, calls tools, persists data to SQLite, and exposes a lightweight dashboard.

## Features
- Single `/api/chat` endpoint for multi-turn conversations with routing to receptionist, restaurant, or room service agents.
- Optional OpenAI-powered intent parsing and extraction with rule-based fallback for offline use.
- SQLite persistence for users, conversations, restaurant orders, and room service requests.
- Room booking gate: users must book a room before requesting services (rooms 101–119, 201–229, 301–339).
- Unique display IDs for services: `RES-<room>-<6>` and `ROS-<room>-<6>`.
- Dashboard (`/dashboard`) for restaurant + room-service activity and user list, with status controls.
- Invoice summary in chat sidebar (per user).

## Architecture
- **FastAPI** app at `app/main.py` mounts endpoints and seeds rooms on startup.
- **Agents** (`app/agents/*`): orchestrator routes to department-specific agents; each agent performs domain logic and writes to the DB.
- **Data**: SQLite models in `app/models.py`; menu/config under `app/data`.
- **LLM client**: `app/agents/llm_client.py` uses `OPENAI_API_KEY` if set, otherwise falls back to keyword heuristics.
- **Dashboard**: static HTML/JS in `app/static/dashboard.html` pulling from `/api/dashboard`.
- **Auth**: register/login pages (`/register`, `/login`) persist users to DB.

## Quickstart
```bash
# 1) Create a virtual environment
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\\Scripts\\activate

# 2) Install dependencies
pip install -r requirements.txt

# 3) Create environment file
cat > .env <<'ENV'
OPENAI_API_KEY=
OPENAI_MODEL=gpt-4o-mini
DATABASE_URL=sqlite:///./resort.db
DEBUG=false
ENV

# 4) Run the server
uvicorn app.main:app --reload --port 8000
```

Open:
- Landing page: http://localhost:8000/
- Register: http://localhost:8000/register
- Login: http://localhost:8000/login
- Chat: http://localhost:8000/chat
- Dashboard: http://localhost:8000/dashboard
- API docs: http://localhost:8000/docs

## Setup
```bash
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Create your environment file
cat > .env <<'ENV'
# Optional: OpenAI key for richer intent parsing. Leave blank to stay heuristic-only.
OPENAI_API_KEY=
OPENAI_MODEL=gpt-4o-mini
# SQLite by default; replace with Postgres URL if needed.
DATABASE_URL=sqlite:///./resort.db
DEBUG=false
ENV
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
  "conversation_id": "optional-uuid",
  "user_id": "optional-user-id"
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
- Data source: `GET /api/dashboard` (JSON with restaurant_orders, room_service_requests, users).
- Update statuses via the dropdowns on each row. Changes reflect in user chat sidebar.

## Auth & Users
- Register: `POST /api/register` with `{ full_name, email, password }`.
- Login: `POST /api/login` with `{ email, password }`.
- Users are listed on the dashboard with their assigned room number (or `NA`).

## Invoice
- `GET /api/users/{user_id}/invoice` returns guest info and all restaurant orders with total due.
- Chat sidebar shows the invoice and a “Pay bill” CTA.

## Data model
- **User**: id, full_name, email, password_hash, room_number, timestamps.
- **RestaurantOrder**: id, display_id, room_number, items (JSON array), total_amount, status, timestamps.
- **RoomServiceRequest**: id, display_id, room_number, request_type, status, timestamps.
- **ConversationMessage**: stored per turn to maintain context (currently not replayed to the LLM, but available for extension).
- **Room**: room_number, availability; seeded on startup.

## Sample flows
1. Ask for info: "What time is check-in and is the gym open?" → receptionist responds from config.
2. Order food: "Send two Margherita Pizzas to room 201" → restaurant agent logs order, returns bill, shows on dashboard.
3. Room service: "Need laundry pickup in 301" → room service agent logs a request.
4. Availability: "Do you have rooms open tonight?" → receptionist reads from the rooms table.
5. Billing: "Show me the bill" → invoice summary appears in sidebar.

<!-- ## Notes
- Agents fall back to keyword heuristics when `OPENAI_API_KEY` is not set.
- Conversation IDs persist across turns if you pass the same `conversation_id` in subsequent calls.
- Update statuses directly in the DB (SQLite file at `resort.db` by default) if you need to simulate workflow progress.
- Rooms seed automatically on startup if the table is empty. -->

## Overall System Design
```bash
Guest UI (Landing/Login/Register/Chat)
        |
        v
   FastAPI (app/main.py)
   ├── /api/register, /api/login
   ├── /api/chat  --------------------+
   ├── /api/users/{id}/history         |
   ├── /api/users/{id}/invoice         |
   ├── /api/orders/{id}/status         |
   └── /api/room-service/{id}/status   |
        |                              |
        v                              |
 Agent Orchestrator                    |
  ├── ReceptionistAgent                |
  ├── RestaurantAgent  ----> Orders ---+--> SQLite 
  └── RoomServiceAgent ----> Requests--+--> Users / Rooms / Messages
```

## Folder Structure
```bash
app/
├── agents/
│   ├── llm_client.py           # OpenAI intent + extraction
│   ├── orchestrator.py         # Routes requests to agents
│   ├── receptionist_agent.py   # FAQ + room availability
│   ├── restaurant_agent.py     # Menu + order + billing
│   ├── room_service_agent.py   # Cleaning/laundry/amenities
│   └── types.py                # AgentResult dataclass
├── data/
│   ├── menu.py                 # Menu loader 
│   └── resort_info.py          # Static resort info
├── static/
│   ├── landing.html            # Marketing landing page
│   ├── login.html              # Login UI
│   ├── register.html           # Register UI
│   ├── chat.html               # Guest chat + invoice sidebar
│   └── dashboard.html          # Operations dashboard
├── config.py                   # Env config
├── database.py                 # SQLAlchemy engine/session
├── main.py                     # API + routes
├── models.py                   # SQLAlchemy models
└── schemas.py                  # Pydantic schemas
```
