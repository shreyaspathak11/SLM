"""Enterprise analytics database generator for stress-testing Text-to-SQL SLMs.

Creates an SQLite database (analytics.db) with 7 normalized tables and 75,000+ records:
- Departments (8 rows)
- Employees (250 rows)
- Suppliers (100 rows)
- Users (5,000 rows)
- Products (500 rows)
- Orders (50,000 rows)
- Reviews (20,000 rows)
"""

from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
import random
import sqlite3

from backend.config import DATABASE_PATH


def create_database(db_path: Path = DATABASE_PATH) -> None:
    """Create a 7-table enterprise relational schema and seed 75,858 rows."""
    random.seed(42)

    if db_path.exists():
        db_path.unlink()

    connection = sqlite3.connect(db_path)
    cursor = connection.cursor()
    cursor.execute("PRAGMA synchronous = OFF;")
    cursor.execute("PRAGMA journal_mode = MEMORY;")

    # 1. Create normalized relational schema
    cursor.executescript(
        """
        CREATE TABLE Departments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            budget REAL NOT NULL,
            head_office TEXT NOT NULL
        );

        CREATE TABLE Employees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            department_id INTEGER NOT NULL,
            role TEXT NOT NULL,
            salary REAL NOT NULL,
            hire_date TEXT NOT NULL,
            region TEXT NOT NULL,
            FOREIGN KEY (department_id) REFERENCES Departments(id)
        );

        CREATE TABLE Suppliers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            country TEXT NOT NULL,
            reliability_score REAL NOT NULL,
            lead_time_days INTEGER NOT NULL
        );

        CREATE TABLE Users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            tier TEXT NOT NULL,
            signup_date TEXT NOT NULL,
            region TEXT NOT NULL
        );

        CREATE TABLE Products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            supplier_id INTEGER NOT NULL,
            unit_cost REAL NOT NULL,
            price REAL NOT NULL,
            stock_quantity INTEGER NOT NULL,
            FOREIGN KEY (supplier_id) REFERENCES Suppliers(id)
        );

        CREATE TABLE Orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            employee_id INTEGER NOT NULL,
            order_date TEXT NOT NULL,
            status TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            FOREIGN KEY (user_id) REFERENCES Users(id),
            FOREIGN KEY (product_id) REFERENCES Products(id),
            FOREIGN KEY (employee_id) REFERENCES Employees(id)
        );

        CREATE TABLE Reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            rating INTEGER NOT NULL,
            review_date TEXT NOT NULL,
            FOREIGN KEY (product_id) REFERENCES Products(id),
            FOREIGN KEY (user_id) REFERENCES Users(id)
        );
        """
    )

    regions = ["North America", "Europe", "Asia-Pacific", "Latin America", "Middle East"]
    countries = ["USA", "Germany", "Japan", "UK", "India", "Canada", "Brazil", "UAE", "France", "South Korea"]
    first_names = [
        "James", "Mary", "John", "Patricia", "Robert", "Jennifer", "Michael", "Linda",
        "William", "Elizabeth", "David", "Barbara", "Richard", "Susan", "Joseph", "Jessica",
        "Thomas", "Sarah", "Charles", "Karen", "Christopher", "Nancy", "Daniel", "Lisa",
        "Matthew", "Betty", "Anthony", "Margaret", "Mark", "Sandra", "Donald", "Ashley",
        "Steven", "Kimberly", "Paul", "Emily", "Andrew", "Donna", "Joshua", "Michelle",
    ]
    last_names = [
        "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis",
        "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez", "Wilson", "Anderson",
        "Thomas", "Taylor", "Moore", "Jackson", "Martin", "Lee", "Perez", "Thompson",
        "White", "Harris", "Sanchez", "Clark", "Ramirez", "Lewis", "Robinson", "Walker",
    ]

    # 2. Seed Departments (8 rows)
    departments_data = [
        ("Sales", 2500000.0, "New York"),
        ("Engineering", 4200000.0, "San Francisco"),
        ("Marketing", 1800000.0, "London"),
        ("Operations", 1500000.0, "Berlin"),
        ("Logistics", 2100000.0, "Tokyo"),
        ("Customer Success", 1200000.0, "Toronto"),
        ("Finance", 950000.0, "New York"),
        ("Procurement", 1100000.0, "Singapore"),
    ]
    cursor.executemany(
        "INSERT INTO Departments (name, budget, head_office) VALUES (?, ?, ?);",
        departments_data,
    )

    # 3. Seed Employees (250 rows)
    roles = ["Account Executive", "Sales Manager", "Support Specialist", "Operations Analyst", "Solutions Architect"]
    emp_base_date = datetime(2020, 1, 1)
    employees_data = [
        (
            f"{random.choice(first_names)} {random.choice(last_names)}",
            random.randint(1, len(departments_data)),
            random.choice(roles),
            round(random.uniform(55000, 165000), 2),
            (emp_base_date + timedelta(days=random.randint(0, 1400))).strftime("%Y-%m-%d"),
            random.choice(regions),
        )
        for _ in range(250)
    ]
    cursor.executemany(
        "INSERT INTO Employees (name, department_id, role, salary, hire_date, region) VALUES (?, ?, ?, ?, ?, ?);",
        employees_data,
    )

    # 4. Seed Suppliers (100 rows)
    supplier_prefixes = ["Apex", "Global", "Vertex", "Prime", "Nexus", "titan", "Omni", "Pacific", "Nordic", "Quantum"]
    supplier_suffixes = ["Logistics", "Manufacturing", "Components", "Supply Co", "Industries", "Distribution", "Tech"]
    suppliers_data = [
        (
            f"{supplier_prefixes[i % len(supplier_prefixes)]} {supplier_suffixes[i % len(supplier_suffixes)]} #{i + 1}",
            random.choice(countries),
            round(random.uniform(3.2, 5.0), 2),
            random.randint(3, 28),
        )
        for i in range(100)
    ]
    cursor.executemany(
        "INSERT INTO Suppliers (name, country, reliability_score, lead_time_days) VALUES (?, ?, ?, ?);",
        suppliers_data,
    )

    # 5. Seed Users (5,000 rows)
    tiers = ["Standard", "Pro", "Enterprise"]
    tier_weights = [0.65, 0.25, 0.10]
    user_base_date = datetime(2022, 1, 1)
    users_data = [
        (
            f"{random.choice(first_names)} {random.choice(last_names)}",
            random.choices(tiers, weights=tier_weights, k=1)[0],
            (user_base_date + timedelta(days=random.randint(0, 1000))).strftime("%Y-%m-%d"),
            random.choice(regions),
        )
        for _ in range(5000)
    ]
    cursor.executemany(
        "INSERT INTO Users (name, tier, signup_date, region) VALUES (?, ?, ?, ?);",
        users_data,
    )

    # 6. Seed Products (500 rows)
    categories = ["Electronics", "Furniture", "Kitchen", "Home", "Accessories", "Networking", "Storage"]
    adjectives = ["Pro", "Ultra", "Compact", "Ergonomic", "Smart", "Wireless", "Industrial", "Precision"]
    nouns = [
        "Monitor", "Keyboard", "Chair", "Desk", "Dock", "Router", "SSD", "Headphones",
        "Speaker", "Webcam", "Microphone", "Purifier", "Kettle", "Blender", "Backpack",
    ]
    products_data = []
    for i in range(500):
        category = random.choice(categories)
        name = f"{random.choice(adjectives)} {random.choice(nouns)} {100 + i}"
        unit_cost = round(random.uniform(12.0, 350.0), 2)
        markup = random.uniform(1.25, 2.10)
        price = round(unit_cost * markup, 2)
        stock_qty = random.randint(0, 800)
        supplier_id = random.randint(1, 100)
        products_data.append((name, category, supplier_id, unit_cost, price, stock_qty))

    cursor.executemany(
        "INSERT INTO Products (name, category, supplier_id, unit_cost, price, stock_quantity) VALUES (?, ?, ?, ?, ?, ?);",
        products_data,
    )

    # 7. Seed Orders (50,000 rows)
    statuses = ["Completed", "Shipped", "Processing", "Returned", "Cancelled"]
    status_weights = [0.72, 0.12, 0.06, 0.05, 0.05]
    order_base_date = datetime(2023, 1, 1)
    orders_data = [
        (
            random.randint(1, 5000),
            random.randint(1, 500),
            random.randint(1, 250),
            (order_base_date + timedelta(days=random.randint(0, 650))).strftime("%Y-%m-%d"),
            random.choices(statuses, weights=status_weights, k=1)[0],
            random.randint(1, 10),
        )
        for _ in range(50000)
    ]
    cursor.executemany(
        "INSERT INTO Orders (user_id, product_id, employee_id, order_date, status, quantity) VALUES (?, ?, ?, ?, ?, ?);",
        orders_data,
    )

    # 8. Seed Reviews (20,000 rows)
    reviews_data = [
        (
            random.randint(1, 500),
            random.randint(1, 5000),
            random.choices([1, 2, 3, 4, 5], weights=[0.06, 0.08, 0.16, 0.35, 0.35], k=1)[0],
            (order_base_date + timedelta(days=random.randint(10, 660))).strftime("%Y-%m-%d"),
        )
        for _ in range(20000)
    ]
    cursor.executemany(
        "INSERT INTO Reviews (product_id, user_id, rating, review_date) VALUES (?, ?, ?, ?);",
        reviews_data,
    )

    # 9. Create performance indexes for large-scale join & filter operations
    cursor.executescript(
        """
        CREATE INDEX idx_users_region ON Users(region);
        CREATE INDEX idx_users_tier ON Users(tier);
        CREATE INDEX idx_products_category ON Products(category);
        CREATE INDEX idx_products_supplier ON Products(supplier_id);
        CREATE INDEX idx_orders_user ON Orders(user_id);
        CREATE INDEX idx_orders_product ON Orders(product_id);
        CREATE INDEX idx_orders_employee ON Orders(employee_id);
        CREATE INDEX idx_orders_status ON Orders(status);
        CREATE INDEX idx_orders_date ON Orders(order_date);
        CREATE INDEX idx_reviews_product ON Reviews(product_id);
        """
    )

    connection.commit()
    connection.close()
    print(f"Enterprise database created at {db_path} with 75,858 rows across 7 tables.")

def ensure_database(db_path: Path = DATABASE_PATH) -> None:
    """Create analytics.db when it is missing or does not contain the full 7-table dataset."""
    if db_path.exists():
        with closing(sqlite3.connect(f"{db_path.as_uri()}?mode=ro", uri=True)) as connection:
            tables = [
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%';"
                )
            ]
            total_rows = sum(connection.execute(f"SELECT COUNT(*) FROM {t};").fetchone()[0] for t in tables)
        if len(tables) >= 7 and total_rows >= 70000:
            return

    create_database(db_path)


if __name__ == "__main__":
    create_database()
