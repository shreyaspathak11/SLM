"""Pydantic schema for a row of the Reviews table."""

from datetime import date

from pydantic import BaseModel, Field


class Review(BaseModel):
    id: int
    product_id: int
    user_id: int
    rating: int = Field(ge=1, le=5)
    review_date: date

