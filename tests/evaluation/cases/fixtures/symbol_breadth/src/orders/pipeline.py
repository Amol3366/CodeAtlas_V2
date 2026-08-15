"""The order pipeline, and the enum it advances through."""

from __future__ import annotations

from enum import Enum

from src.orders.repository import OrderRepository


class OrderStage(Enum):
    """Stages an order passes through."""

    DRAFT = "draft"
    PLACED = "placed"


class OrderPipeline:
    """Advances an order to its next stage."""

    def __init__(self, repository: OrderRepository) -> None:
        self.repository = repository

    def advance(self, order_id: str) -> OrderStage:
        return OrderStage.PLACED


def run_pipeline(pipeline: OrderPipeline, order_id: str) -> OrderStage:
    return pipeline.advance(order_id)
