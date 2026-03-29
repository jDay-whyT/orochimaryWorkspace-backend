"""Rent search service — parallel Booking.com + Airbnb via RapidAPI."""
import asyncio
import logging
from dataclasses import dataclass
from datetime import date

import httpx

LOGGER = logging.getLogger(__name__)

BOOKING_HOST = "booking-com15.p.rapidapi.com"
AIRBNB_HOST = "airbnb19.p.rapidapi.com"
TIMEOUT = 10


@dataclass
class RentListing:
    source: str  # "booking" | "airbnb"
    name: str
    price_per_night: float
    rating: float | None
    url: str


async def _search_booking(
    city: str,
    checkin: date,
    checkout: date,
    budget: int,
    api_key: str,
) -> list[RentListing]:
    nights = (checkout - checkin).days or 1
    headers = {
        "x-rapidapi-host": BOOKING_HOST,
        "x-rapidapi-key": api_key,
    }
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        r = await client.get(
            f"https://{BOOKING_HOST}/api/v1/hotels/searchDestination",
            params={"query": city},
            headers=headers,
        )
        r.raise_for_status()
        dest_data = r.json().get("data", [])
        if not dest_data:
            return []
        dest_id = dest_data[0]["dest_id"]
        search_type = dest_data[0]["search_type"]

        r2 = await client.get(
            f"https://{BOOKING_HOST}/api/v1/hotels/searchHotels",
            params={
                "dest_id": dest_id,
                "search_type": search_type,
                "arrival_date": checkin.isoformat(),
                "departure_date": checkout.isoformat(),
                "adults": 1,
                "room_qty": 1,
                "page_number": 1,
                "sort_by": "popularity",
                "currency_code": "USD",
                "price_max": budget,
            },
            headers=headers,
        )
        r2.raise_for_status()
        hotels = r2.json().get("data", {}).get("hotels", [])

    results: list[RentListing] = []
    for h in hotels:
        prop = h.get("property", {})
        gross = prop.get("priceBreakdown", {}).get("grossPrice", {}).get("value")
        if gross is None:
            continue
        country = prop.get("countryCode", "")
        hotel_id = prop.get("id", "")
        score = prop.get("reviewScore")
        results.append(RentListing(
            source="booking",
            name=prop.get("name", ""),
            price_per_night=gross / nights,
            rating=float(score) if score else None,
            url=f"https://www.booking.com/hotel/{country}/{hotel_id}.html",
        ))
    return results


async def _search_airbnb(
    city: str,
    checkin: date,
    checkout: date,
    budget: int,
    api_key: str,
) -> list[RentListing]:
    headers = {
        "x-rapidapi-host": AIRBNB_HOST,
        "x-rapidapi-key": api_key,
    }
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        r = await client.get(
            f"https://{AIRBNB_HOST}/api/v2/searchPropertyByLocation",
            params={
                "location": city,
                "checkin": checkin.isoformat(),
                "checkout": checkout.isoformat(),
                "adults": 1,
                "totalRecords": 20,
                "currency": "USD",
                "priceMax": budget,
            },
            headers=headers,
        )
        r.raise_for_status()
        items = r.json().get("data", {}).get("list", [])

    results: list[RentListing] = []
    for item in items:
        listing = item.get("listing", {})
        listing_id = listing.get("id", "")

        price_str: str = (
            item.get("pricingQuote", {})
            .get("structuredStayDisplayPrice", {})
            .get("primaryLine", {})
            .get("price", "")
        )
        try:
            price_per_night = float(price_str.replace("$", "").replace(",", "").strip())
        except (ValueError, AttributeError):
            continue

        rating: float | None = None
        try:
            rating = float(str(listing.get("avgRatingLocalized", "")).split()[0])
        except (ValueError, IndexError, AttributeError):
            pass

        results.append(RentListing(
            source="airbnb",
            name=listing.get("name", ""),
            price_per_night=price_per_night,
            rating=rating,
            url=f"https://www.airbnb.com/rooms/{listing_id}",
        ))
    return results


async def search_rentals(
    city: str,
    checkin: date,
    checkout: date,
    budget: int,
    api_key: str,
) -> list[RentListing]:
    """Search Booking.com and Airbnb in parallel, return up to 10 results sorted by price."""
    booking_task = _search_booking(city, checkin, checkout, budget, api_key)
    airbnb_task = _search_airbnb(city, checkin, checkout, budget, api_key)

    raw = await asyncio.gather(booking_task, airbnb_task, return_exceptions=True)

    combined: list[RentListing] = []
    for result in raw:
        if isinstance(result, Exception):
            LOGGER.warning("Rent search partial failure: %s", result)
            continue
        combined.extend(result)

    combined.sort(key=lambda x: x.price_per_night)
    return combined[:10]
