"""Pydantic schema for a row of the Users table."""

from datetime import date

from pydantic import BaseModel


class User(BaseModel):
    id: int
    name: str
    tier: str
    signup_date: date
    region: str

