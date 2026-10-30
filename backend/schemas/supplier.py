"""Pydantic schema for a row of the Suppliers table."""

from pydantic import BaseModel


class Supplier(BaseModel):
    id: int
    name: str
    country: str
    reliability_score: float
    lead_time_days: int

