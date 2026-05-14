# Goozali Airtable field ID → name mapping
FIELDS = {
    "fld0IWlQzimjOyKcm": "discovered",
    "fldHy6G67uu7RvU7W": "field_select",
    "fldPX7uQTBeLM8qIM": "title",
    "fldLutadLsnGiv7oZ": "company",
    "fld9UFlS0Yxfo1AuX": "industry",
    "fldDhjjRS8LR94g9q": "url",
    "fldcK55EmF5hONqxu": "scope",
    "fldKjkUS3dypwOv9e": "location",
    "fldfuYXHAHe1DsL8X": "min_exp",
    "fldwOL044G6IGcDKj": "description",
    "fldIuBO23JewsToWa": "requirements",
}

# Field category select IDs to filter for relevant roles
RELEVANT_FIELD_IDS = {
    "selbQiZPez7SQlvo8",  # Software Engineering
    "selAUmXLz5XRNuKh3",  # DevOps
    "selzqeRW9lOZsCMo7",  # AI / Machine Learning
    "selTGoJ74Jw3CP1Lp",  # Data Science
    "sel3fKJTUaxl7fHjr",  # Cybersecurity
    "selW1m49WeOuHe3KQ",  # QA / Automation
}

GOOZALI_SHARE_URL = "https://airtable.com/shrQBuWjXd0YgPqV6"
MATCH_SCORE_THRESHOLD = 60

# Title exclusions — applied at display and scoring level
EXCLUDED_TITLE_KEYWORDS = [
    "senior", "staff ", "principal", "team lead", "tech lead",
    "manager", "director", "vp ", "head of", "architect",
    "qa ", "quality", "tester", "test engineer", "test automation",
]

# Two-phase scoring: keyword pre-filter, then Claude API for top N
TOP_N_CLAUDE = 50

# For TechAviv jobs (skill-tags only, no prose description):
# if Claude scores in this range, fetch the real job page and re-score
TECHAVIV_RESCORE_MIN = 30
TECHAVIV_RESCORE_MAX = 65

# Dor's skills for keyword pre-scoring
CV_SKILLS = [
    "python", "jenkins", "github actions", "ci/cd", "devops", "groovy",
    "docker", "linux", "bash", "aws", "azure", "gcp", "microservices",
    "langraph", "ai", "automation", "cloud", "genai", "vault", "grafana",
    "kubernetes", "terraform", "ansible", "git", "shell", "scripting",
    "pipeline", "devsecops", "sre", "monitoring", "flask", "fastapi",
    "github", "sonarqube", "codeql", "spotbugs", "pmd",
    # AI / LLM product engineering keywords
    "llm", "gpt", "openai", "anthropic", "langchain", "langgraph",
    "machine learning", "deep learning", "nlp", "generative ai",
    "ai solutions", "ai developer", "ai engineer", "ai integration",
    "prompt", "rag", "vector", "embedding", "copilot",
    "salesforce", "crm", "revenue", "saas", "api integration",
    "application developer", "backend developer", "software engineer",
]
