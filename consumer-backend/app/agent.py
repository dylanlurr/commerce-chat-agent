import json
import os
from typing import Any

from .tools import ConsumerTools


class OpenAIChatAgent:
    def __init__(self, tools: ConsumerTools):
        self.tools = tools
        self.api_key = os.getenv("OPENAI_API_KEY")

    @property
    def tool_specs(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "search_products",
                    "description": "Search products by a free-text query",
                    "parameters": {
                        "type": "object",
                        "properties": {"query": {"type": "string"}},
                        "required": ["query"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "add_to_cart",
                    "description": "Add product to cart",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "sku": {"type": "string"},
                            "quantity": {"type": "integer", "default": 1},
                        },
                        "required": ["sku"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "compare_products",
                    "description": "Compare product attributes and prices",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "skus": {"type": "array", "items": {"type": "string"}}
                        },
                        "required": ["skus"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "checkout",
                    "description": "Checkout cart and return total",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
        ]

    def _invoke_tool(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        if name == "search_products":
            return self.tools.search_products(query=args.get("query", ""))
        if name == "add_to_cart":
            return self.tools.add_to_cart(sku=args.get("sku", ""), quantity=int(args.get("quantity", 1)))
        if name == "compare_products":
            return self.tools.compare_products(skus=args.get("skus", []))
        if name == "checkout":
            return self.tools.checkout()
        return {"error": f"Unknown tool: {name}"}

    def _fallback(self, message: str) -> tuple[str, str | None]:
        text = message.lower()
        if "search" in text or "find" in text:
            result = self.tools.search_products(query=message)
            return json.dumps(result), "search_products"
        if "add" in text and "sku" in text:
            sku = message.split("sku")[-1].strip().upper() or "SKU1"
            result = self.tools.add_to_cart(sku=sku, quantity=1)
            return json.dumps(result), "add_to_cart"
        if "compare" in text:
            result = self.tools.compare_products(["SKU1", "SKU2"])
            return json.dumps(result), "compare_products"
        if "checkout" in text:
            result = self.tools.checkout()
            return json.dumps(result), "checkout"
        return "How can I help you shop today?", None

    def respond(self, message: str) -> tuple[str, str | None]:
        if not self.api_key:
            return self._fallback(message)

        try:
            from openai import OpenAI

            client = OpenAI(api_key=self.api_key)
            initial = client.chat.completions.create(
                model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                messages=[{"role": "user", "content": message}],
                tools=self.tool_specs,
                tool_choice="auto",
            )
            assistant_message = initial.choices[0].message
            if not assistant_message.tool_calls:
                return assistant_message.content or "", None

            call = assistant_message.tool_calls[0]
            arguments = json.loads(call.function.arguments or "{}")
            tool_result = self._invoke_tool(call.function.name, arguments)
            follow_up = client.chat.completions.create(
                model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                messages=[
                    {"role": "user", "content": message},
                    assistant_message,
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "name": call.function.name,
                        "content": json.dumps(tool_result),
                    },
                ],
            )
            return follow_up.choices[0].message.content or json.dumps(tool_result), call.function.name
        except Exception:
            return self._fallback(message)
