# Commerce Chat Agent

An intelligent, multi-tenant conversational commerce platform. Merchants can create stores, upload product catalogs via CSV (with AI-powered column mapping and attribute extraction), and manage inventory. Consumers interact with an AI shopping assistant that searches products, compares items, manages persistent carts, and completes checkout conversations in real time.

---

## System Architecture

```
commerce-chat-agent/
├── merchant-backend/         # FastAPI service (port 8000) — merchant onboarding, CSV ingestion & catalog CRUD
│   ├── app/
│   │   ├── config.py         # App settings & PostgreSQL connection URLs
│   │   ├── database.py       # Central database & dynamic tenant database provisioning
│   │   ├── models.py         # SQLAlchemy ORM models (Merchant, Product, Cart, etc.)
│   │   ├── schemas.py        # Pydantic validation schemas
│   │   ├── routes/           # REST API endpoints (merchants, catalog, health)
│   │   └── services/         # CSV processing & LLM column mapping
│   └── static/index.html     # Merchant Dashboard web UI
├── consumer-backend/         # FastAPI service (port 8001) — AI shopping assistant with function calling
│   ├── app/
│   │   ├── config.py         # Consumer app settings
│   │   ├── database.py       # Dynamic tenant session router
│   │   ├── models.py         # Consumer data models
│   │   ├── schemas.py        # Chat request/response schemas
│   │   ├── routes/           # Chat & health endpoints
│   │   └── services/         # OpenAI function-calling agent & tool execution
│   └── static/index.html     # Shopping Assistant chat web UI
├── frontend/
│   └── index.html            # Hub Landing Page linking both portals
├── test_products.csv         # Sample product catalog for testing
├── .env.example              # Environment variables template
└── README.md                 # Project documentation
```

### 1. Multi-Tenant Database Architecture
- **Central Registry (`commerce_agent`)**:
  - Tracks merchant accounts (`id`, `name`, `email`, `database_name`, `created_at`).
- **Dedicated Database per Merchant (`merchant_<name>_<hash>`)**:
  - Each merchant gets an isolated PostgreSQL database dynamically provisioned during store creation (`POST /merchants`).
  - Isolated tenant tables:
    - `products`: Catalog items, price, stock, specs, and JSONB `attributes`.
    - `categories`: Product category hierarchy.
    - `upload_logs`: Ingestion history, column mapping records, and upload identifiers (`upload_id`).
    - `carts` & `cart_items`: Consumer carts scoped per shopping session (`session_id`).
    - `transactions`: Completed checkout orders and totals.

### 2. LLM-Assisted CSV Ingestion
During CSV catalog uploads (`POST /catalog/upload`), the system uses OpenAI `gpt-4o-mini` with structured JSON output:
- Automatically maps custom or messy column headers to the 7 core schema fields: `title`, `description`, `price`, `category`, `attributes`, `image_url`, `stock`.
- Robust handling of currency-annotated columns (e.g. `Price (USD)`, `Unit Cost ($)`, `In Stock (Units)`).
- **Attribute Preservation**: Any unmapped columns (e.g. `Brand`, `Frame Shape`, `Frame Color`, `Material`) are preserved as structured key-value pairs in the `attributes` JSONB field for each product so no merchant data is lost.

### 3. AI Shopping Assistant (Function Calling)
- Powered by OpenAI `gpt-4o-mini` with real-time tool calling.
- Dynamically connects to the selected merchant's dedicated PostgreSQL database.
- Features persistent session memory, smart product search, item comparisons, inventory validation, and cart management without exposing raw database UUIDs.

---

## Prerequisites

- **Python**: 3.12 or higher
- **PostgreSQL**: 14 or higher (running locally or via Docker)
- **OpenAI API Key**: Active key with model access (`gpt-4o-mini`)

---

## Step-by-Step Installation & Setup

### Step 1: Clone the Repository & Set Up Virtual Environment

```bash
cd /path/to/commerce-chat-agent

# Create virtual environment with Python 3.12
python3.12 -m venv venv

# Activate virtual environment
source venv/bin/activate

# Install dependencies
pip install fastapi "uvicorn[standard]" "sqlalchemy[asyncio]" asyncpg \
    psycopg2-binary python-dotenv python-multipart pandas pydantic \
    pydantic-settings openai
```

---

### Step 2: Configure Environment Variables

Copy the template file to `.env`:

```bash
cp .env.example .env
```

Open `.env` and fill in your PostgreSQL credentials and OpenAI API key:

```env
DATABASE_URL=postgresql+asyncpg://<username>:<password>@localhost:5432/commerce_agent
DATABASE_URL_SYNC=postgresql://<username>:<password>@localhost:5432/commerce_agent
OPENAI_API_KEY=sk-your-actual-openai-api-key-here
MERCHANT_BACKEND_URL=http://localhost:8000
CONSUMER_BACKEND_URL=http://localhost:8001
```

---

### Step 3: Initialize PostgreSQL Central Database

Make sure PostgreSQL is running on your machine, then create the central database `commerce_agent`:

```bash
# Start PostgreSQL (macOS Homebrew example)
pg_ctl -D /opt/homebrew/var/postgresql@14 start

# Create central database
psql -d postgres -c "CREATE DATABASE commerce_agent;"
```

---

### Step 4: Start the Backend Services

Open two terminal windows (or tabs) and start both services:

#### Terminal 1 — Merchant Backend (Port 8000)
```bash
source venv/bin/activate
cd merchant-backend
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

#### Terminal 2 — Consumer Backend (Port 8001)
```bash
source venv/bin/activate
cd consumer-backend
uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload
```

---

## Accessing the Web Portals

| Portal | URL | Description |
|---|---|---|
| **Hub Landing Page** | Open [`frontend/index.html`](file:///Users/dylan.lorrenzo/Documents/commerce-chat-agent/frontend/index.html) in browser | Central launchpad linking Merchant & Consumer portals |
| **Merchant Dashboard** | [http://localhost:8000](http://localhost:8000) | Store creation, CSV catalog upload, inline catalog editing & store management |
| **Consumer Shopping Assistant** | [http://localhost:8001](http://localhost:8001) | Conversational shopping assistant, catalog discovery, cart & checkout |
| **Merchant API Docs (Swagger)** | [http://localhost:8000/docs](http://localhost:8000/docs) | Interactive OpenAPI documentation for Merchant backend |
| **Consumer API Docs (Swagger)** | [http://localhost:8001/docs](http://localhost:8001/docs) | Interactive OpenAPI documentation for Consumer backend |

---

## User Flow & Usage Guide

### 1. Merchant Onboarding & Catalog Upload
1. Open **Merchant Dashboard** at `http://localhost:8000`.
2. Under **Register New Store**, enter a store name (e.g. `Apex Optics`) and email, then click **Create Store**.
   - *Backend automatically provisions a dedicated database `merchant_apex_optics_<hash>` and runs all schema migrations.*
3. Select your store from the store dropdown.
4. Under **Upload Catalog CSV**, select [`test_products.csv`](file:///Users/dylan.lorrenzo/Documents/commerce-chat-agent/test_products.csv) (or any custom CSV) and click **Upload & Process**.
5. Review the inferred column mappings and uploaded products in the catalog table.
   - You can edit price, stock, or category inline.
   - You can delete single products, undo an entire upload batch, or clear the catalog.
   - You can permanently delete a store and drop its dedicated database with **Delete Store**.

### 2. Shopping with the AI Assistant
1. Open **Shopping Assistant** at `http://localhost:8001`.
2. Select your store from the **Store** selector dropdown.
3. Chat with the shopping assistant using natural language:
   - *"What sunglasses do you have in stock?"*
   - *"Show me blue light glasses under $150"*
   - *"Compare Oliver Peoples Modern with Gucci Studio"*
   - *"Add 1 pair of Gucci Studio to my cart"*
   - *"What is my cart total?"*
   - *"I would like to checkout please"*
4. Watch items update dynamically in the **Your Cart** sidebar on the right.

---

## API Reference

### Merchant Backend (`http://localhost:8000`)

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | Health check endpoint |
| `POST` | `/merchants` | Register merchant & provision isolated database |
| `GET` | `/merchants` | List all registered merchants from central registry |
| `DELETE` | `/merchants/{id}` | Delete merchant and drop its dedicated database |
| `POST` | `/catalog/upload` | Upload CSV catalog with AI field mapping |
| `GET` | `/catalog?merchant_id={id}` | List products from merchant's tenant database |
| `GET` | `/catalog/search?merchant_id={id}&query={q}` | Search products in merchant catalog |
| `PATCH` | `/catalog/{id}?merchant_id={id}` | Update product fields inline |
| `DELETE` | `/catalog/{id}?merchant_id={id}` | Delete a single product from catalog |
| `DELETE` | `/catalog/upload/{upload_id}?merchant_id={id}` | Undo an entire CSV upload batch |
| `DELETE` | `/catalog/clear/all?merchant_id={id}` | Clear all products from merchant store |

### Consumer Backend (`http://localhost:8001`)

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | Health check endpoint |
| `POST` | `/chat` | Send consumer message to AI shopping assistant |

---

## AI Agent Tools

The AI assistant has access to 5 specialized tools executed directly against the tenant database:

1. `search_products`: Search products by text query, category, and min/max price.
2. `add_to_cart`: Validate stock and add items to the customer's active cart.
3. `compare_products`: Compare 2 or more products side by side with specs and pricing.
4. `check_inventory`: Check real-time stock availability for a specific product.
5. `checkout`: Complete mock checkout, decrement catalog inventory, and record transaction.

---

## License

This project is licensed under the MIT License.
