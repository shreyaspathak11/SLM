"""Pydantic schema for a row of the Products table."""

from pydantic import BaseModel


class Product(BaseModel):
    id: int
    name: str
    category: str
    supplier_id: int
    unit_cost: float
    price: float
    stock_quantity: int

