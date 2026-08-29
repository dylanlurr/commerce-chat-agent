"""
Tool implementations for the shopping assistant agent.
All queries execute directly against the merchant's dedicated tenant database session.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Product, Cart, CartItem, Transaction


# ── Helper ────────────────────────────────────────────────────────────────────

def _product_to_dict(p: Product) -> dict[str, Any]:
    """Convert a Product ORM object to a serializable dict."""
    return {
        "id": str(p.id),
        "title": p.title,
        "description": p.description or "",
        "price": float(p.price),
        "category": p.category or "",
        "attributes": p.attributes or {},
        "image_url": p.image_url or "",
        "stock": p.stock,
    }


async def _get_or_create_cart(
    db: AsyncSession, session_id: str
) -> Cart:
    """Get the active cart for a session, or create one in the merchant DB."""
    result = await db.execute(
        select(Cart).where(Cart.session_id == session_id)
    )
    cart = result.scalar_one_or_none()
    if not cart:
        cart = Cart(session_id=session_id)
        db.add(cart)
        await db.flush()
        await db.refresh(cart)
    return cart


async def _get_cart_summary(db: AsyncSession, cart: Cart) -> dict[str, Any]:
    """Build a cart summary dict."""
    await db.refresh(cart, ["items"])
    items = []
    total = 0.0
    for item in cart.items:
        await db.refresh(item, ["product"])
        price = float(item.product.price)
        subtotal = price * item.quantity
        total += subtotal
        items.append({
            "product_id": str(item.product_id),
            "title": item.product.title,
            "price": price,
            "quantity": item.quantity,
            "subtotal": subtotal,
        })
    return {
        "items": items,
        "total": round(total, 2),
        "item_count": sum(i["quantity"] for i in items),
    }


# ── Tool: search_products ────────────────────────────────────────────────────

async def search_products(
    db: AsyncSession,
    query: str,
    category: str | None = None,
    max_price: float | None = None,
    min_price: float | None = None,
) -> str:
    """Search the product catalog in the merchant's dedicated database."""
    stmt = select(Product)

    if query.strip():
        term = f"%{query.strip()}%"
        stmt = stmt.where(
            or_(
                Product.title.ilike(term),
                Product.description.ilike(term),
                Product.category.ilike(term),
            )
        )

    if category:
        stmt = stmt.where(Product.category.ilike(f"%{category}%"))

    if min_price is not None:
        stmt = stmt.where(Product.price >= Decimal(str(min_price)))

    if max_price is not None:
        stmt = stmt.where(Product.price <= Decimal(str(max_price)))

    stmt = stmt.order_by(Product.price).limit(10)
    result = await db.execute(stmt)
    products = result.scalars().all()

    if not products:
        return "No products found matching your search criteria."

    lines = [f"Found {len(products)} product(s):\n"]
    for p in products:
        d = _product_to_dict(p)
        stock_label = f"{d['stock']} in stock" if d['stock'] > 0 else "OUT OF STOCK"
        lines.append(
            f"- **{d['title']}** (ID: {d['id']})\n"
            f"  Price: ${d['price']:.2f} | Category: {d['category'] or 'N/A'} | {stock_label}\n"
            f"  {d['description'][:120]}"
        )
    return "\n".join(lines)


# ── Tool: add_to_cart ─────────────────────────────────────────────────────────

async def add_to_cart(
    db: AsyncSession,
    session_id: str,
    product_id: str,
    quantity: int = 1,
) -> str:
    """Add a product to the shopping cart in the merchant's database. Checks stock first."""
    try:
        prod_uuid = uuid.UUID(product_id)
    except ValueError:
        return f"Invalid product ID: {product_id}"

    result = await db.execute(
        select(Product).where(Product.id == prod_uuid)
    )
    product = result.scalar_one_or_none()
    if not product:
        return f"Product {product_id} not found."

    # Stock check
    if product.stock < quantity:
        if product.stock == 0:
            return f"Sorry, **{product.title}** is currently out of stock."
        return (
            f"Sorry, only {product.stock} unit(s) of **{product.title}** available, "
            f"but you requested {quantity}."
        )

    # Get or create cart
    cart = await _get_or_create_cart(db, session_id)

    # Check if item already in cart
    result = await db.execute(
        select(CartItem).where(
            CartItem.cart_id == cart.id,
            CartItem.product_id == prod_uuid,
        )
    )
    existing = result.scalar_one_or_none()

    if existing:
        new_qty = existing.quantity + quantity
        if new_qty > product.stock:
            return (
                f"Cannot add {quantity} more — you already have {existing.quantity} in cart, "
                f"and only {product.stock} total are in stock."
            )
        existing.quantity = new_qty
    else:
        item = CartItem(
            cart_id=cart.id,
            product_id=prod_uuid,
            quantity=quantity,
        )
        db.add(item)

    await db.flush()

    # Return updated cart summary
    summary = await _get_cart_summary(db, cart)
    return (
        f"Added {quantity}x **{product.title}** (${float(product.price):.2f}) to your cart.\n\n"
        f"Cart total: ${summary['total']:.2f} ({summary['item_count']} item(s))"
    )


# ── Tool: compare_products ───────────────────────────────────────────────────

async def compare_products(
    db: AsyncSession,
    product_ids: list[str],
) -> str:
    """Compare two or more products side by side from the merchant database."""
    if len(product_ids) < 2:
        return "Please provide at least 2 product IDs to compare."

    products = []
    for pid in product_ids:
        try:
            prod_uuid = uuid.UUID(pid)
        except ValueError:
            continue
        result = await db.execute(
            select(Product).where(Product.id == prod_uuid)
        )
        p = result.scalar_one_or_none()
        if p:
            products.append(_product_to_dict(p))

    if len(products) < 2:
        return "Could not find enough products to compare. Please check the product IDs."

    # Build comparison text
    lines = ["**Product Comparison:**\n"]
    lines.append("| Feature | " + " | ".join(p["title"] for p in products) + " |")
    lines.append("|---------|" + "|".join("------" for _ in products) + "|")
    lines.append("| Price | " + " | ".join(f"${p['price']:.2f}" for p in products) + " |")
    lines.append("| Category | " + " | ".join(p["category"] or "N/A" for p in products) + " |")
    lines.append(
        "| Stock | "
        + " | ".join(
            f"{p['stock']} available" if p["stock"] > 0 else "OUT OF STOCK"
            for p in products
        )
        + " |"
    )
    lines.append(
        "| Description | "
        + " | ".join(p["description"][:80] or "N/A" for p in products)
        + " |"
    )

    # Compare attributes
    all_attrs = set()
    for p in products:
        all_attrs.update(p["attributes"].keys())
    for attr in sorted(all_attrs):
        vals = [str(p["attributes"].get(attr, "—")) for p in products]
        lines.append(f"| {attr} | " + " | ".join(vals) + " |")

    return "\n".join(lines)


# ── Tool: check_inventory ────────────────────────────────────────────────────

async def check_inventory(
    db: AsyncSession,
    product_id: str,
) -> str:
    """Check the current stock level for a product in the merchant DB."""
    try:
        prod_uuid = uuid.UUID(product_id)
    except ValueError:
        return f"Invalid product ID: {product_id}"

    result = await db.execute(
        select(Product).where(Product.id == prod_uuid)
    )
    product = result.scalar_one_or_none()
    if not product:
        return f"Product {product_id} not found."

    if product.stock > 0:
        return (
            f"**{product.title}** — {product.stock} unit(s) in stock. "
            f"Price: ${float(product.price):.2f}"
        )
    else:
        return f"**{product.title}** is currently **OUT OF STOCK**."


# ── Tool: checkout ────────────────────────────────────────────────────────────

async def checkout(
    db: AsyncSession,
    session_id: str,
) -> str:
    """
    Process checkout — mock payment flow on the merchant database.
    Validates stock, decrements inventory, creates transaction, and clears the cart.
    """
    result = await db.execute(
        select(Cart).where(Cart.session_id == session_id)
    )
    cart = result.scalar_one_or_none()
    if not cart:
        return "Your cart is empty. Add some products before checking out!"

    await db.refresh(cart, ["items"])
    if not cart.items:
        return "Your cart is empty. Add some products before checking out!"

    # Validate stock for all items
    out_of_stock = []
    total = Decimal("0.00")

    for item in cart.items:
        await db.refresh(item, ["product"])
        product = item.product

        if product.stock < item.quantity:
            out_of_stock.append(
                f"- **{product.title}**: requested {item.quantity}, "
                f"only {product.stock} available"
            )
        else:
            total += product.price * item.quantity

    if out_of_stock:
        return (
            "Cannot complete checkout — some items have insufficient stock:\n\n"
            + "\n".join(out_of_stock)
            + "\n\nPlease update your cart and try again."
        )

    # Decrement stock
    for item in cart.items:
        item.product.stock -= item.quantity

    # Create transaction
    transaction = Transaction(
        cart_id=cart.id,
        session_id=session_id,
        total_amount=total,
        status="completed",
    )
    db.add(transaction)

    # Clear cart items
    for item in list(cart.items):
        await db.delete(item)

    await db.flush()
    await db.refresh(transaction)

    return (
        f"🎉 **Order confirmed!**\n\n"
        f"Transaction ID: `{transaction.id}`\n"
        f"Total: **${float(total):.2f}**\n"
        f"Status: Completed (mock payment)\n\n"
        f"Thank you for your purchase!"
    )
