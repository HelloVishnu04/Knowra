import csv
import html
import json
import re
from pathlib import Path


CONTACTS = Path(r"C:\Users\user\Desktop\Knowra\hr_contacts.csv")
CSV_OUTPUT = Path(r"C:\Users\user\Desktop\Knowra\software_trainee_campaign_100.csv")
JSON_OUTPUT = Path(r"C:\Users\user\Desktop\Knowra\tmp\software_trainee_campaign_100.json")

KNOWN_BOOST = {
    "Accops Systems", "Accubits Technologies", "AppViewX", "Atlan", "Aujas Cybersecurity",
    "Blackstraw.ai", "Blancco Technology Group", "CleverTap", "CloudSEK", "ContractPodAi",
    "Crayon Data", "DataCore Software", "Detect Technologies", "ElectrifAi", "Entropik Tech",
    "Gupshup", "Haptik", "LambdaTest", "Mindtickle", "Observe.AI", "Scienaptic AI",
    "Secomind.AI", "SecureKloud Technologies", "SirionLabs", "SpringML", "SuperOps.ai",
    "Symphony RetailAI", "Symphony SummitAI", "SysCloud", "Talentica Software", "Tata Digital",
    "Uniphore", "Versa Networks", "Virsec Systems", "Wavicle Data Solutions", "WebEngage",
    "Wobot.ai", "Zaggle Prepaid Ocean Services", "Zemoso Technologies", "ZiMetrics Technologies",
    "Zuci Systems", "5ireChain", "360 Degree Cloud Technologies", "Aeries Technology Group",
    "AFour Technologies", "Algonomy", "Apty", "Arya.ag", "Avataar.Me", "Azilen Technologies",
    "Bidgely", "Birdeye", "CloudMoyo", "CloudThat", "Cloud Analogy", "cloudEQ", "CodeCraft Technologies",
    "Codilar Technologies", "Codingmart Technologies", "CropIn Technology", "Daffodil Software",
    "Deque Systems", "DLT Labs", "Eka Software Solutions", "eGain Corporation", "Soliton Technologies",
    "SourceFuse Technologies", "TestVagrant Technologies", "Volante Technologies", "Winjit Technologies",
}

KEYWORD_SCORES = [
    (r"(^|[^a-z])(ai|ml)([^a-z]|$)", 12),
    (r"analytics|intelligence", 10),
    (r"cyber|security|secure|virsec", 10),
    (r"cloud|data centre|data center", 9),
    (r"(^|[^a-z])data([^a-z]|$)", 8),
    (r"software|product", 7),
    (r"systems|technologies|technology|tech$", 5),
    (r"digital|labs|network|automation", 4),
]

CATEGORY_OVERRIDES = {
    "Accubits Technologies": "AI/ML",
    "Atlan": "Data/Analytics",
    "Avataar.Me": "AI/ML",
    "Bidgely": "AI/ML",
    "CloudSEK": "Cybersecurity",
    "ContractPodAi": "AI/ML",
    "Detect Technologies": "AI/ML",
    "ElectrifAi": "AI/ML",
    "Kiya.ai": "FinTech",
    "SpringML": "AI/ML",
    "ST Telemedia Global Data Centres": "Cloud/Infrastructure",
    "Symphony RetailAI": "AI/ML",
    "Symphony SummitAI": "AI/ML",
}


def designation_score(value):
    text = value.lower()
    score = 0
    if "campus" in text:
        score += 12
    if "talent acquisition" in text or "recruitment" in text or "recruiter" in text:
        score += 9
    if "people" in text or "human resources" in text or "hr" in text:
        score += 4
    if "chief" in text or "vice president" in text or "director" in text:
        score -= 1
    return score


def company_score(company):
    lowered = company.lower()
    score = 25 if company in KNOWN_BOOST else 0
    for pattern, points in KEYWORD_SCORES:
        if re.search(pattern, lowered):
            score += points
    if re.search(r"staffing|recruitment services|manpower", lowered):
        score -= 15
    return score


def category_for(company):
    if company in CATEGORY_OVERRIDES:
        return CATEGORY_OVERRIDES[company]
    lowered = company.lower()
    if re.search(r"cyber|security|secure|accops|blancco|deque|virsec", lowered):
        return "Cybersecurity"
    if re.search(r"health|medical|5c network", lowered):
        return "HealthTech"
    if re.search(r"pay|fin|bank|credit|zaggle|5ire|fintech", lowered):
        return "FinTech"
    if re.search(r"(^|[^a-z])(ai|ml)([^a-z]|$)|analytics|intelligence|haptik|uniphore|gupshup|algonomy|entropik", lowered):
        return "AI/ML"
    if re.search(r"cloud|network|data centre|data center|syscloud|versa", lowered):
        return "Cloud/Infrastructure"
    if re.search(r"(^|[^a-z])data([^a-z]|$)|sigmoid|zimetrics|wavicle|crayon", lowered):
        return "Data/Analytics"
    if re.search(r"software|saas|product|labs|appview|clevertap|webengage|mindtickle|lambdatest|superops|siri(on|us)", lowered):
        return "SaaS/Product"
    return "Software Engineering"


def hook_and_evidence(company, category):
    hooks = {
        "AI/ML": (
            f"What draws me to {company} is the opportunity to work on AI-led products where model quality and dependable full-stack delivery matter together.",
            "During my IBM SkillsBuild internship, I built Recon, a cyber-threat detection platform with a scikit-learn model, FastAPI inference service, and Flask dashboard. I also implemented a GPT-1-style language model in TensorFlow, including a custom BPE tokenizer and training pipeline.",
        ),
        "Cybersecurity": (
            f"I am particularly interested in {company} because security products demand careful engineering, trustworthy APIs, and clear responses to real operational risks.",
            "That connects directly with Recon, the cyber-threat detection platform I built during my IBM SkillsBuild internship. It classifies network traffic into five threat categories and returns confidence, severity, and recommended actions through a FastAPI service and Flask dashboard.",
        ),
        "Cloud/Infrastructure": (
            f"I am drawn to the infrastructure-oriented engineering work at {company}, where reliability, deployment discipline, and clean service boundaries are essential.",
            "My recent work includes a dual-server FastAPI and Flask system packaged with Docker Compose, CI/CD workflows through GitHub Actions, and hands-on use of AWS, OCI, PostgreSQL, Redis, and Linux.",
        ),
        "Data/Analytics": (
            f"I am interested in {company} because building useful data products requires both a sound analytical pipeline and an interface that makes results actionable.",
            "I have built Python data pipelines with Pandas and scikit-learn, including EDA, imputation, scaling, feature selection, model serialization, and REST deployment. My projects also use PostgreSQL, Supabase, PyTorch, TensorFlow, and XGBoost.",
        ),
        "FinTech": (
            f"I am interested in contributing to {company}, where dependable backend services, well-designed APIs, and careful handling of data are central to the product experience.",
            "As a freelance developer, I delivered an end-to-end Laravel ERP system, owning the database design, backend logic, and user interface. I have also built authenticated React and FastAPI applications using PostgreSQL, Supabase, JWT, Docker, and CI/CD.",
        ),
        "HealthTech": (
            f"I am especially interested in {company} because health technology benefits from engineering that turns complex data into clear and responsible user experiences.",
            "One of my projects, MediPredict, combines four machine-learning models in a validated Streamlit interface for disease-risk prediction. I also build full-stack systems with Python, FastAPI, React, PostgreSQL, Docker, and CI/CD.",
        ),
        "SaaS/Product": (
            f"I am drawn to {company}'s product-engineering environment and the challenge of turning real user needs into reliable, maintainable software.",
            "I have delivered an end-to-end Laravel ERP system for a startup client and built S.A.F.E., a React 19, TypeScript, FastAPI, PyTorch, and Supabase application with authentication, persistent user data, and CI/CD.",
        ),
        "Software Engineering": (
            f"I am reaching out because {company} looks like the kind of engineering environment where I could learn quickly while contributing to real product delivery.",
            "My experience spans JavaScript, TypeScript, Python, SQL, C++, React, FastAPI, Flask, Laravel, PostgreSQL, Docker, and GitHub Actions. I have independently delivered a startup ERP system and several full-stack AI applications.",
        ),
    }
    return hooks[category]


with CONTACTS.open(encoding="utf-8-sig", newline="") as stream:
    rows = list(csv.DictReader(stream))

by_company = {}
for row in rows:
    by_company.setdefault(row["CompanyIndex"], []).append(row)

selected_contacts = []
for contacts in by_company.values():
    contact = max(contacts, key=lambda row: designation_score(row["Designation"]))
    contact["Score"] = company_score(contact["Company"]) + designation_score(contact["Designation"])
    selected_contacts.append(contact)

selected_contacts.sort(key=lambda row: (-int(row["Score"]), row["Company"].lower()))
selected_contacts = selected_contacts[:100]

campaign = []
for sequence, row in enumerate(selected_contacts, start=1):
    company = row["Company"]
    category = category_for(company)
    hook, evidence = hook_and_evidence(company, category)
    first_name = row["HRName"].split()[0]
    body = f"""<p>Dear {html.escape(first_name)},</p>
<p>I am writing to explore a <strong>Software Engineer Trainee</strong> opportunity at <strong>{html.escape(company)}</strong>. {html.escape(hook)}</p>
<p>{html.escape(evidence)}</p>
<p>I am currently pursuing a B.Tech in Computer Science at Anand Engineering College and expect to graduate in 2027. I would value the opportunity to contribute my practical development experience, problem-solving mindset, and willingness to learn within your engineering team.</p>
<p>I have attached my résumé for your consideration. If there is a suitable trainee or entry-level software engineering opportunity at {html.escape(company)}, I would be grateful for a chance to discuss it.</p>
<p>Thank you for your time.</p>
<p>Warm regards,<br>
Vishnu Kumar<br>
+91 90278 72285<br>
<a href=\"mailto:dev.vishnu.git@gmail.com\">dev.vishnu.git@gmail.com</a><br>
<a href=\"https://github.com/HelloVishnu04\">github.com/HelloVishnu04</a></p>"""
    campaign.append(
        {
            "Sequence": sequence,
            "Company": company,
            "Category": category,
            "HRName": row["HRName"],
            "Designation": row["Designation"],
            "Email": row["Email"],
            "Subject": "Application for the Software Engineer Trainee",
            "BodyHTML": body,
            "Status": "Ready",
        }
    )

with CSV_OUTPUT.open("w", encoding="utf-8-sig", newline="") as stream:
    writer = csv.DictWriter(stream, fieldnames=campaign[0].keys())
    writer.writeheader()
    writer.writerows(campaign)

JSON_OUTPUT.write_text(json.dumps(campaign, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"Prepared {len(campaign)} personalized messages")
print("Category counts:")
for category in sorted({row['Category'] for row in campaign}):
    print(f"  {category}: {sum(row['Category'] == category for row in campaign)}")
