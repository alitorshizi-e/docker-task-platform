import json
import os
import socket
import time
from contextlib import asynccontextmanager

import psycopg
import redis
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel


DB_HOST = os.getenv("DB_HOST", "db")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "taskdb")
DB_USER = os.getenv("DB_USER", "taskuser")
DB_PASSWORD = os.getenv("DB_PASSWORD")

REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))


def get_db_connection():
    return psycopg.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
    )


redis_client = redis.Redis(
    host=REDIS_HOST,
    port=REDIS_PORT,
    decode_responses=True,
)


def initialize_database():
    max_attempts = 10

    for attempt in range(1, max_attempts + 1):
        try:
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS tasks (
                            id SERIAL PRIMARY KEY,
                            title VARCHAR(255) NOT NULL,
                            completed BOOLEAN NOT NULL DEFAULT FALSE
                        )
                        """
                    )

                conn.commit()

            print("Database initialization completed")
            return

        except psycopg.OperationalError as error:
            print(
                f"Database connection attempt "
                f"{attempt}/{max_attempts} failed: {error}"
            )

            if attempt == max_attempts:
                raise

            time.sleep(2)


@asynccontextmanager
async def lifespan(app: FastAPI):
    initialize_database()
    yield


app = FastAPI(
    title="Docker Task Platform",
    lifespan=lifespan,
)


class TaskCreate(BaseModel):
    title: str


@app.get("/")
def root():
    return {
        "message": "Docker Task Platform is running",
        "hostname": socket.gethostname(),
    }


@app.get("/health/live")
def liveness():
    return {
        "status": "alive"
    }


@app.get("/health/ready")
def readiness():
    dependencies = {
        "postgresql": False,
        "redis": False,
    }

    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()

        dependencies["postgresql"] = True

    except Exception:
        pass

    try:
        dependencies["redis"] = bool(redis_client.ping())

    except Exception:
        pass

    if not all(dependencies.values()):
        raise HTTPException(
            status_code=503,
            detail={
                "status": "not_ready",
                "dependencies": dependencies,
            },
        )

    return {
        "status": "ready",
        "dependencies": dependencies,
    }


@app.get("/health")
def health():
    return readiness()


@app.post("/tasks", status_code=201)
def create_task(task: TaskCreate):
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO tasks (title)
                    VALUES (%s)
                    RETURNING id, title, completed
                    """,
                    (task.title,),
                )

                row = cursor.fetchone()

            conn.commit()

        redis_client.delete("tasks:all")

        return {
            "id": row[0],
            "title": row[1],
            "completed": row[2],
        }

    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=str(error),
        )


@app.get("/tasks")
def list_tasks():
    try:
        cached_tasks = redis_client.get("tasks:all")

        if cached_tasks:
            return {
                "source": "redis",
                "tasks": json.loads(cached_tasks),
            }

        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, title, completed
                    FROM tasks
                    ORDER BY id
                    """
                )

                rows = cursor.fetchall()

        tasks = [
            {
                "id": row[0],
                "title": row[1],
                "completed": row[2],
            }
            for row in rows
        ]

        redis_client.setex(
            "tasks:all",
            30,
            json.dumps(tasks),
        )

        return {
            "source": "postgresql",
            "tasks": tasks,
        }

    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=str(error),
        )