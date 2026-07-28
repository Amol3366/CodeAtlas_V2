def get_order(order_id: str) -> dict[str, str]:
    return {"id": order_id, "status": "ready"}

def health() -> str:
    checked = "ok"
    return "ok"
