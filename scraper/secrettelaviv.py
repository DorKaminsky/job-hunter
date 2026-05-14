"""
Secret Tel Aviv job scraper — https://www.secrettelaviv.com/jobs
WordPress-based job board, server-rendered HTML, CSS selectors, page-based pagination.
"""
import sys, os, re
from datetime import datetime, timezone
from playwright.sync_api import sync_playwright

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from shared.db import get_conn, init_db

SOURCE = "secrettelaviv"
BASE_URL = "https://www.secrettelaviv.com/jobs"
MAX_PAGES = 20

FIELD_MAP = {
    "engineering": "Software Engineering",
    "software": "Software Engineering",
    "developer": "Software Engineering",
    "backend": "Software Engineering",
    "frontend": "Software Engineering",
    "full stack": "Software Engineering",
    "fullstack": "Software Engineering",
    "mobile": "Software Engineering",
    "cloud": "Software Engineering",
    "devops": "DevOps",
    "infrastructure": "DevOps",
    "platform": "DevOps",
    "sre": "DevOps",
    "data": "Data Science",
    "machine learning": "AI / Machine Learning",
    "ml": "AI / Machine Learning",
    "ai": "AI / Machine Learning",
    "artificial intelligence": "AI / Machine Learning",
    "security": "Cybersecurity",
    "cybersecurity": "Cybersecurity",
    "qa": "QA / Automation",
    "quality": "QA / Automation",
    "automation": "QA / Automation",
    "test": "QA / Automation",
}


def classify_field(title: str, description: str = ""):
    text = f"{title} {description}".lower()
    for key, val in FIELD_MAP.items():
        if key in text:
            return val
    return None


def stable_id(title: str, company: str) -> str:
    slug = re.sub(r'[^a-z0-9]+', '-', f"{company}-{title}".lower()).strip('-')[:60]
    return f"stlv_{slug}"


def fetch_all_jobs():
    jobs = []
    seen_ids = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        page = ctx.new_page()

        for page_num in range(1, MAX_PAGES + 1):
            url = BASE_URL if page_num == 1 else f"{BASE_URL}/page/{page_num}"
            try:
                page.goto(url, wait_until='domcontentloaded', timeout=30000)
            except Exception as e:
                print(f"[secrettelaviv] Page {page_num} load error: {e}")
                break

            # Job listings — Secret Tel Aviv uses multiple possible selectors
            # Try several common WordPress job board patterns
            listings = page.query_selector_all('.job-listing, .job_listing, article.job-item, .job-card, li.job')

            if not listings:
                # Try generic article/post selectors
                listings = page.query_selector_all('article[class*="job"], .jobs-list li, .job-list-item')

            if not listings:
                print(f"[secrettelaviv] No listings found on page {page_num} — stopping")
                break

            page_jobs = 0
            for el in listings:
                try:
                    # Title
                    title_el = el.query_selector('.job-title, h2, h3, .position-title, a[class*="title"]')
                    title = title_el.inner_text().strip() if title_el else ''
                    if not title:
                        title_el = el.query_selector('a')
                        title = title_el.inner_text().strip() if title_el else ''

                    # Company
                    company_el = el.query_selector('.company-name, .company, .employer, [class*="company"]')
                    company = company_el.inner_text().strip() if company_el else ''

                    # Location
                    loc_el = el.query_selector('.location, .job-location, [class*="location"]')
                    location = loc_el.inner_text().strip() if loc_el else 'Tel Aviv'

                    # URL
                    link_el = el.query_selector('a')
                    url_href = link_el.get_attribute('href') if link_el else ''
                    if url_href and not url_href.startswith('http'):
                        url_href = 'https://www.secrettelaviv.com' + url_href

                    # Description snippet
                    desc_el = el.query_selector('.job-description, .description, p')
                    description = desc_el.inner_text().strip()[:500] if desc_el else ''

                    if not title:
                        continue

                    field = classify_field(title, description)
                    if field is None:
                        continue

                    job_id = stable_id(title, company)
                    if job_id in seen_ids:
                        continue
                    seen_ids.add(job_id)

                    jobs.append({
                        'id': job_id,
                        'title': title,
                        'company': company or 'Unknown',
                        'field': field,
                        'description': description,
                        'requirements': '',
                        'url': url_href,
                        'location': location,
                        'min_exp': None,
                        'discovered': datetime.now(timezone.utc).isoformat(),
                        'source': SOURCE,
                    })
                    page_jobs += 1

                except Exception:
                    continue

            print(f"[secrettelaviv] Page {page_num}: {page_jobs} tech jobs")
            if page_jobs == 0:
                break

        browser.close()

    return jobs


def save_jobs(jobs):
    conn = get_conn()
    new_count = 0
    for job in jobs:
        existing = conn.execute("SELECT id FROM jobs WHERE id=?", (job['id'],)).fetchone()
        if existing:
            continue
        conn.execute(
            """INSERT INTO jobs (id, title, company, field, description, requirements,
               url, location, min_exp, discovered, source)
               VALUES (:id,:title,:company,:field,:description,:requirements,
                       :url,:location,:min_exp,:discovered,:source)""",
            job,
        )
        new_count += 1
    conn.commit()
    conn.close()
    return new_count


def run():
    init_db()
    print("[secrettelaviv] Fetching Secret Tel Aviv jobs...")
    jobs = fetch_all_jobs()
    print(f"[secrettelaviv] Found {len(jobs)} relevant jobs")
    saved = save_jobs(jobs)
    print(f"[secrettelaviv] Saved {saved} new jobs to DB")
    return saved


if __name__ == "__main__":
    run()
