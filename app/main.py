from fastapi import FastAPI
from app.api import bills, search

app = FastAPI(title="Bill Retrieval API", version="0.1.0")
app.include_router(bills.router, prefix="/api")
app.include_router(search.router, prefix="/api")
