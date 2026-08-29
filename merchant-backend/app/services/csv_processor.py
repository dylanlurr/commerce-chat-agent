"""
CSV processing service — parsing, LLM-assisted column mapping, validation, and normalization.
"""

from __future__ import annotations

import io
import json
import logging
import re
from decimal import Decimal, InvalidOperation
from typing import Any

import pandas as pd
from openai import AsyncOpenAI

from app.config import settings

logger = logging.getLogger(__name__)

# The target schema columns the merchant catalog expects
TARGET_COLUMNS = {
    "title",
    "description",
    "price",
    "category",
    "attributes",
    "image_url",
    "stock",
}

_openai_client: AsyncOpenAI | None = None


def _get_openai_client() -> AsyncOpenAI | None:
    global _openai_client
    if _openai_client is None:
        key = settings.openai_api_key
        if key and not key.startswith("sk-your"):
            _openai_client = AsyncOpenAI(api_key=key)
    return _openai_client


def _clean_column_variations(col: str) -> list[str]:
    """
    Generate normalized forms of a column name for flexible synonym matching.
    Handles parentheses, brackets, currency symbols, and extra punctuation.
    Example: 'Price (USD)' -> ['price', 'price_usd', 'price (usd)']
    """
    raw = col.strip().lower()

    # 1. Remove text inside parentheses: "Price (USD)" -> "price"
    no_parens = re.sub(r"\(.*?\)", "", raw).strip()
    slug_no_parens = re.sub(r"[^\w]+", "_", no_parens).strip("_")

    # 2. Remove text inside brackets: "Cost [EUR]" -> "cost"
    no_brackets = re.sub(r"\[.*?\]", "", no_parens).strip()
    slug_no_brackets = re.sub(r"[^\w]+", "_", no_brackets).strip("_")

    # 3. Slug with all alphanumeric characters: "Price (USD)" -> "price_usd"
    slug_full = re.sub(r"[^\w]+", "_", raw).strip("_")

    # 4. Remove currency symbols or codes: "$", "USD", "EUR", etc.
    clean_currency = re.sub(r"[\$€£¥₹]", "", raw)
    clean_currency = re.sub(
        r"\b(usd|eur|gbp|aud|cad|jpy|idr|inr|cny|sgd|cents)\b", "", clean_currency
    ).strip()
    slug_clean_currency = re.sub(r"[^\w]+", "_", clean_currency).strip("_")

    candidates = [
        slug_no_parens,
        slug_no_brackets,
        slug_clean_currency,
        slug_full,
        raw,
    ]
    seen = set()
    result = []
    for c in candidates:
        if c and c not in seen:
            seen.add(c)
            result.append(c)
    return result


def _fallback_mapping(columns: list[str]) -> dict[str, str | None]:
    """Fallback standard normalization with robust multi-variant synonym matching."""
    mapping: dict[str, str | None] = {}

    synonyms = {
        "title": [
            "title",
            "name",
            "item_name",
            "product_name",
            "product",
            "item",
            "product_title",
            "item_title",
            "model_name",
            "item_description_short",
        ],
        "description": [
            "description",
            "desc",
            "details",
            "summary",
            "overview",
            "info",
            "product_description",
            "item_details",
            "long_description",
            "body",
        ],
        "price": [
            "price",
            "cost",
            "unit_cost",
            "unit_price",
            "selling_price",
            "msrp",
            "amount",
            "rate",
            "cost_price",
            "retail_price",
            "regular_price",
            "sale_price",
            "item_price",
            "price_usd",
            "price_eur",
            "price_cents",
        ],
        "category": [
            "category",
            "dept",
            "department",
            "type",
            "section",
            "group",
            "product_category",
            "item_category",
            "category_name",
            "collection",
        ],
        "attributes": [
            "attributes",
            "specs",
            "specifications",
            "properties",
            "features",
            "custom_attributes",
            "options",
            "metadata",
        ],
        "image_url": [
            "image_url",
            "image",
            "img",
            "photo",
            "pic",
            "image_link",
            "picture",
            "photo_url",
            "img_url",
            "picture_url",
            "thumbnail",
            "photo_link",
        ],
        "stock": [
            "stock",
            "quantity",
            "qty",
            "inventory",
            "count",
            "units",
            "in_stock",
            "stock_quantity",
            "available_stock",
            "qty_on_hand",
            "quantity_available",
        ],
    }

    used_targets = set()
    for col in columns:
        variants = _clean_column_variations(col)
        matched_target = None

        for variant in variants:
            for target, syn_list in synonyms.items():
                if variant in syn_list and target not in used_targets:
                    matched_target = target
                    used_targets.add(target)
                    break
            if matched_target:
                break

        mapping[col] = matched_target
    return mapping


async def infer_column_mappings(
    columns: list[str], sample_rows: list[dict[str, Any]]
) -> dict[str, str | None]:
    """
    Use OpenAI gpt-4o-mini to infer mapping from CSV column names to target schema fields.
    Returns a dict mapping source column name -> target schema field (or None if unmapped).
    """
    client = _get_openai_client()
    if not client:
        logger.info("OpenAI API key not configured, using fallback standard normalization.")
        return _fallback_mapping(columns)

    prompt = f"""You are an expert data ingestion assistant. You need to map raw CSV column names to a target product catalog schema.

Target schema fields:
- "title": Product name, item title, item name, model name (required). Examples: "Product Name", "Item Title (SKU)", "Title".
- "description": Product description, details, summary, overview (optional). Examples: "Details", "Description", "Overview".
- "price": Selling price, unit price, cost, MSRP, rate, or currency-annotated fields (required numeric). Examples: "Price (USD)", "Unit Price ($)", "Cost (EUR)", "Price", "MSRP", "Rate".
- "category": Product category, department, section, item group (optional). Examples: "Category", "Department", "Dept", "Section".
- "attributes": Technical specs, JSON attributes, key-value specifications (optional). Examples: "Attributes", "Specs", "Properties".
- "image_url": Product image link, photo URL, picture URL (optional). Examples: "Image URL", "Photo", "Pic", "Thumbnail", "Image Link".
- "stock": Available inventory quantity, stock count, quantity on hand, units in stock (optional integer). Examples: "Stock", "Quantity", "Qty", "In Stock (Units)", "Inventory Count".

CSV Columns to map:
{json.dumps(columns, indent=2)}

Sample Data (first few rows):
{json.dumps(sample_rows[:3], indent=2)}

Instructions:
1. For each input column name, determine if it corresponds to one of the 7 target fields: ["title", "description", "price", "category", "attributes", "image_url", "stock"].
2. Note: Ignore parenthetical currency or unit annotations like "(USD)", "($)", "(EUR)", "(units)", "[Qty]" when matching columns (e.g. "Price (USD)" MUST map to "price", "Stock (Units)" MUST map to "stock").
3. If a column cannot be confidently mapped to one of the 7 target fields (e.g. 'color', 'weight', 'sku', 'rating', 'supplier', or non-matching data), map it to null.
4. Do NOT map multiple CSV columns to the same target field (pick the best one, set others to null).
5. Return ONLY valid JSON in the exact structure:
{{
  "mapping": {{
    "csv_column_name": "target_field_or_null"
  }}
}}
"""

    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": "You are a precise data mapping assistant. Respond only with valid JSON.",
                },
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.0,
        )

        content = response.choices[0].message.content or "{}"
        parsed = json.loads(content)
        mapping = parsed.get("mapping", {})

        # Validate that mapped values are in TARGET_COLUMNS
        validated_mapping: dict[str, str | None] = {}
        for col in columns:
            target = mapping.get(col)
            if target and str(target).lower() in TARGET_COLUMNS:
                validated_mapping[col] = str(target).lower()
            else:
                validated_mapping[col] = None

        # Double check with fallback for any obvious unmapped fields like Price (USD)
        fallback = _fallback_mapping(columns)
        for col in columns:
            if not validated_mapping.get(col) and fallback.get(col):
                validated_mapping[col] = fallback[col]

        return validated_mapping

    except Exception as e:
        logger.warning(
            f"LLM column mapping failed: {e}. Falling back to standard normalization."
        )
        return _fallback_mapping(columns)


async def process_csv(file_bytes: bytes, filename: str) -> dict[str, Any]:
    """
    Parse and validate a CSV file against the target product schema with LLM-assisted column mapping.

    Returns a dict with:
        - rows: list of cleaned row dicts ready for DB insertion
        - total_rows: total rows in the CSV (excluding header)
        - ingested_rows: rows that passed validation
        - skipped_rows: rows that were empty or invalid
        - inferred_mapping: dict of {source_col: target_field} for auto-mapped columns
        - unmapped_columns: CSV columns that don't match the target schema
        - errors: list of {row, field, message} dicts describing issues
    """
    try:
        df = pd.read_csv(io.BytesIO(file_bytes), dtype=str, keep_default_na=False)
    except Exception as e:
        return {
            "rows": [],
            "total_rows": 0,
            "ingested_rows": 0,
            "skipped_rows": 0,
            "inferred_mapping": {},
            "unmapped_columns": [],
            "errors": [
                {"row": 0, "field": "", "message": f"Failed to parse CSV: {e}"}
            ],
        }

    raw_columns = list(df.columns)
    sample_rows = df.head(3).to_dict(orient="records")

    # Step 1: Infer column mappings using OpenAI LLM (or robust fallback)
    inferred_mapping_full = await infer_column_mappings(raw_columns, sample_rows)

    # Separate into mapped columns and unmapped columns
    rename_dict: dict[str, str] = {}
    inferred_mapping_result: dict[str, str] = {}
    unmapped_columns: list[str] = []

    for orig_col, target_field in inferred_mapping_full.items():
        if target_field and target_field in TARGET_COLUMNS:
            rename_dict[orig_col] = target_field
            if orig_col.lower().strip() != target_field:
                inferred_mapping_result[orig_col] = target_field
        else:
            unmapped_columns.append(orig_col)

    # Step 2: Apply the inferred mapping to rename the dataframe
    df = df.rename(columns=rename_dict)

    # Keep target schema columns and unmapped columns
    usable_columns = [col for col in df.columns if col in TARGET_COLUMNS or col in unmapped_columns]
    df = df[usable_columns]

    total_rows = len(df)
    rows: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    skipped = 0

    for idx, raw_row in df.iterrows():
        row_num = int(idx) + 2  # +2 for 1-indexed + header row
        row = raw_row.to_dict()

        # Skip completely empty rows
        if all(str(v).strip() == "" for v in row.values()):
            skipped += 1
            continue

        # Title is REQUIRED
        title = str(row.get("title", "")).strip()
        if not title:
            errors.append(
                {"row": row_num, "field": "title", "message": "Title is required and cannot be empty"}
            )
            skipped += 1
            continue

        # Price is REQUIRED
        price = None
        raw_price = (
            str(row.get("price", ""))
            .strip()
            .replace(",", "")
            .replace("$", "")
            .replace("€", "")
            .replace("£", "")
            .replace("¥", "")
        )

        if not raw_price:
            errors.append(
                {
                    "row": row_num,
                    "field": "price",
                    "message": "Price is required and cannot be empty",
                }
            )
            skipped += 1
            continue

        try:
            price = Decimal(raw_price)
            if price < 0:
                errors.append(
                    {
                        "row": row_num,
                        "field": "price",
                        "message": f"Negative price: {raw_price}",
                    }
                )
                skipped += 1
                continue
        except InvalidOperation:
            errors.append(
                {
                    "row": row_num,
                    "field": "price",
                    "message": f"Invalid price format: {raw_price}",
                }
            )
            skipped += 1
            continue

        # Coerce stock (optional, default: 0)
        stock = 0
        raw_stock = str(row.get("stock", "")).strip()
        if raw_stock:
            try:
                stock = int(float(raw_stock))
                if stock < 0:
                    stock = 0
            except (ValueError, TypeError):
                errors.append(
                    {
                        "row": row_num,
                        "field": "stock",
                        "message": f"Invalid stock value: {raw_stock}",
                    }
                )
                stock = 0

        # Parse attributes (JSON string or leave as empty dict)
        attributes: dict[str, Any] = {}
        raw_attrs = str(row.get("attributes", "")).strip()
        if raw_attrs:
            try:
                parsed = json.loads(raw_attrs)
                if isinstance(parsed, dict):
                    attributes = parsed
                else:
                    attributes = {"raw": parsed}
            except json.JSONDecodeError:
                attributes = {"raw": raw_attrs}

        # Preserve unmapped columns as key-value pairs in attributes
        for unmapped_col in unmapped_columns:
            val = str(raw_row.get(unmapped_col, "")).strip()
            if val:
                attributes[unmapped_col] = val

        cleaned = {
            "title": title,
            "description": str(row.get("description", "")).strip() or None,
            "price": price,
            "category": str(row.get("category", "")).strip() or None,
            "attributes": attributes,
            "image_url": str(row.get("image_url", "")).strip() or None,
            "stock": stock,
        }
        rows.append(cleaned)

    return {
        "rows": rows,
        "total_rows": total_rows,
        "ingested_rows": len(rows),
        "skipped_rows": skipped,
        "inferred_mapping": inferred_mapping_result,
        "unmapped_columns": unmapped_columns,
        "errors": errors,
    }
