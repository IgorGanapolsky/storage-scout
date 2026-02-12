#!/usr/bin/env python3
"""
FastAPI Server for Agentic Commerce

Exposes tool rental catalog via REST API for AI agent discovery.
Deploy to Railway, Render, or any Docker host.

Run locally:
    pip install fastapi uvicorn
    uvicorn api_server:app --reload --port 8000

Endpoints:
    GET  /                     - API info
    GET  /catalog              - Full catalog (JSON-LD)
    GET  /catalog/ucp          - UCP format catalog
    GET  /products/{id}        - Single product
    POST /query                - Agent query handler
    GET  /availability/{id}    - Check availability
    POST /quote                - Get rental quote
    POST /reserve              - Create reservation
"""

import os
from datetime import datetime
from typing import Optional

try:
    from fastapi import FastAPI, HTTPException, Query
    from fastapi.middleware.cors import CORSMiddleware
    from pydantic import BaseModel
except ImportError:
    print("FastAPI not installed. Run: pip install fastapi uvicorn")
    exit(1)

from agent_commerce import AgentCommerceCatalog
from config import LOCATION

# Initialize FastAPI
app = FastAPI(
    title="Igor's Tool Rentals - Agentic Commerce API",
    description="Machine-readable API for AI shopping agents. Implements Universal Commerce Protocol patterns.",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS configuration
# Define allowed origins explicitly for security
# In production, restrict to specific domains
ALLOWED_ORIGINS = os.environ.get(
    "CORS_ORIGINS",
    "http://localhost:3000,http://localhost:8080,https://igorganapolsky.github.io"
).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Requested-With"],
)

# Initialize catalog with sample data (replace with real inventory)
SAMPLE_INVENTORY = [
    {
        "id": "pw-001",
        "name": "Ryobi 2300 PSI Electric Pressure Washer",
        "category": "pressure_washer",
        "brand": "Ryobi",
        "condition": "excellent",
        "daily_rate": 40,
        "weekly_rate": 150,
    },
    {
        "id": "cc-001",
        "name": "Bissell ProHeat Carpet Cleaner",
        "category": "carpet_cleaner",
        "brand": "Bissell",
        "condition": "good",
        "daily_rate": 35,
        "weekly_rate": 120,
    },
    {
        "id": "ts-001",
        "name": "DEWALT 10-inch Wet Tile Saw",
        "category": "tile_saw",
        "brand": "DEWALT",
        "condition": "excellent",
        "daily_rate": 50,
        "weekly_rate": 180,
    },
]

catalog = AgentCommerceCatalog(SAMPLE_INVENTORY)


# Request/Response Models
class AgentQuery(BaseModel):
    intent: str  # find_rental, check_availability, get_quote, book
    category: Optional[str] = None
    location: Optional[str] = None
    max_price: Optional[float] = None
    product_id: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    renter_info: Optional[dict] = None
    quote_id: Optional[str] = None


class QuoteRequest(BaseModel):
    product_id: str
    start_date: str
    end_date: str


class ReservationRequest(BaseModel):
    product_id: str
    quote_id: str
    renter_name: str
    renter_email: str
    renter_phone: str


# Routes
@app.get("/")
async def root():
    """API information for agent discovery."""
    return {
        "name": "Igor's Tool Rentals",
        "type": "rental_equipment",
        "ucp_version": "1.0",
        "location": LOCATION,
        "capabilities": {
            "instant_booking": True,
            "quotes": True,
            "availability_check": True,
        },
        "endpoints": {
            "catalog_jsonld": "/catalog",
            "catalog_ucp": "/catalog/ucp",
            "products": "/products/{product_id}",
            "query": "/query",
            "availability": "/availability/{product_id}",
            "quote": "/quote",
            "reserve": "/reserve",
        },
        "documentation": "/docs",
    }


@app.get("/catalog")
async def get_catalog_jsonld():
    """
    Get full catalog in JSON-LD format.
    Optimized for web embedding and SEO/GEO.
    """
    return catalog.get_full_catalog_jsonld()


@app.get("/catalog/ucp")
async def get_catalog_ucp():
    """
    Get catalog in Universal Commerce Protocol format.
    For agent-to-agent discovery.
    """
    return catalog.get_ucp_catalog()


@app.get("/products")
async def list_products(
    category: Optional[str] = Query(None, description="Filter by category"),
    max_price: Optional[float] = Query(None, description="Maximum daily price"),
):
    """List all products with optional filters."""
    products = []
    for product in catalog.products.values():
        if category and product.category != category:
            continue
        if max_price and product.price_daily > max_price:
            continue
        products.append(product.to_ucp_catalog_entry())

    return {
        "products": products,
        "count": len(products),
        "filters": {"category": category, "max_price": max_price},
    }


@app.get("/products/{product_id}")
async def get_product(product_id: str):
    """Get single product details."""
    if product_id not in catalog.products:
        raise HTTPException(status_code=404, detail="Product not found")

    return catalog.products[product_id].to_ucp_catalog_entry()


@app.post("/query")
async def handle_agent_query(query: AgentQuery):
    """
    Universal query handler for AI agents.

    Supports intents:
    - find_rental: Search for available rentals
    - check_availability: Check if product is available for dates
    - get_quote: Generate rental quote
    - book: Create reservation

    Example:
    {
        "intent": "find_rental",
        "category": "pressure_washer",
        "max_price": 50
    }
    """
    return catalog.handle_agent_query(query.dict())


@app.get("/availability/{product_id}")
async def check_availability(
    product_id: str,
    start_date: str = Query(..., description="Start date (YYYY-MM-DD)"),
    end_date: str = Query(..., description="End date (YYYY-MM-DD)"),
):
    """Check product availability for specific dates."""
    if product_id not in catalog.products:
        raise HTTPException(status_code=404, detail="Product not found")

    return catalog.booking_agent.check_availability(
        product_id, start_date, end_date
    )


@app.post("/quote")
async def get_quote(request: QuoteRequest):
    """Generate a rental quote."""
    if request.product_id not in catalog.products:
        raise HTTPException(status_code=404, detail="Product not found")

    product = catalog.products[request.product_id]
    return catalog.booking_agent.get_quote(
        request.product_id,
        request.start_date,
        request.end_date,
        product.price_daily,
        product.price_weekly,
    )


@app.post("/reserve")
async def create_reservation(request: ReservationRequest):
    """Create a reservation (hold before payment)."""
    if request.product_id not in catalog.products:
        raise HTTPException(status_code=404, detail="Product not found")

    renter_info = {
        "name": request.renter_name,
        "email": request.renter_email,
        "phone": request.renter_phone,
    }

    return catalog.booking_agent.create_reservation(
        request.product_id,
        request.quote_id,
        renter_info,
    )


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "products_count": len(catalog.products),
    }


# Agent-specific headers
@app.middleware("http")
async def add_agent_headers(request, call_next):
    """Add headers that help AI agents understand the API."""
    response = await call_next(request)
    response.headers["X-UCP-Version"] = "1.0"
    response.headers["X-Merchant-ID"] = "igor-tools-coral-springs"
    response.headers["X-API-Type"] = "agentic-commerce"
    return response


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 8000))
    host = os.environ.get("HOST", "127.0.0.1")
    uvicorn.run(app, host=host, port=port)
