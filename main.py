import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

import psycopg2
from fastapi import FastAPI

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def check_database_connection() -> bool:
    database_url = os.getenv("DATABASE_URL")

    if not database_url:
        logger.warning("DATABASE_URL is not set; skipping PostgreSQL connection check.")
        return False

    connection = None

    try:
        connection = psycopg2.connect(
            database_url,
            connect_timeout=10,
        )

        with connection.cursor() as cursor:
            cursor.execute("SELECT 1;")
            cursor.fetchone()

        logger.info("PostgreSQL connection established successfully.")
        return True
    except psycopg2.Error:
        logger.exception("Unable to connect to PostgreSQL.")
        return False
    finally:
        if connection is not None:
            connection.close()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.database_connected = check_database_connection()
    yield


app = FastAPI(
    title="Project Nexus",
    lifespan=lifespan,
)


@app.get("/")
def home() -> dict[str, str]:
    return {
        "status": "Project Nexus Active",
        "database": "Connected",
    }
