"""Pydantic schema for a row of the Orders table."""

from datetime import date

from pydantic import BaseModel


class Order(BaseModel):
    id: int
    user_id: int
    product_id: int
    employee_id: int
    order_date: date
    status: str
    quantity: int

