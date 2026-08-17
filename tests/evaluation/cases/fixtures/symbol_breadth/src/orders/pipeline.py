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


def start_pipeline(pipeline: OrderPipeline, order_id: str) -> OrderStage:
    """Entry point, one hop above `run_pipeline`.

    Exists so this fixture holds a two-hop call chain: a caller of `advance`
    reached only through another caller. Without one, no symbol-intent case
    here can be ranking-sensitive -- every returned symbol is a direct answer,
    so any order passes and a reversal changes nothing.
    """
    return run_pipeline(pipeline, order_id)
