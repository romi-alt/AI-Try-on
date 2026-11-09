from pydantic import BaseModel


class StatsOut(BaseModel):
    garments_active: int
    sessions_today: int
    jobs_today: int
    jobs_failed_today: int
    queue_depth: int
