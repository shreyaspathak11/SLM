"""Pydantic schema for a row of the Employees table."""

from datetime import date

from pydantic import BaseModel


class Employee(BaseModel):
    id: int
    name: str
    department_id: int
    role: str
    salary: float
    hire_date: date
    region: str

