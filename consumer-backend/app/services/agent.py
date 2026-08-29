"""
OpenAI function-calling agent for the shopping assistant.
Manages conversation memory per session and executes tools against the merchant database.
"""

import asyncio
import json
from typing import Any

from openai import AsyncOpenAI, RateLimitError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.services import tools

# ── OpenAI client ─────────────────────────────────────────────────────────────

_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    """Lazily create the OpenAI client so the server can start without a key."""
    global _client
    if _client is None:
        api_key = settings.openai_api_key
        if not api_key or api_key.startswith("sk-your"):
            raise RuntimeError(
                "OpenAI API key not configured. "
                "Set OPENAI_API_KEY in your .env file."
            )
        _client = AsyncOpenAI(api_key=api_key)
    return _client


MODEL = "gpt-4o-mini"

# ── In-memory session store ──────────────────────────────────────────────────

_sessions: dict[str, list[dict[str, Any]]] = {}

# ── System prompt ────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are a friendly and knowledgeable shopping assistant. Your job is to help customers:

1. **Discover** products — search and browse the merchant's catalog
2. **Decide** — compare products, check inventory, answer questions
3. **Purchase** — manage their cart and complete checkout

Guidelines:
- Always be helpful, concise, and proactive in suggesting products.
- When a customer mentions a budget, remember it and filter accordingly.
- Before adding to cart, always confirm the product and quantity with the customer unless they've been very specific.
- NEVER allow a purchase of an out-of-stock item. Always check inventory before confirming checkout.
- When comparing products, present the information in a clear, structured format.
- When presenting products to the customer, present them cleanly with their title, category, price, and stock status. Do NOT display raw product UUIDs/IDs to the customer in your messages, but keep track of them internally to use with tools (such as add_to_cart, check_inventory, compare_products) when the customer refers to an item by title, number, or description.
- After adding items to cart, summarize what's in the cart.
- For checkout, always confirm the order total with the customer first.
- If the customer asks about something outside of shopping (weather, coding, etc.), politely redirect them to shopping.
- Do NOT use emojis in your responses. Keep all formatting clean, professional, and text-based.

You have access to the following tools:
- search_products: Search the product catalog
- add_to_cart: Add a product to the customer's cart
- compare_products: Compare 2 or more products side by side
- check_inventory: Check if a product is in stock
- checkout: Process the cart and complete a mock purchase

Remember context from earlier in the conversation — budgets, preferences, items discussed, etc."""

# ── Tool definitions for OpenAI function calling ─────────────────────────────

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "search_products",
            "description": "Search the product catalog by text query. Can filter by category, min/max price.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query text (product name, description, category keywords)",
                    },
                    "category": {
                        "type": "string",
                        "description": "Filter by category name (optional)",
                    },
                    "max_price": {
                        "type": "number",
                        "description": "Maximum price filter (optional)",
                    },
                    "min_price": {
                        "type": "number",
                        "description": "Minimum price filter (optional)",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_to_cart",
            "description": "Add a product to the customer's shopping cart. Checks stock availability.",
            "parameters": {
                "type": "object",
                "properties": {
                    "product_id": {
                        "type": "string",
                        "description": "The UUID of the product to add",
                    },
                    "quantity": {
                        "type": "integer",
                        "description": "Number of units to add (default: 1)",
                        "default": 1,
                    },
                },
                "required": ["product_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compare_products",
            "description": "Compare two or more products side by side. Requires at least 2 product IDs.",
            "parameters": {
                "type": "object",
                "properties": {
                    "product_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of product UUIDs to compare (minimum 2)",
                    },
                },
                "required": ["product_ids"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_inventory",
            "description": "Check the current stock level and availability of a product.",
            "parameters": {
                "type": "object",
                "properties": {
                    "product_id": {
                        "type": "string",
                        "description": "The UUID of the product to check",
                    },
                },
                "required": ["product_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "checkout",
            "description": "Process checkout and complete the purchase. Validates stock for all cart items, creates a transaction, and decrements inventory. This is a MOCK payment — no real charges.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
]


# ── Tool dispatcher ──────────────────────────────────────────────────────────

async def _execute_tool(
    tool_name: str,
    arguments: dict[str, Any],
    db: AsyncSession,
    session_id: str,
) -> str:
    """Execute a tool by name against the merchant's dedicated database."""
    try:
        if tool_name == "search_products":
            return await tools.search_products(
                db=db,
                query=arguments.get("query", ""),
                category=arguments.get("category"),
                max_price=arguments.get("max_price"),
                min_price=arguments.get("min_price"),
            )
        elif tool_name == "add_to_cart":
            return await tools.add_to_cart(
                db=db,
                session_id=session_id,
                product_id=arguments["product_id"],
                quantity=arguments.get("quantity", 1),
            )
        elif tool_name == "compare_products":
            return await tools.compare_products(
                db=db,
                product_ids=arguments["product_ids"],
            )
        elif tool_name == "check_inventory":
            return await tools.check_inventory(
                db=db,
                product_id=arguments["product_id"],
            )
        elif tool_name == "checkout":
            return await tools.checkout(
                db=db,
                session_id=session_id,
            )
        else:
            return f"Unknown tool: {tool_name}"
    except Exception as e:
        return f"Tool error ({tool_name}): {str(e)}"


# ── Main agent loop ──────────────────────────────────────────────────────────

async def chat(
    db: AsyncSession,
    session_id: str,
    user_message: str,
) -> str:
    """
    Process a user message through the agent.
    Maintains conversation history per session and runs the function-calling loop.
    """
    if session_id not in _sessions:
        _sessions[session_id] = [{"role": "system", "content": SYSTEM_PROMPT}]

    messages = _sessions[session_id]
    messages.append({"role": "user", "content": user_message})

    client = _get_client()

    for _ in range(10):
        response = None
        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = await client.chat.completions.create(
                    model=MODEL,
                    messages=messages,
                    tools=TOOL_DEFINITIONS,
                    tool_choice="auto",
                )
                break
            except RateLimitError as e:
                if attempt < max_retries - 1:
                    wait_time = 4 * (attempt + 1)
                    await asyncio.sleep(wait_time)
                else:
                    return (
                        "I am temporarily rate-limited. Please wait a few seconds and try again."
                    )

        if not response:
            return "I couldn't get a response from the AI model. Please try again shortly."

        choice = response.choices[0]
        assistant_message = choice.message
        messages.append(assistant_message)

        if not assistant_message.tool_calls:
            return assistant_message.content or "I'm sorry, I couldn't process that."

        for tool_call in assistant_message.tool_calls:
            fn_name = tool_call.function.name
            try:
                fn_args = json.loads(tool_call.function.arguments)
            except json.JSONDecodeError:
                fn_args = {}

            result = await _execute_tool(
                tool_name=fn_name,
                arguments=fn_args,
                db=db,
                session_id=session_id,
            )

            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": result,
            })

    return "I'm having trouble processing your request. Could you try rephrasing?"
