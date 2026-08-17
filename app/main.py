from fastapi import FastAPI
import socket

app = FastAPI(title="Docker Task Platform")


@app.get("/")
def root():
    return {
        "message": "Docker Task Platform is running",
        "hostname": socket.gethostname()
    }


@app.get("/health")
def health():
    return {
        "status": "healthy"
    }