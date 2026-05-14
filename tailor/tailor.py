import sys, os, io, json, re
import anthropic
import pdfplumber
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable, Table, TableStyle
from reportlab.lib.enums import TA_RIGHT
from dotenv import load_dotenv

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from shared.db import get_conn, init_db
from shared.config import MATCH_SCORE_THRESHOLD, EXCLUDED_TITLE_KEYWORDS

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

TEAL = colors.HexColor("#4A9BAF")
BLACK = colors.HexColor("#222222")
GRAY = colors.HexColor("#666666")

TAILOR_SYSTEM = """You are an expert resume writer helping a candidate present their genuine experience in the best light for a specific role.

Rules:
- Preserve ALL factual information — never invent experience, skills, or qualifications
- Keep the candidate's natural voice — edits should feel like THEY wrote it, not like the job description was copy-pasted in
- Make changes SUBTLE: reorder or reframe bullets to emphasise what's most relevant, don't replace every sentence with job-posting language
- Only inject a job-posting keyword if the candidate genuinely did that thing — rephrase their existing bullet to use that term naturally
- Prioritise the most relevant bullets; trim or compress less relevant ones to save space
- The summary should sound personal and confident, not like a job spec echo
- Keep the exact same sections, roles, companies, and dates — structural changes are forbidden

Return ONLY a valid JSON object (no markdown, no code fences):
{
  "name": "Full Name",
  "contact": "phone • email • GitHub • LinkedIn",
  "summary": "Summary paragraph",
  "sections": [
    {
      "title": "SECTION NAME",
      "entries": [
        {
          "role": "Title",
          "company": "Company",
          "date": "Date Range",
          "bullets": ["bullet 1", "bullet 2"]
        }
      ]
    }
  ]
}"""

SHORTEN_PROMPT = (
    "The resume is too long and spills onto a second page. "
    "Shorten it by trimming bullets to their most impactful parts and condensing the summary. "
    "Do NOT remove any roles, projects, or education entries. Return the full updated JSON."
)


def load_cv_text(cv_path: str) -> str:
    with pdfplumber.open(cv_path) as pdf:
        return "\n\n".join(p.extract_text() or "" for p in pdf.pages).strip()


def parse_json(text: str) -> dict:
    text = re.sub(r"^```[a-z]*\n?", "", text.strip())
    text = re.sub(r"\n?```$", "", text)
    return json.loads(text.strip())


def tailor_cv(cv_text: str, job: dict) -> dict:
    job_text = f"Job Title: {job['title']}\nCompany: {job['company']}\n\nDescription:\n{job['description']}\n\nRequirements:\n{job['requirements']}"
    messages = [{"role": "user", "content": f"CV:\n{cv_text}\n\nJOB:\n{job_text}\n\nTailor my CV for this job and return JSON."}]
    resp = client.messages.create(model="claude-sonnet-4-6", max_tokens=4096, system=TAILOR_SYSTEM, messages=messages)
    data = parse_json(resp.content[0].text)
    messages.append({"role": "assistant", "content": resp.content[0].text})

    # Enforce 1 page — up to 3 shorten attempts
    for _ in range(3):
        pdf_bytes = build_pdf(data)
        if count_pages(pdf_bytes) <= 1:
            break
        messages.append({"role": "user", "content": SHORTEN_PROMPT})
        resp = client.messages.create(model="claude-sonnet-4-6", max_tokens=4096, system=TAILOR_SYSTEM, messages=messages)
        data = parse_json(resp.content[0].text)
        messages.append({"role": "assistant", "content": resp.content[0].text})

    return data


def count_pages(pdf_bytes: bytes) -> int:
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        return len(pdf.pages)


def build_pdf(data: dict) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=1.8*cm, rightMargin=1.8*cm, topMargin=1.6*cm, bottomMargin=1.6*cm)

    def s(text): return (text or "").replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")

    name_s = ParagraphStyle("N", fontSize=28, fontName="Helvetica-Bold", textColor=BLACK, leading=32, spaceAfter=2)
    contact_s = ParagraphStyle("C", fontSize=9.5, fontName="Helvetica", textColor=BLACK, leading=14, spaceAfter=10)
    summary_s = ParagraphStyle("S", fontSize=9.5, fontName="Helvetica", textColor=BLACK, leading=15, spaceAfter=14)
    sec_s = ParagraphStyle("Sec", fontSize=9, fontName="Helvetica-Bold", textColor=TEAL, leading=12, spaceAfter=1, spaceBefore=6)
    role_s = ParagraphStyle("R", fontSize=10.5, fontName="Helvetica-Bold", textColor=BLACK, leading=14, spaceAfter=0, spaceBefore=6)
    date_s = ParagraphStyle("D", fontSize=9.5, fontName="Helvetica", textColor=GRAY, leading=14, alignment=TA_RIGHT)
    bullet_s = ParagraphStyle("B", fontSize=9.5, fontName="Helvetica", textColor=BLACK, leading=14, leftIndent=14, spaceAfter=1)

    story = [Paragraph(s(data.get("name","")), name_s), Paragraph(s(data.get("contact","")), contact_s)]
    if data.get("summary"):
        story.append(Paragraph(s(data["summary"]), summary_s))

    for sec in data.get("sections", []):
        story.append(Paragraph(s(sec["title"]), sec_s))
        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#cccccc"), spaceAfter=4, spaceBefore=1))
        for entry in sec.get("entries", []):
            role_text = " — ".join(filter(None, [entry.get("role",""), entry.get("company","")]))
            date_text = entry.get("date","")
            if role_text or date_text:
                if date_text:
                    t = Table([[Paragraph(s(role_text), role_s), Paragraph(s(date_text), date_s)]], colWidths=["75%","25%"], hAlign="LEFT")
                    t.setStyle(TableStyle([("VALIGN",(0,0),(-1,-1),"MIDDLE"),("LEFTPADDING",(0,0),(-1,-1),0),("RIGHTPADDING",(0,0),(-1,-1),0),("TOPPADDING",(0,0),(-1,-1),0),("BOTTOMPADDING",(0,0),(-1,-1),0)]))
                    story.append(t)
                else:
                    story.append(Paragraph(s(role_text), role_s))
            for b in entry.get("bullets", []):
                b = b.strip()
                if b:
                    story.append(Paragraph(("• " if not b.startswith("•") else "") + s(b), bullet_s))
        story.append(Spacer(1, 4))

    doc.build(story)
    return buf.getvalue()


def run(cv_path: str, pdfs_dir: str):
    init_db()
    cv_text = load_cv_text(cv_path)
    os.makedirs(pdfs_dir, exist_ok=True)

    conn = get_conn()
    # Jobs matched above threshold but not yet tailored, excluding senior/QA/manager titles
    exclude_clauses = " ".join(
        f"AND LOWER(j.title) NOT LIKE ?" for _ in EXCLUDED_TITLE_KEYWORDS
    )
    to_tailor = conn.execute(f"""
        SELECT j.*, m.score FROM jobs j
        JOIN matches m ON m.job_id = j.id
        LEFT JOIN applications a ON a.job_id = j.id
        WHERE m.score >= ? AND a.id IS NULL
        {exclude_clauses}
    """, [MATCH_SCORE_THRESHOLD] + [f'%{kw}%' for kw in EXCLUDED_TITLE_KEYWORDS]).fetchall()

    tailored_count = 0
    print(f"[tailor] Tailoring {len(to_tailor)} CVs...")
    for job in to_tailor:
        job = dict(job)
        try:
            data = tailor_cv(cv_text, job)
            pdf_bytes = build_pdf(data)
            safe_title = re.sub(r'[^a-zA-Z0-9_-]', '_', job['title'])[:40]
            filename = f"{job['id']}_{safe_title}.pdf"
            pdf_path = os.path.join(pdfs_dir, filename)
            with open(pdf_path, 'wb') as f:
                f.write(pdf_bytes)
            conn.execute(
                "INSERT INTO applications (job_id, status, pdf_path, tailored_json) VALUES (?,?,?,?)",
                (job['id'], 'new', pdf_path, json.dumps(data))
            )
            conn.commit()
            tailored_count += 1
            print(f"  ✓ [{job['score']:3d}] {job['title']} @ {job['company']}")
        except Exception as e:
            print(f"  [error] {job['id']}: {e}")

    conn.close()
    print("[tailor] Done")
    return tailored_count


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python tailor.py <cv.pdf>")
        sys.exit(1)
    cv = sys.argv[1]
    pdfs = os.path.join(os.path.dirname(__file__), '..', 'pdfs')
    run(cv, pdfs)
