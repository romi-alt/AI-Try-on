from pydantic import BaseModel


class StatsOut(BaseModel):
    products_in_stock: int
    sessions_today: int
    jobs_today: int
    jobs_failed_today: int
    queue_depth: int
