"""Rent search service — parallel Booking.com + Airbnb."""
import asyncio
import logging
from dataclasses import dataclass
from datetime import date

import httpx

LOGGER = logging.getLogger(__name__)

APIFY_BASE = "https://api.apify.com"
OMKAR_BASE = "https://airbnb-scraper-api.omkar.cloud"
CLIENT_TIMEOUT = 130
POLL_INTERVAL = 3
POLL_TIMEOUT = 120


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
        data = r.json()
        return data if isinstance(data, list) else data.get("items", [])


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
        if isinstance(price, str):
            try:
                price = float(price.replace("$", "").replace(",", "").strip())
            except ValueError:
                continue
        else:
            price = float(price)
        if price > budget:
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
    omkar_token: str,
) -> list[RentListing]:
    try:
        async with httpx.AsyncClient(timeout=CLIENT_TIMEOUT) as client:
            r = await client.get(
                f"{OMKAR_BASE}/airbnb/listings/search",
                params={
                    "destination_query": city,
                    "arrival_date": checkin.isoformat(),
                    "departure_date": checkout.isoformat(),
                    "adult_guests": 1,
                },
                headers={"API-Key": omkar_token},
            )
            r.raise_for_status()
            items = r.json().get("listings", [])
    except Exception as exc:
        LOGGER.warning("Airbnb scraper error: %s", exc)
        return []

    results: list[RentListing] = []
    for item in items:
        price_raw = item.get("pricing", {}).get("nightly_rate")
        if price_raw is None:
            continue
        try:
            price = float(price_raw)
        except (ValueError, TypeError):
            continue
        if float(price) > budget:
            continue
        rating = item.get("overall_rating")
        url = item["listing_url"]
        name = item.get("name", "")
        results.append(RentListing(
            source="airbnb",
            name=name,
            price_per_night=price,
            rating=float(rating) if rating is not None else None,
            url=url,
        ))
    return results[:6]


async def search_rentals(
    city: str,
    checkin: date,
    checkout: date,
    budget: int,
    apify_token: str,
    omkar_token: str = "",
) -> list[RentListing]:
    """Параллельный поиск на Booking (Apify) и Airbnb (omkar.cloud). Топ 13 по цене."""
    raw = await asyncio.gather(
        _search_booking(city, checkin, checkout, budget, apify_token),
        _search_airbnb(city, checkin, checkout, budget, omkar_token),
        return_exceptions=True,
    )

    combined: list[RentListing] = []
    for result in raw:
        if isinstance(result, Exception):
            LOGGER.warning("Rent search partial failure: %s", result)
            continue
        combined.extend(result)

    combined.sort(key=lambda x: x.price_per_night)
    return combined[:13]
