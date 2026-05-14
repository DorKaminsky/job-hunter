import sys, os, json, re, time
import urllib.request
import anthropic
import pdfplumber
from dotenv import load_dotenv

try:
    from playwright.sync_api import sync_playwright as _sync_playwright
    _PLAYWRIGHT_AVAILABLE = True
except ImportError:
    _PLAYWRIGHT_AVAILABLE = False

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from shared.db import get_conn, init_db
from shared.config import MATCH_SCORE_THRESHOLD, CV_SKILLS, TOP_N_CLAUDE, \
                          TECHAVIV_RESCORE_MIN, TECHAVIV_RESCORE_MAX

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

MATCH_SYSTEM_BASE = """You are a recruitment expert. Given a candidate's CV and a job posting, evaluate how well the candidate fits the role.

Return ONLY a valid JSON object with this exact structure (no markdown, no explanation):
{
  "score": <integer 0-100>,
  "matched_keywords": ["keyword1", "keyword2", ...],
  "reason": "One or two sentences explaining the fit score."
}

Scoring guide — use the FULL range, do not cluster scores:
- 90-100: Near-perfect match — candidate has virtually all required skills, right experience level, ideal domain
- 75-89:  Strong match — candidate has most required skills with only minor gaps
- 60-74:  Good match — candidate meets core requirements but has some notable gaps
- 40-59:  Partial match — some relevant skills but significant gaps in domain or experience
- 20-39:  Weak match — mostly different domain or experience level
- 0-19:   Poor match — fundamentally wrong domain or far outside experience level

Calibration rules:
- Roles requiring 5+ years when candidate has ~4 years: cap at 75
- Roles titled "Senior", "Staff", "Principal", "Lead", "Manager", "Director", "Architect": subtract 15 points
- Roles in a clearly different domain (pure QA, hardware, data science only): cap at 45
- Genuinely excellent fits where candidate hits every bullet: score 88+
- Do NOT default to 70-75 for everything — differentiate clearly between a great fit and a decent fit"""


def build_match_system(conn) -> str:
    """Build the scoring system prompt enriched with user profile and feedback examples."""
    extra = []

    profile_row = conn.execute("SELECT value FROM user_profile WHERE key='profile'").fetchone()
    if profile_row and profile_row[0].strip():
        extra.append(f"\n\nCANDIDATE SELF-DESCRIPTION (use this to calibrate scores):\n{profile_row[0].strip()}")

    thumbs_up = conn.execute("""
        SELECT j.title, j.company, j.field, m.score, m.reason
        FROM matches m JOIN jobs j ON j.id = m.job_id
        WHERE m.feedback = 'up'
        ORDER BY m.matched_at DESC LIMIT 10
    """).fetchall()

    thumbs_down = conn.execute("""
        SELECT j.title, j.company, j.field, m.score, m.reason
        FROM matches m JOIN jobs j ON j.id = m.job_id
        WHERE m.feedback = 'down'
        ORDER BY m.matched_at DESC LIMIT 10
    """).fetchall()

    if thumbs_up:
        examples = "\n".join(
            f"  - {r['title']} @ {r['company']} (field: {r['field']}, scored {r['score']}): {r['reason']}"
            for r in thumbs_up
        )
        extra.append(f"\n\nJOBS THE CANDIDATE LIKED (score these types higher):\n{examples}")

    if thumbs_down:
        examples = "\n".join(
            f"  - {r['title']} @ {r['company']} (field: {r['field']}, scored {r['score']}): {r['reason']}"
            for r in thumbs_down
        )
        extra.append(f"\n\nJOBS THE CANDIDATE DISLIKED (score these types lower):\n{examples}")

    return MATCH_SYSTEM_BASE + "".join(extra)


def load_cv_text(cv_path: str) -> str:
    with pdfplumber.open(cv_path) as pdf:
        return "\n\n".join(p.extract_text() or "" for p in pdf.pages).strip()


def keyword_score(job: dict) -> int:
    text = f"{job.get('title','')} {job.get('description','')} {job.get('requirements','')}".lower()
    hits = sum(1 for skill in CV_SKILLS if skill in text)
    if not CV_SKILLS:
        return 0
    return min(100, round(hits / len(CV_SKILLS) * 100 * 3))


def _playwright_fetch_text(url: str, bctx=None) -> str:
    """Fetch a JS-rendered page and return body inner_text, or '' on failure."""
    if not _PLAYWRIGHT_AVAILABLE:
        return ''
    try:
        def _fetch(ctx):
            page = ctx.new_page()
            try:
                page.goto(url, wait_until='domcontentloaded', timeout=20000)
                # Bail out if a login wall appeared
                if page.locator('input[type="password"]').count() > 0:
                    return ''
                return page.inner_text('body')[:6000].strip()
            finally:
                page.close()

        if bctx is not None:
            return _fetch(bctx)
        with _sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            )
            try:
                return _fetch(ctx)
            finally:
                browser.close()
    except Exception:
        return ''


def fetch_job_description(url: str, bctx=None) -> str:
    """Fetch and extract plain text from a job URL. Falls back to Playwright for JS pages."""
    if not url:
        return ''
    # Try urllib first (fast path)
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml",
            }
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode("utf-8", errors="ignore")

        html = re.sub(r"<(script|style|noscript)[^>]*>.*?</(script|style|noscript)>",
                      " ", html, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r"\s+", " ", text).strip()[:5000]
        word_chars = len(re.findall(r'[a-zA-Z]{3,}', text))
        if word_chars >= 50:
            return text
    except Exception:
        pass

    # Playwright fallback for JS-rendered / blocked pages
    text = _playwright_fetch_text(url, bctx)
    if len(re.findall(r'[a-zA-Z]{3,}', text)) >= 50:
        return text
    return ''


def score_job_claude(cv_text: str, job: dict, match_system: str) -> dict:
    job_text = (
        f"Job Title: {job['title']}\nCompany: {job['company']}\nField: {job['field']}\n\n"
        f"Description:\n{job['description']}\n\nRequirements:\n{job['requirements']}"
    )
    prompt = f"CANDIDATE CV:\n{cv_text}\n\nJOB POSTING:\n{job_text}"
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=512,
        system=match_system,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = response.content[0].text.strip()
    raw = raw.replace("```json", "").replace("```", "").strip()
    return json.loads(raw)


def run(cv_path: str):
    init_db()
    cv_text = load_cv_text(cv_path)
    print(f"[matcher] CV loaded ({len(cv_text)} chars)")

    conn = get_conn()

    # Build scoring system prompt once, incorporating profile and past feedback
    match_system = build_match_system(conn)
    has_profile = "CANDIDATE SELF-DESCRIPTION" in match_system
    has_feedback = "LIKED" in match_system or "DISLIKED" in match_system
    if has_profile or has_feedback:
        print(f"[matcher] Scoring enriched with {'profile ' if has_profile else ''}{'+ feedback' if has_feedback else ''}")

    unmatched = conn.execute("""
        SELECT j.* FROM jobs j
        LEFT JOIN matches m ON m.job_id = j.id
        WHERE m.id IS NULL
    """).fetchall()
    unmatched = [dict(row) for row in unmatched]
    print(f"[matcher] {len(unmatched)} unmatched jobs — keyword pre-scoring...")

    for job in unmatched:
        job['_kw_score'] = keyword_score(job)

    unmatched.sort(key=lambda j: j['_kw_score'], reverse=True)
    top = unmatched[:TOP_N_CLAUDE]
    rest = unmatched[TOP_N_CLAUDE:]

    print(f"[matcher] Sending top {len(top)} to Claude API, {len(rest)} keyword-only...")

    rescore_count = 0

    # Open a single shared Playwright browser for all URL rescores
    _pw_ctx = None
    if _PLAYWRIGHT_AVAILABLE:
        try:
            _pw_inst = _sync_playwright().__enter__()
            _browser = _pw_inst.chromium.launch(headless=True)
            _pw_ctx = _browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            )
        except Exception:
            _pw_inst = None
            _browser = None
            _pw_ctx = None
    else:
        _pw_inst = None
        _browser = None

    try:
        # Phase 2: Claude API for top N
        for job in top:
            try:
                result = score_job_claude(cv_text, job, match_system)
                score = result.get('score', 0)
                keywords = result.get('matched_keywords', [])
                reason = result.get('reason', '')

                # Phase 2b: TechAviv borderline rescore — fetch full job description
                is_techaviv = job.get('source') == 'techaviv'
                in_rescore_range = TECHAVIV_RESCORE_MIN <= score <= TECHAVIV_RESCORE_MAX
                if is_techaviv and in_rescore_range:
                    full_desc = fetch_job_description(job.get('url', ''), bctx=_pw_ctx)
                    if full_desc and len(full_desc) > 200:
                        conn.execute(
                            "UPDATE jobs SET description=?, requirements=? WHERE id=?",
                            (full_desc, '', job['id'])
                        )
                        enriched = dict(job, description=full_desc, requirements='')
                        result2 = score_job_claude(cv_text, enriched, match_system)
                        score2 = result2.get('score', 0)
                        print(f"  ↺ rescore {score}→{score2} [{job['title']} @ {job['company']}]")
                        score = score2
                        keywords = result2.get('matched_keywords', [])
                        reason = result2.get('reason', '') + " [rescored with full description]"
                        rescore_count += 1
                        time.sleep(0.2)

            except Exception as e:
                print(f"  [error] {job['id']}: {e}")
                score = job['_kw_score']
                keywords = []
                reason = f"Claude API error — keyword pre-score used ({score})"

            conn.execute(
                "INSERT INTO matches (job_id, score, keywords, reason) VALUES (?,?,?,?)",
                (job['id'], score, json.dumps(keywords), reason)
            )
            conn.commit()
            status = "✓" if score >= MATCH_SCORE_THRESHOLD else "✗"
            print(f"  {status} [C {score:3d}] {job['title']} @ {job['company']}")

        # Phase 3: keyword-only for the rest
        for job in rest:
            score = job['_kw_score']
            conn.execute(
                "INSERT INTO matches (job_id, score, keywords, reason) VALUES (?,?,?,?)",
                (job['id'], score, json.dumps([]), "Keyword-based pre-score (not Claude-verified)")
            )
            conn.commit()
            status = "✓" if score >= MATCH_SCORE_THRESHOLD else "✗"
            print(f"  {status} [K {score:3d}] {job['title']} @ {job['company']}")

    finally:
        if _pw_ctx:
            try:
                _pw_ctx.close()
            except Exception:
                pass
        if _browser:
            try:
                _browser.close()
            except Exception:
                pass
        if _pw_inst:
            try:
                _pw_inst.__exit__(None, None, None)
            except Exception:
                pass

    conn.close()
    total = len(top) + len(rest)
    print(f"[matcher] Done — {len(top)} Claude-scored ({rescore_count} rescored with full desc), {len(rest)} keyword-scored")
    return total, len(top)


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python matcher.py <path_to_cv.pdf>")
        sys.exit(1)
    run(sys.argv[1])
