"""
pytest fixtures — shared across all test modules.

Provides:
- client: httpx AsyncClient with ASGITransport
- sample_python_code: sample code with hardcoded key, SQL injection, long function
- sample_files: reusable file list fixture
"""

import asyncio
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.fixture(scope="session")
def event_loop():
    """Create a session-scoped event loop."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    """Async HTTP client for testing FastAPI app."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def sample_python_code() -> str:
    """Sample Python code containing multiple issues for testing.

    Contains:
    - Hardcoded API key (security)
    - SQL injection (security)
    - Long function (style)
    - Nested loops (performance)
    """
    return r'''
"""Sample module with intentional issues for testing."""

API_KEY = "sk-proj-abc123def456ghi789jkl012mno345pqr678stu901vwx234yz"

import sqlite3
import os

def get_user(user_id):
    """Vulnerable to SQL injection."""
    conn = sqlite3.connect("users.db")
    query = f"SELECT * FROM users WHERE id = {user_id}"
    return conn.execute(query).fetchall()

def long_function():
    """A function that is intentionally long for testing."""
    result = []
    for i in range(10):
        result.append(i)
    for i in range(10):
        result.append(i * 2)
    for i in range(10):
        result.append(i * 3)
    for j in range(10):
        result.append(j)
    for j in range(10):
        result.append(j * 2)
    for j in range(10):
        result.append(j * 3)
    for k in range(10):
        result.append(k)
    for k in range(10):
        result.append(k * 2)
    for k in range(10):
        result.append(k * 3)
    for m in range(10):
        result.append(m)
    for m in range(10):
        result.append(m * 2)
    for m in range(10):
        result.append(m * 3)
    for n in range(10):
        result.append(n)
    for n in range(10):
        result.append(n * 2)
    for n in range(10):
        result.append(n * 3)
    for x in range(10):
        result.append(x)
    for x in range(10):
        result.append(x * 2)
    for x in range(10):
        result.append(x * 3)
    for y in range(10):
        result.append(y)
    for y in range(10):
        result.append(y * 2)
    for y in range(10):
        result.append(y * 3)
    for a in range(5):
        for b in range(5):
            for c in range(5):
                result.append((a, b, c))
    return result


def good_function():
    """A well-structured function."""
    return sum(range(100))
'''


@pytest.fixture
def sample_files(sample_python_code: str) -> list[dict[str, str]]:
    """Sample files for review testing."""
    return [
        {"path": "src/main.py", "content": sample_python_code},
    ]


@pytest.fixture
def sample_go_code() -> str:
    """Sample Go code for multi-language testing."""
    return '''package main

import (
    "database/sql"
    "fmt"
    "net/http"
)

// VeryLongFunction demonstrates a function that exceeds recommended line count.
func VeryLongFunction() error {
    fmt.Println("line 1")
    fmt.Println("line 2")
    fmt.Println("line 3")
    fmt.Println("line 4")
    fmt.Println("line 5")
    fmt.Println("line 6")
    fmt.Println("line 7")
    fmt.Println("line 8")
    fmt.Println("line 9")
    fmt.Println("line 10")
    fmt.Println("line 11")
    fmt.Println("line 12")
    fmt.Println("line 13")
    fmt.Println("line 14")
    fmt.Println("line 15")
    fmt.Println("line 16")
    fmt.Println("line 17")
    fmt.Println("line 18")
    fmt.Println("line 19")
    fmt.Println("line 20")
    fmt.Println("line 21")
    fmt.Println("line 22")
    fmt.Println("line 23")
    fmt.Println("line 24")
    fmt.Println("line 25")
    fmt.Println("line 26")
    fmt.Println("line 27")
    fmt.Println("line 28")
    fmt.Println("line 29")
    fmt.Println("line 30")
    fmt.Println("line 31")
    fmt.Println("line 32")
    fmt.Println("line 33")
    fmt.Println("line 34")
    fmt.Println("line 35")
    fmt.Println("line 36")
    fmt.Println("line 37")
    fmt.Println("line 38")
    fmt.Println("line 39")
    fmt.Println("line 40")
    fmt.Println("line 41")
    fmt.Println("line 42")
    fmt.Println("line 43")
    fmt.Println("line 44")
    fmt.Println("line 45")
    fmt.Println("line 46")
    fmt.Println("line 47")
    fmt.Println("line 48")
    fmt.Println("line 49")
    fmt.Println("line 50")
    fmt.Println("line 51")
    fmt.Println("line 52")
    fmt.Println("line 53")
    fmt.Println("line 54")
    fmt.Println("line 55")
    fmt.Println("line 56")
    fmt.Println("line 57")
    fmt.Println("line 58")
    fmt.Println("line 59")
    fmt.Println("line 60")
    fmt.Println("line 61")
    fmt.Println("line 62")
    fmt.Println("line 63")
    fmt.Println("line 64")
    fmt.Println("line 65")
    fmt.Println("line 66")
    fmt.Println("line 67")
    fmt.Println("line 68")
    fmt.Println("line 69")
    fmt.Println("line 70")
    fmt.Println("line 71")
    fmt.Println("line 72")
    fmt.Println("line 73")
    fmt.Println("line 74")
    fmt.Println("line 75")
    fmt.Println("line 76")
    fmt.Println("line 77")
    fmt.Println("line 78")
    fmt.Println("line 79")
    fmt.Println("line 80")
    fmt.Println("line 81")
    fmt.Println("line 82")
    return nil
}

func GoodFunction() int {
    return 42
}
'''
