"""Extraction tools. The JSON schema IS the output contract - tool_use makes the
response schema-valid by construction, so nothing here re-parses model prose."""

_MONEY = {"type": ["number", "null"]}

_CONFIDENCE = {
    "type": "object",
    "description": (
        "Per-field confidence 0.0-1.0. Score each field on how directly the source "
        "supports it: 1.0 the value is printed verbatim, 0.5 it was inferred or the "
        "source is ambiguous, 0.0 you could not find it. Do not report a single "
        "document-level score - low confidence on one field is what routes a record "
        "to a human."
    ),
    "properties": {
        "vendor_name": {"type": "number"},
        "document_number": {"type": "number"},
        "issue_date": {"type": "number"},
        "currency": {"type": "number"},
        "line_items": {"type": "number"},
        "stated_total": {"type": "number"},
        "payment_terms": {"type": "number"},
    },
    "required": [
        "vendor_name",
        "document_number",
        "issue_date",
        "currency",
        "line_items",
        "stated_total",
        "payment_terms",
    ],
    "additionalProperties": False,
}

_LINE_ITEM = {
    "type": "object",
    "properties": {
        "description": {"type": "string"},
        "quantity": {"type": ["number", "null"]},
        "unit_price": _MONEY,
        "amount": {"type": "number", "description": "Line total as printed."},
    },
    "required": ["description", "quantity", "unit_price", "amount"],
    "additionalProperties": False,
}

# Every field a source document may legitimately omit is nullable. A required
# non-nullable field is an instruction to invent a value.
_COMMON = {
    "vendor_name": {"type": ["string", "null"]},
    "document_number": {"type": ["string", "null"]},
    "issue_date": {
        "type": ["string", "null"],
        "description": "ISO 8601 date, YYYY-MM-DD. Normalise 3/4/26 and 4 Mar 2026 alike.",
    },
    "currency": {
        "type": "string",
        "enum": ["USD", "EUR", "GBP", "LKR", "unclear", "other"],
    },
    "currency_detail": {
        "type": ["string", "null"],
        "description": "ISO code when currency is 'other'; else null.",
    },
    "line_items": {"type": "array", "items": _LINE_ITEM},
    "stated_total": {
        **_MONEY,
        "description": "The total as printed on the document. Never compute this one.",
    },
    "calculated_total": {
        "type": ["number", "null"],
        "description": "Sum of line_items[].amount. Extracted separately from stated_total so a mismatch is detectable.",
    },
    "conflict_detected": {
        "type": "boolean",
        "description": "True when the source contradicts itself (two different totals, a date that disagrees with the period).",
    },
    "conflict_note": {"type": ["string", "null"]},
    "field_confidence": _CONFIDENCE,
}

INVOICE_TOOL = {
    "name": "extract_invoice",
    "description": (
        "Record the fields of a supplier INVOICE - a demand for payment, carrying an "
        "invoice number and payment terms. Use this rather than extract_receipt when "
        "the document asks for money that has not been paid yet."
    ),
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            **_COMMON,
            "payment_terms": {
                "type": "string",
                "enum": ["net_15", "net_30", "net_60", "due_on_receipt", "unclear", "other"],
                "description": "'unclear' when the document is ambiguous; 'other' for a real term outside this list.",
            },
            "payment_terms_detail": {
                "type": ["string", "null"],
                "description": "The verbatim term when payment_terms is 'other'; else null.",
            },
            "purchase_order": {"type": ["string", "null"]},
        },
        "required": [
            *_COMMON,
            "payment_terms",
            "payment_terms_detail",
            "purchase_order",
        ],
        "additionalProperties": False,
    },
}

RECEIPT_TOOL = {
    "name": "extract_receipt",
    "description": (
        "Record the fields of a RECEIPT - proof that money has already been paid, "
        "carrying a payment method and usually no payment terms. Use this rather than "
        "extract_invoice when the document confirms a completed payment."
    ),
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            **_COMMON,
            "payment_method": {
                "type": "string",
                "enum": ["card", "cash", "bank_transfer", "unclear", "other"],
            },
            "payment_method_detail": {"type": ["string", "null"]},
        },
        "required": [*_COMMON, "payment_method", "payment_method_detail"],
        "additionalProperties": False,
    },
}

TOOLS = [INVOICE_TOOL, RECEIPT_TOOL]
TOOLS_BY_NAME = {t["name"]: t for t in TOOLS}
