"""Stand-in for the backend systems. Deliberately inconsistent: the CRM emits ISO 8601,
the order service emits unix seconds, and the fulfilment service emits numeric status
codes. Normalising that is a hook's job, not the model's."""

CUSTOMERS = [
    {
        "customer_id": "CUS-1001",
        "name": "Priya Raman",
        "email": "priya@example.com",
        "postcode": "SW1A 1AA",
        "tier": "standard",
        "created_at": "2024-11-02T09:14:00Z",
    },
    {
        "customer_id": "CUS-1002",
        "name": "Priya Raman",
        "email": "p.raman@example.net",
        "postcode": "EC1V 9BX",
        "tier": "priority",
        "created_at": "2025-06-18T16:02:00Z",
    },
    {
        "customer_id": "CUS-1003",
        "name": "Tomas Neder",
        "email": "tomas@example.com",
        "postcode": "M1 4BT",
        "tier": "standard",
        "created_at": "2023-02-01T11:00:00Z",
    },
]

# Numeric codes as the fulfilment service emits them.
STATUS_CODES = {10: "placed", 20: "shipped", 30: "delivered", 40: "returned", 90: "cancelled"}

ORDERS = [
    {
        "order_id": "ORD-55120",
        "customer_id": "CUS-1001",
        "status_code": 30,
        "placed_at": 1771286400,
        "delivered_at": 1771718400,
        "total": 128.40,
        "currency": "GBP",
        "items": [{"sku": "KB-11", "name": "Keyboard", "qty": 1, "price": 128.40}],
        "refundable": True,
        "warehouse_zone": "LDN-3",
        "carrier_ref": "TRK-889201",
        "picker_id": "EMP-224",
        "packaging_class": "B",
        "route_hash": "9f2c11ab",
        "insurance_band": 2,
    },
    {
        "order_id": "ORD-55121",
        "customer_id": "CUS-1001",
        "status_code": 20,
        "placed_at": 1774051200,
        "delivered_at": None,
        "total": 940.00,
        "currency": "GBP",
        "items": [{"sku": "MON-32", "name": "Monitor", "qty": 1, "price": 940.00}],
        "refundable": True,
        "warehouse_zone": "LDN-1",
        "carrier_ref": "TRK-889444",
        "picker_id": "EMP-108",
        "packaging_class": "A",
        "route_hash": "31be07cc",
        "insurance_band": 4,
    },
    {
        "order_id": "ORD-55190",
        "customer_id": "CUS-1003",
        "status_code": 40,
        "placed_at": 1769040000,
        "delivered_at": 1769472000,
        "total": 62.00,
        "currency": "GBP",
        "items": [{"sku": "CBL-2", "name": "Cable", "qty": 2, "price": 31.00}],
        "refundable": False,
        "warehouse_zone": "MAN-2",
        "carrier_ref": "TRK-771002",
        "picker_id": "EMP-511",
        "packaging_class": "C",
        "route_hash": "aa0912ff",
        "insurance_band": 1,
    },
]

REFUNDS: list[dict] = []


def find_customers(email=None, order_id=None, postcode=None) -> list[dict]:
    matches = CUSTOMERS
    if email:
        matches = [c for c in matches if c["email"].lower() == email.lower()]
    if postcode:
        matches = [c for c in matches if c["postcode"].replace(" ", "").upper() == postcode.replace(" ", "").upper()]
    if order_id:
        owners = {o["customer_id"] for o in ORDERS if o["order_id"] == order_id}
        matches = [c for c in matches if c["customer_id"] in owners]
    return list(matches)


def find_orders(customer_id=None, order_id=None) -> list[dict]:
    matches = ORDERS
    if customer_id:
        matches = [o for o in matches if o["customer_id"] == customer_id]
    if order_id:
        matches = [o for o in matches if o["order_id"] == order_id]
    return list(matches)


def record_refund(order_id: str, amount: float, reason: str) -> dict:
    refund = {"refund_id": f"REF-{len(REFUNDS) + 9001}", "order_id": order_id, "amount": amount, "reason": reason}
    REFUNDS.append(refund)
    return refund


def reset() -> None:
    REFUNDS.clear()
