import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

NPI_BASE_URL = "https://npiregistry.cms.hhs.gov/api/"
DEPARTMENT_TAXONOMY = {
    "Dermatology": "Dermatology",
    "Cardiology": "Cardiology",
    "General Medicine": "Family Medicine",
    "Pediatrics": "Pediatrics",
    "Orthopedics": "Orthopaedic Surgery",
}


def _matches_taxonomy(item: dict[str, Any], target: str) -> bool:
    if not target:
        return True
    taxonomies = item.get("taxonomies", []) or []
    target_lower = target.lower()
    for taxonomy in taxonomies:
        description = (taxonomy.get("desc") or taxonomy.get("taxonomy_description") or "").lower()
        if target_lower in description:
            return True
    return False


async def _fetch_npi(params: dict[str, str]) -> list[dict[str, Any]]:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(NPI_BASE_URL, params=params)
            response.raise_for_status()
            data = response.json()
    except Exception as exc:
        logger.warning("npi_lookup_failed params=%s error=%s", params, exc)
        return []
    return data.get("results", [])


async def _lookup_zip(postal_code: str) -> tuple[str | None, str | None]:
    url = f"https://api.zippopotam.us/us/{postal_code}"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(url)
            response.raise_for_status()
            data = response.json()
    except Exception as exc:
        logger.warning("zip_lookup_failed postal_code=%s error=%s", postal_code, exc)
        return None, None
    places = data.get("places", []) or []
    if not places:
        return None, None
    place = places[0]
    return place.get("place name"), place.get("state abbreviation")


def _collect_providers(
    results: list[dict[str, Any]], taxonomy: str, limit: int
) -> list[dict[str, Any]]:
    providers: list[dict[str, Any]] = []
    for item in results:
        if not _matches_taxonomy(item, taxonomy):
            continue
        number = str(item.get("number", ""))
        basic = item.get("basic", {}) or {}
        name = basic.get("name") or basic.get("organization_name") or "Provider"
        addresses = item.get("addresses", []) or []
        address = addresses[0] if addresses else {}
        providers.append(
            {
                "npi": number,
                "name": name,
                "city": address.get("city"),
                "state": address.get("state"),
                "postal_code": address.get("postal_code"),
            }
        )
        if len(providers) >= limit:
            break
    return providers


async def search_providers(
    department: str, postal_code: str, limit: int = 5
) -> tuple[list[dict[str, Any]], str | None]:
    taxonomy = DEPARTMENT_TAXONOMY.get(department, department)
    query_limit = max(limit * 5, 20)
    params = {
        "version": "2.1",
        "limit": str(query_limit),
        "postal_code": postal_code,
    }
    results = await _fetch_npi(params)
    providers = _collect_providers(results, taxonomy, limit)
    if providers:
        return providers, None

    city, state = await _lookup_zip(postal_code)
    if not city and not state:
        return [], None

    fallback_params = {
        "version": "2.1",
        "limit": str(query_limit),
    }
    if state:
        fallback_params["state"] = state
    if city:
        fallback_params["city"] = city
    if taxonomy:
        fallback_params["taxonomy_description"] = taxonomy
    fallback_results = await _fetch_npi(fallback_params)
    fallback_providers = _collect_providers(fallback_results, taxonomy, limit)
    if fallback_providers:
        return fallback_providers, "nearby"

    if taxonomy:
        fallback_params.pop("taxonomy_description", None)
        broader_results = await _fetch_npi(fallback_params)
        broader_providers = _collect_providers(broader_results, "", limit)
        if broader_providers:
            return broader_providers, "broader"

    return [], None
