"""
Lawyer finder.
Uses Google Places API to find relevant lawyers by practice area and location.
Stores results in the lawyers table and triggers outbound calls.
"""

import os
import json
import uuid
import requests
from dotenv import load_dotenv
from db import get_conn, update_case

load_dotenv()

GOOGLE_API_KEY = os.environ.get("GOOGLE_PLACES_API_KEY", "")
MAX_LAWYERS = 5  # How many lawyers to contact per case

# Map practice areas to search terms
PRACTICE_AREA_QUERIES = {
    "employment":       "employment lawyer",
    "personal_injury":  "personal injury attorney",
    "family":           "family law attorney",
    "landlord_tenant":  "tenant rights lawyer",
    "contract":         "contract dispute attorney",
    "criminal":         "criminal defense attorney",
    "immigration":      "immigration lawyer",
    "other":            "attorney lawyer",
}


def find_lawyers_for_case(case_id: str):
    """
    Look up the case, find matching lawyers via Google Places, store them,
    then kick off the calling pipeline.
    """
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM cases WHERE id=?", (case_id,)).fetchone()

    if not row or not row["case_json"]:
        print(f"[lawyer_finder] No case data found for {case_id}")
        return

    case_data = json.loads(row["case_json"])
    practice_area = case_data.get("practice_area", "other")
    location = case_data.get("location", {})
    city = location.get("city", "")
    state = location.get("state", "")

    if not city:
        print(f"[lawyer_finder] No city in case {case_id}, cannot search")
        return

    query = PRACTICE_AREA_QUERIES.get(practice_area, "attorney lawyer")
    location_str = f"{city}, {state}"

    print(f"[lawyer_finder] Searching for '{query}' in '{location_str}'")
    lawyers = _search_google_places(query, location_str)

    if not lawyers:
        print(f"[lawyer_finder] No lawyers found for case {case_id}")
        return

    # Store lawyers in DB
    with get_conn() as conn:
        for lawyer in lawyers[:MAX_LAWYERS]:
            lawyer_id = str(uuid.uuid4())
            conn.execute("""
                INSERT INTO lawyers
                    (id, case_id, name, firm, phone, address, city, state,
                     practice_areas, google_place_id, rating, call_status)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                lawyer_id, case_id,
                lawyer.get("name", ""),
                lawyer.get("name", ""),          # firm = name for solo/small firms
                lawyer.get("phone", ""),
                lawyer.get("address", ""),
                city, state,
                practice_area,
                lawyer.get("place_id", ""),
                lawyer.get("rating", 0.0),
                "pending"
            ))

    update_case(case_id, status="calling")
    print(f"[lawyer_finder] Stored {min(len(lawyers), MAX_LAWYERS)} lawyers for case {case_id}")

    # Trigger calls
    from phone_caller import call_lawyers_for_case
    call_lawyers_for_case(case_id)


def _search_google_places(query: str, location_str: str) -> list[dict]:
    """
    Search Google Places Text Search API for lawyers.
    Returns a list of dicts with name, phone, address, place_id, rating.
    """
    url = "https://maps.googleapis.com/maps/api/place/textsearch/json"
    params = {
        "query": f"{query} in {location_str}",
        "key": GOOGLE_API_KEY,
        "type": "lawyer",
    }

    resp = requests.get(url, params=params, timeout=10)
    resp.raise_for_status()
    data = resp.json()

    results = []
    for place in data.get("results", []):
        place_id = place.get("place_id", "")
        # Get phone number via Place Details (requires a second call)
        phone = _get_place_phone(place_id)
        if not phone:
            continue  # skip lawyers without a phone number

        results.append({
            "name":     place.get("name", ""),
            "address":  place.get("formatted_address", ""),
            "place_id": place_id,
            "rating":   place.get("rating", 0.0),
            "phone":    phone,
        })

    return results


def _get_place_phone(place_id: str) -> str:
    """Fetch formatted_phone_number from Place Details API."""
    url = "https://maps.googleapis.com/maps/api/place/details/json"
    params = {
        "place_id": place_id,
        "fields": "formatted_phone_number",
        "key": GOOGLE_API_KEY,
    }
    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        return resp.json().get("result", {}).get("formatted_phone_number", "")
    except Exception as e:
        print(f"[lawyer_finder] Failed to get phone for {place_id}: {e}")
        return ""


if __name__ == "__main__":
    case_id = input("Case ID to search lawyers for: ").strip()
    find_lawyers_for_case(case_id)
