import sys, os, json
from datetime import datetime, timezone, timedelta
from playwright.sync_api import sync_playwright

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from shared.db import get_conn, init_db
from shared.config import FIELDS, RELEVANT_FIELD_IDS, GOOZALI_SHARE_URL


def fetch_goozali_data() -> dict:
    result = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        def handle_route(route, request):
            try:
                resp = route.fetch()
            except Exception:
                route.abort()
                return
            if 'readSharedViewData' in request.url and 'msgpack' not in request.url:
                try:
                    result['body'] = resp.text()
                except Exception:
                    pass
            route.fulfill(response=resp)

        page.route('**/*', handle_route)
        page.goto(GOOZALI_SHARE_URL, wait_until='domcontentloaded', timeout=40000)
        page.wait_for_timeout(10000)
        browser.close()

    if 'body' not in result:
        raise RuntimeError("Failed to capture Airtable data")
    return json.loads(result['body'])


def resolve_field_choices(columns: list) -> dict:
    """Build select-id → label map from column metadata."""
    choice_map = {}
    for col in columns:
        opts = col.get('typeOptions') or {}
        choices = opts.get('choices', {})
        for cid, choice in choices.items():
            choice_map[cid] = choice.get('name', cid)
    return choice_map


def parse_rows(data: dict, since_hours: int = 25) -> list[dict]:
    table = data['data']['table']
    columns = table['columns']
    rows = table['rows']
    choice_map = resolve_field_choices(columns)

    cutoff = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    jobs = []

    for row in rows:
        cells = row.get('cellValuesByColumnId', {})

        # Filter by relevant field category
        field_sel = cells.get('fldHy6G67uu7RvU7W')
        if field_sel not in RELEVANT_FIELD_IDS:
            continue

        # Parse discovered date
        discovered_raw = cells.get('fld0IWlQzimjOyKcm', '')
        try:
            discovered_dt = datetime.fromisoformat(discovered_raw.replace('Z', '+00:00'))
        except Exception:
            continue

        if discovered_dt < cutoff:
            continue

        # Resolve location (multiselect list of IDs)
        loc_ids = cells.get('fldKjkUS3dypwOv9e', []) or []
        location = ', '.join(choice_map.get(lid, lid) for lid in loc_ids)

        jobs.append({
            'id': row['id'],
            'title': cells.get('fldPX7uQTBeLM8qIM', ''),
            'company': cells.get('fldLutadLsnGiv7oZ', ''),
            'field': choice_map.get(field_sel, field_sel),
            'description': cells.get('fldwOL044G6IGcDKj', '') or '',
            'requirements': cells.get('fldIuBO23JewsToWa', '') or '',
            'url': cells.get('fldDhjjRS8LR94g9q', ''),
            'location': location,
            'min_exp': cells.get('fldfuYXHAHe1DsL8X'),
            'discovered': discovered_raw,
            'source': 'goozali',
        })

    return jobs


def save_jobs(jobs: list[dict]) -> int:
    conn = get_conn()
    new_count = 0
    for job in jobs:
        existing = conn.execute('SELECT id FROM jobs WHERE id=?', (job['id'],)).fetchone()
        if existing:
            continue
        conn.execute(
            """INSERT INTO jobs (id, title, company, field, description, requirements,
               url, location, min_exp, discovered, source)
               VALUES (:id,:title,:company,:field,:description,:requirements,
                       :url,:location,:min_exp,:discovered,:source)""",
            job
        )
        new_count += 1
    conn.commit()
    conn.close()
    return new_count


def run(since_hours: int = 25) -> int:
    init_db()
    print(f"[scraper] Fetching Goozali data...")
    data = fetch_goozali_data()
    jobs = parse_rows(data, since_hours=since_hours)
    print(f"[scraper] Found {len(jobs)} relevant new jobs in last {since_hours}h")
    saved = save_jobs(jobs)
    print(f"[scraper] Saved {saved} new jobs to DB")
    return saved


if __name__ == '__main__':
    hours = int(sys.argv[1]) if len(sys.argv) > 1 else 25
    run(since_hours=hours)
