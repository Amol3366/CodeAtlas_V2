from src.orders.pipeline import OrderPipeline
from src.orders.repository import OrderRepository


def test_pipeline_advances() -> None:
    pipeline = OrderPipeline(OrderRepository({}))
    assert pipeline.advance("o1")
