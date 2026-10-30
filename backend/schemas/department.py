"""Pydantic schema for a row of the Departments table."""

from pydantic import BaseModel


class Department(BaseModel):
    id: int
    name: str
    budget: float
    head_office: str

