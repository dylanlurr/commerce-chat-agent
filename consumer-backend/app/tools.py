from dataclasses import dataclass, field


@dataclass
class ConsumerTools:
    products: list[dict] = field(
        default_factory=lambda: [
            {"sku": "SKU1", "name": "Phone", "description": "Smart phone", "price": 499.99},
            {"sku": "SKU2", "name": "Headphones", "description": "Noise cancelling", "price": 199.0},
        ]
    )
    cart: dict[str, int] = field(default_factory=dict)

    def search_products(self, query: str) -> dict:
        matches = [p for p in self.products if query.lower() in p["name"].lower()]
        return {"matches": matches}

    def add_to_cart(self, sku: str, quantity: int = 1) -> dict:
        self.cart[sku] = self.cart.get(sku, 0) + quantity
        return {"cart": self.cart}

    def compare_products(self, skus: list[str]) -> dict:
        selected = [p for p in self.products if p["sku"] in skus]
        return {"comparison": selected}

    def checkout(self) -> dict:
        if not self.cart:
            return {"status": "empty_cart"}
        total = 0.0
        for sku, qty in self.cart.items():
            for product in self.products:
                if product["sku"] == sku:
                    total += product["price"] * qty
        self.cart.clear()
        return {"status": "success", "total": round(total, 2)}
