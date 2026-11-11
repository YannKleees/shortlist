"""Skills named in a posting or a CV, so a job can show what you already have and what you would still need."""

import re

# Display name -> pattern. Patterns are matched on lower case text.
SKILLS = {
    "Python": r"\bpython\b", "SQL": r"\bsql\b|postgres|mysql|t-sql", "R": r"\br\b(?![&'.\-/])(?:\s+(?:programming|language|studio)|,|\s+and\b|\s*/)",
    "pandas": r"\bpandas\b", "NumPy": r"\bnumpy\b", "scikit-learn": r"scikit|sklearn", "PyTorch": r"pytorch|\btorch\b",
    "TensorFlow": r"tensorflow|\bkeras\b", "Spark": r"\b(?:py)?spark\b", "Airflow": r"\bairflow\b", "dbt": r"\bdbt\b",
    "Docker": r"\bdocker\b", "Kubernetes": r"kubernetes|\bk8s\b", "AWS": r"\baws\b|amazon web services", "Azure": r"\bazure\b",
    "Google Cloud": r"\bgcp\b|google cloud|bigquery", "Power BI": r"power ?bi", "Tableau": r"\btableau\b", "Excel": r"\bexcel\b",
    "Git": r"\bgit\b|github|gitlab", "Java": r"\bjava\b(?!script)", "JavaScript": r"javascript|\bnode\.?js\b",
    "TypeScript": r"typescript", "C++": r"c\+\+", "Scala": r"\bscala\b", "Statistics": r"statisti",
    "Machine learning": r"machine learning|\bml\b", "Deep learning": r"deep learning|neural network", "NLP": r"\bnlp\b|natural language",
    "Computer vision": r"computer[- ]vision|object detection", "LLMs": r"\bllms?\b|large language model|genai|generative ai", "MLOps": r"mlops",
    "Snowflake": r"snowflake", "Databricks": r"databricks", "Looker": r"\blooker\b", "SAS": r"\bsas\b", "MATLAB": r"matlab",
    "Linux": r"\blinux\b", "REST APIs": r"\brest\b|\bapis?\b", "React": r"\breact\b", "Kafka": r"\bkafka\b",
    "A/B testing": r"a/b test|ab test|experimentation", "Time series": r"time[- ]series|forecast", "ETL": r"\betl\b|\belt\b|data pipeline",
    "Data visualisation": r"visuali[sz]", "Optimisation": r"optimi[sz]ation|operations research",
    "FastAPI": r"fastapi", "Flask": r"\bflask\b", "Rust": r"\brust\b", "Hugging Face": r"hugging ?face",
    "Recommender systems": r"recommend(?:er|ation)s? (?:system|engine)|recsys",
}
# The same skills in the groups a reader looks for. A skill that is not listed here falls under "Other".
GROUPS = {
    "Languages": ["Python", "SQL", "R", "Java", "JavaScript", "TypeScript", "C++", "Scala", "Rust", "MATLAB", "SAS"],
    "Data and machine learning": ["pandas", "NumPy", "scikit-learn", "PyTorch", "TensorFlow", "Hugging Face", "Statistics", "Machine learning",
                                  "Deep learning", "NLP", "Computer vision", "LLMs", "Recommender systems", "Time series", "A/B testing",
                                  "Optimisation"],
    "Data engineering": ["ETL", "Spark", "Airflow", "dbt", "Kafka", "Snowflake", "Databricks", "Docker", "Kubernetes", "AWS", "Azure",
                         "Google Cloud", "MLOps", "Linux", "Git"],
    "Reporting and web": ["Power BI", "Tableau", "Excel", "Looker", "Data visualisation", "REST APIs", "FastAPI", "Flask", "React"],
}
GROUP_OF = {s: g for g, names in GROUPS.items() for s in names}
# Fields of work rather than tools: the words that say what kind of data person you are.
FIELDS = ("Computer vision", "NLP", "Recommender systems", "LLMs", "Time series", "A/B testing", "Optimisation", "MLOps", "Data visualisation")
_COMPILED = {name: re.compile(p) for name, p in SKILLS.items()}


def find_skills(text):
    t = (text or "").lower()
    return [name for name, p in _COMPILED.items() if p.search(t)]


def gaps(posting, cv, required_languages=(), spoken=()):
    """(have, need): skills the posting names that the CV shows, and the ones it does not, plus missing languages."""
    asked = find_skills(posting)
    mine = set(find_skills(cv))
    have = [s for s in asked if s in mine]
    need = [s for s in asked if s not in mine] if cv else []
    need += [lg for lg in required_languages if lg not in spoken]
    return have, need
