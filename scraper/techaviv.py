"""
TechAviv job scraper — https://jobs.techaviv.com
Intercepts the first /api-boards/search-jobs response (triggered by page load),
then paginates via page.evaluate() fetch calls using the established browser session.
"""
import sys, os, json
from datetime import datetime, timezone
from playwright.sync_api import sync_playwright

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from shared.db import get_conn, init_db

SOURCE = "techaviv"
API_URL = "https://jobs.techaviv.com/api-boards/search-jobs"
PAGE_SIZE = 15
MAX_PAGES = 60  # up to 900 jobs

FIELD_MAP = {
    "engineering": "Software Engineering",
    "software": "Software Engineering",
    "backend": "Software Engineering",
    "frontend": "Software Engineering",
    "fullstack": "Software Engineering",
    "full stack": "Software Engineering",
    "mobile": "Software Engineering",
    "cloud": "Software Engineering",
    "devops": "DevOps",
    "infrastructure": "DevOps",
    "platform": "DevOps",
    "sre": "DevOps",
    "data": "Data Science",
    "machine learning": "AI / Machine Learning",
    "ai": "AI / Machine Learning",
    "artificial intelligence": "AI / Machine Learning",
    "security": "Cybersecurity",
    "cybersecurity": "Cybersecurity",
    "qa": "QA / Automation",
    "quality": "QA / Automation",
    "automation": "QA / Automation",
}


def classify_field(departments, title):
    text = " ".join(departments + [title]).lower()
    for key, val in FIELD_MAP.items():
        if key in text:
            return val
    return None  # non-tech role, skip


def stable_id(job_id, company_slug):
    return f"ta_{company_slug}_{job_id}"


def _parse_raw_jobs(raw_jobs, cutoff=None):
    """Parse raw API job objects. Returns (jobs_list, should_stop)."""
    jobs = []
    stop = False
    for raw in raw_jobs:
        ts = raw.get("timeStamp", "")
        if cutoff:
            try:
                discovered_dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except Exception:
                discovered_dt = datetime.now(timezone.utc)
            if discovered_dt < cutoff:
                stop = True
                continue

        depts = [d.lower() for d in (raw.get("departments") or [])]
        title = raw.get("title", "")
        field = classify_field(depts, title)
        if field is None:
            continue  # skip HR, Sales, Finance, etc.

        locations = raw.get("locations") or []
        location = ", ".join(locations) if locations else ""

        skills = [s.get("label", "") for s in (raw.get("skills") or [])]
        req_skills = [s.get("label", "") for s in (raw.get("requiredSkills") or [])]
        pref_skills = [s.get("label", "") for s in (raw.get("preferredSkills") or [])]

        # Build a rich synthetic description Claude can score from
        parts = [f"Role: {title} at {raw.get('companyName', '')}"]
        if depts:
            parts.append(f"Department: {', '.join(raw.get('departments', []))}")
        if req_skills:
            parts.append(f"Required skills: {', '.join(req_skills)}")
        if pref_skills:
            parts.append(f"Preferred skills: {', '.join(pref_skills)}")
        if skills:
            parts.append(f"All skills: {', '.join(skills)}")
        job_types = [t if isinstance(t, str) else t.get("label", str(t)) for t in (raw.get("jobTypes") or [])]
        if job_types:
            parts.append(f"Job type: {', '.join(job_types)}")
        if raw.get("remote"):
            parts.append("Remote: Yes")
        description = "\n".join(parts)
        requirements = f"Required: {', '.join(req_skills)}" if req_skills else ""

        jobs.append({
            "id": stable_id(raw.get("jobId", ""), raw.get("companySlug", "")),
            "title": title,
            "company": raw.get("companyName", ""),
            "field": field,
            "description": description,
            "requirements": requirements,
            "url": raw.get("applyUrl") or raw.get("url", ""),
            "location": location,
            "min_exp": None,
            "discovered": ts or datetime.now(timezone.utc).isoformat(),
            "source": SOURCE,
        })
    return jobs, stop


def fetch_all_jobs(since_hours=25):
    # TechAviv timestamps are original posting dates, not "discovered" dates.
    # We fetch the first MAX_PAGES of results (sorted by relevance/recency)
    # and rely on DB deduplication to skip already-seen jobs.
    all_jobs = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        page = ctx.new_page()

        # Intercept the first search-jobs call made automatically by the page
        first_response = {}
        def on_response(response):
            if "search-jobs" in response.url and response.status == 200 and "jobs" not in first_response:
                try:
                    body = response.json()
                    if body.get("jobs"):
                        first_response["jobs"] = body["jobs"]
                        first_response["meta"] = body.get("meta", {})
                        first_response["total"] = body.get("total", 0)
                except Exception:
                    pass

        page.on("response", on_response)
        page.goto("https://jobs.techaviv.com/jobs", wait_until="networkidle", timeout=45000)

        if "jobs" not in first_response:
            print("[techaviv] Warning: failed to intercept initial response")
            browser.close()
            return []

        # Process page 1 (no cutoff — use all jobs)
        jobs, _ = _parse_raw_jobs(first_response["jobs"], cutoff=None)
        all_jobs.extend(jobs)
        sequence = first_response["meta"].get("sequence")

        # Paginate
        for _ in range(MAX_PAGES - 1):
            if not sequence:
                break

            payload = {"boardName": "techaviv", "size": PAGE_SIZE, "sequence": sequence}
            result = page.evaluate("""
                async (args) => {
                    try {
                        const resp = await fetch(args.url, {
                            method: 'POST',
                            headers: {'Content-Type': 'application/json', 'Accept': 'application/json'},
                            body: JSON.stringify(args.payload)
                        });
                        return await resp.json();
                    } catch(e) { return {jobs: [], meta: {}}; }
                }
            """, {"url": API_URL, "payload": payload})

            raw_jobs = result.get("jobs", [])
            if not raw_jobs:
                break

            jobs, _ = _parse_raw_jobs(raw_jobs, cutoff=None)
            all_jobs.extend(jobs)

            next_seq = (result.get("meta") or {}).get("sequence")
            if not next_seq or next_seq == sequence:
                break
            sequence = next_seq

        browser.close()

    return all_jobs


def save_jobs(jobs):
    conn = get_conn()
    new_count = 0
    for job in jobs:
        existing = conn.execute("SELECT id FROM jobs WHERE id=?", (job["id"],)).fetchone()
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


def run(since_hours=25):
    init_db()
    print("[techaviv] Fetching TechAviv jobs...")
    jobs = fetch_all_jobs(since_hours=since_hours)
    print(f"[techaviv] Found {len(jobs)} relevant jobs in last {since_hours}h")
    saved = save_jobs(jobs)
    print(f"[techaviv] Saved {saved} new jobs to DB")
    return saved


if __name__ == "__main__":
    hours = int(sys.argv[1]) if len(sys.argv) > 1 else 25
    run(since_hours=hours)
