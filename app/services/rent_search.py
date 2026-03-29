"""Rent search service — parallel Booking.com + Airbnb via Apify."""
import asyncio
import logging
from dataclasses import dataclass
from datetime import date

import httpx

LOGGER = logging.getLogger(__name__)

APIFY_BASE = "https://api.apify.com"
CLIENT_TIMEOUT = 70
POLL_INTERVAL = 3
POLL_TIMEOUT = 60


@dataclass
class RentListing:
    source: str  # "booking" | "airbnb"
    name: str
    price_per_night: float
    rating: float | None
    url: str


async def _run_actor(
    actor_id: str,
    input_data: dict,
    apify_token: str,
) -> list[dict]:
    """Start an Apify actor, poll until done, return dataset items."""
    headers = {"Authorization": f"Bearer {apify_token}"}
    async with httpx.AsyncClient(timeout=CLIENT_TIMEOUT) as client:
        # Start actor run
        actor_id_url = actor_id.replace("/", "~")
        r = await client.post(
            f"{APIFY_BASE}/v2/acts/{actor_id_url}/runs?maxTotalChargeUsd=0.04",
            headers=headers,
            json=input_data,
        )
        r.raise_for_status()
        run_id = r.json()["data"]["id"]

        # Poll for completion
        elapsed = 0
        while elapsed < POLL_TIMEOUT:
            await asyncio.sleep(POLL_INTERVAL)
            elapsed += POLL_INTERVAL
            r = await client.get(
                f"{APIFY_BASE}/v2/actor-runs/{run_id}",
                headers=headers,
            )
            r.raise_for_status()
            status = r.json()["data"]["status"]
            if status == "SUCCEEDED":
                break
            if status in ("FAILED", "ABORTED", "TIMED-OUT"):
                LOGGER.warning("Apify actor %s run %s ended with status %s", actor_id, run_id, status)
                return []
        else:
            LOGGER.warning("Apify actor %s run %s timed out after %ds", actor_id, run_id, POLL_TIMEOUT)
            return []

        # Fetch dataset items
        r = await client.get(
            f"{APIFY_BASE}/v2/actor-runs/{run_id}/dataset/items",
            headers=headers,
        )
        r.raise_for_status()
        return r.json()


async def _search_booking(
    city: str,
    checkin: date,
    checkout: date,
    budget: int,
    apify_token: str,
) -> list[RentListing]:
    try:
        items = await _run_actor(
            "voyager/booking-scraper",
            {
                "search": city,
                "maxItems": 6,
                "checkIn": checkin.isoformat(),
                "checkOut": checkout.isoformat(),
                "numberOfRooms": 1,
                "numberOfAdults": 1,
                "numberOfChildren": 0,
                "currency": "USD",
                "language": "en-gb",
                "orderBy": "distance_from_search",
            },
            apify_token,
        )
    except Exception as exc:
        LOGGER.warning("Booking scraper error: %s", exc)
        return []

    results: list[RentListing] = []
    for item in items:
        price = item.get("price")
        if price is None:
            continue
        if float(price) > budget:      # ← фильтр по бюджету
            continue
        score = item.get("rating")
        results.append(RentListing(
            source="booking",
            name=item.get("name", ""),
            price_per_night=float(price),
            rating=float(score) if score is not None else None,
            url=item.get("url", ""),
        ))
    return results


async def _search_airbnb(
    city: str,
    checkin: date,
    checkout: date,
    budget: int,
    apify_token: str,
) -> list[RentListing]:
    try:
        items = await _run_actor(
            "tri_angle/airbnb-scraper",
            {
                "locationQueries": [city],
                "checkIn": checkin.isoformat(),
                "checkOut": checkout.isoformat(),
                "currency": "USD",
                "maximumPrice": budget,
                "adults": 1,
                "maxListings": 10,
            },
            apify_token,
        )
    except Exception as exc:
        LOGGER.warning("Airbnb scraper error: %s", exc)
        return []

    results: list[RentListing] = []
    for item in items:
        base = item.get("price", {}).get("breakDown", {}).get("basePrice", {}).get("price", "")
        if not base:
            continue
        try:
            price = float(base.replace("$", "").replace(",", "").strip())
        except ValueError:
            continue
        rating_obj = item.get("rating")
        rating = float(rating_obj["guestSatisfaction"]) if rating_obj and rating_obj.get("guestSatisfaction") else None
        url = f"https://www.airbnb.com/rooms/{item['id']}"
        name = item.get("title", "")
        results.append(RentListing(
            source="airbnb",
            name=name,
            price_per_night=price,
            rating=rating,
            url=url,
        ))
    return results


async def search_rentals(
    city: str,
    checkin: date,
    checkout: date,
    budget: int,
    apify_token: str,
) -> list[RentListing]:
    """Параллельный поиск на Booking и Airbnb через Apify. Топ 7 по цене."""
    raw = await asyncio.gather(
        _search_booking(city, checkin, checkout, budget, apify_token),
        _search_airbnb(city, checkin, checkout, budget, apify_token),
        return_exceptions=True,
    )

    combined: list[RentListing] = []
    for result in raw:
        if isinstance(result, Exception):
            LOGGER.warning("Rent search partial failure: %s", result)
            continue
        combined.extend(result)

    combined.sort(key=lambda x: x.price_per_night)
    return combined[:7]
