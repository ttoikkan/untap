"""Explicitly requested candidate discovery; URLs never imply confirmation."""
import re
from urllib.parse import urlsplit


def parse_beer_url(value):
    if not isinstance(value, str):
        raise ValueError("Expected an Untappd beer URL")
    parsed = urlsplit(value.strip())
    match = re.fullmatch(r"/b/([A-Za-z0-9_-]+)/([1-9][0-9]*)/?", parsed.path)
    if (parsed.scheme != "https" or parsed.netloc not in ("untappd.com", "www.untappd.com")
            or parsed.query or parsed.fragment or not match):
        raise ValueError("Use an HTTPS Untappd /b/name/beer-id URL without query parameters")
    return match.group(2), "https://untappd.com" + parsed.path.rstrip("/"), match.group(1)


def candidate_from_hit(hit, url):
    beer_id, canonical, _ = parse_beer_url(url)
    if str(hit.get("bid")) != beer_id:
        raise ValueError("Retrieved beer ID does not match the requested URL")
    if not hit.get("beer_name") or not hit.get("brewery_name"):
        raise ValueError("Retrieved candidate is missing its name or brewery")
    return {
        "name": hit["beer_name"], "brewery": hit["brewery_name"],
        "url": canonical, "abv": hit.get("beer_abv"),
        "rating": hit.get("rating_score"), "ratings": hit.get("rating_count"),
        "type_name": hit.get("type_name"), "image_url": hit.get("beer_label"),
        "image_hd_url": hit.get("beer_label_hd"), "in_production": hit.get("in_production"),
        "user_added": True,
    }


def fetch_candidates(urls):
    # Reuse the inspector transport, not arbitrary URL requests or a new API.
    from untap_inspect import inspect_query
    from untap_untappd import untappd_browser_page
    found = {}
    try:
        with untappd_browser_page() as page:
            for url in urls:
                beer_id, _, slug = parse_beer_url(url)
                if beer_id in found:
                    continue
                print(f"Fetching user-added candidate {beer_id}")
                inspection = inspect_query(page, slug.replace("-", " "), all_pages=True)
                if inspection.get("error"):
                    raise ValueError(f"Candidate {beer_id}: {inspection['error']}")
                hit = next((h for h in inspection["hits"] if str(h.get("bid")) == beer_id), None)
                if hit is None:
                    raise ValueError(f"Beer {beer_id} was not retrieved by its URL name; no substitute was accepted")
                found[beer_id] = candidate_from_hit(hit, url)
    except Exception as exc:
        raise ValueError(f"Candidate retrieval failed: {exc}") from exc
    return found
