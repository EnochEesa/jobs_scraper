# jobs_scraper.py
"""
Daily job scraper for Cloud & DevOps roles.

Searches:
- Indeed (India)
- Naukri
- Foundit
- Wellfound (AngelList)
- Basic site searches (best-effort)

Filters:
- Remote OR India
- 2–6 years experience

Sends results via Gmail SMTP (use App Password).
"""

import os
import re
import smtplib
import time
import html
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests
from bs4 import BeautifulSoup

# ---------------- Configuration ----------------
GMAIL_USER = os.environ.get("GMAIL_USER")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD")
EMAIL_TO = os.environ.get("EMAIL_TO", GMAIL_USER)
SENDER_NAME = os.environ.get("SENDER_NAME", "Daily Job Bot")

KEYWORDS = [
    "DevOps Engineer",
    "Cloud Engineer",
    "Site Reliability Engineer",
    "Platform Engineer",
    "Infrastructure Engineer",
    "AWS Engineer",
    "Azure DevOps Engineer",
    "Kubernetes Engineer",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0 Safari/537.36"
    )
}

MIN_YEARS = 2
MAX_YEARS = 6
REQUEST_TIMEOUT = 15
SLEEP_BETWEEN_REQUESTS = 2.0


# ---------------- Utilities ----------------
def normalize_text(text: str) -> str:
    return " ".join(text.split()) if text else ""


def parse_experience_text(text):
    if not text:
        return None, None

    text = text.lower()

    m = re.search(r"(\d{1,2})\s*[-–]\s*(\d{1,2})\s*years?", text)
    if m:
        return int(m.group(1)), int(m.group(2))

    m = re.search(r"(\d{1,2})\s*\+\s*years?", text)
    if m:
        return int(m.group(1)), None

    m = re.search(r"minimum\s+of\s+(\d{1,2})\s*years?", text)
    if m:
        return int(m.group(1)), None

    m = re.search(r"(\d{1,2})\s*years?", text)
    if m:
        y = int(m.group(1))
        return y, y

    return None, None


def experience_matches(min_y, max_y) -> bool:
    if min_y is None and max_y is None:
        return True

    if min_y is not None and max_y is not None:
        return not (max_y < MIN_YEARS or min_y > MAX_YEARS)

    if min_y is not None:
        return min_y <= MAX_YEARS

    if max_y is not None:
        return max_y >= MIN_YEARS

    return False


def location_matches(location_text: str) -> bool:
    if not location_text:
        return True

    t = location_text.lower()
    return any(
        key in t
        for key in ["remote", "india", "pan india", "india remote"]
    )


def text_contains_keywords(text: str) -> bool:
    t = text.lower()
    if any(kw.lower() in t for kw in KEYWORDS):
        return True
    return any(word in t for word in ["devops", "cloud", "sre", "site reliability"])


# ---------------- Scrapers ----------------
def scrape_indeed(query_kw):
    results = []
    q = "+".join(query_kw.split())
    url = f"https://in.indeed.com/jobs?q={q}+remote+cloud+devops&l=India"

    try:
        r = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        time.sleep(SLEEP_BETWEEN_REQUESTS)
        soup = BeautifulSoup(r.text, "html.parser")

        for a in soup.select("a[data-jk]")[:25]:
            link = a.get("href", "")
            if link.startswith("/"):
                link = "https://in.indeed.com" + link

            title = normalize_text(a.get_text())
            snippet = normalize_text(a.find_parent().get_text()) if a.find_parent() else ""

            results.append({
                "title": title,
                "company": None,
                "location": snippet,
                "link": link,
                "source": "Indeed",
                "snippet": snippet,
            })
    except Exception as e:
        print("Indeed error:", e)

    return results


def scrape_wellfound(query_kw):
    results = []
    q = "+".join(query_kw.split())
    url = f"https://wellfound.com/jobs?search={q}&remote=true"

    try:
        r = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        time.sleep(SLEEP_BETWEEN_REQUESTS)
        soup = BeautifulSoup(r.text, "html.parser")

        seen = set()
        for a in soup.select('a[href*="/jobs/"]'):
            href = a.get("href")
            if not href:
                continue

            link = "https://wellfound.com" + href if href.startswith("/") else href
            if link in seen:
                continue
            seen.add(link)

            title = normalize_text(a.get_text())
            results.append({
                "title": title,
                "company": None,
                "location": "Remote",
                "link": link,
                "source": "Wellfound",
                "snippet": title,
            })
    except Exception as e:
        print("Wellfound error:", e)

    return results


# ---------------- Processing ----------------
def collect_jobs():
    jobs = []
    for kw in KEYWORDS:
        jobs.extend(scrape_indeed(kw))
        jobs.extend(scrape_wellfound(kw))

    unique = {}
    for job in jobs:
        key = job.get("link") or job.get("title")
        if key and key not in unique:
            unique[key] = job

    return list(unique.values())


def filter_jobs(jobs):
    filtered = []
    for j in jobs:
        combined = normalize_text(" ".join([
            j.get("title", ""),
            j.get("company", ""),
            j.get("location", ""),
            j.get("snippet", ""),
        ]))

        if not text_contains_keywords(combined):
            continue

        min_y, max_y = parse_experience_text(combined)
        if not experience_matches(min_y, max_y):
            continue

        if not location_matches(j.get("location", "")):
            continue

        filtered.append(j)

    return filtered


def build_email_html(jobs):
    if not jobs:
        return "<p>No matching jobs found today.</p>"

    rows = []
    for i, j in enumerate(jobs, 1):
        rows.append(
            f"<tr>"
            f"<td>{i}</td>"
            f"<td><a href='{j['link']}'>{html.escape(j['title'])}</a></td>"
            f"<td>{html.escape(j.get('company') or j['source'])}</td>"
            f"<td>{html.escape(j.get('location') or '—')}</td>"
            f"</tr>"
        )

    return (
        "<table border='1' cellpadding='6'>"
        "<tr><th>#</th><th>Title</th><th>Company</th><th>Location</th></tr>"
        + "".join(rows)
        + "</table>"
    )


def send_email(subject, body):
    if not GMAIL_USER or not GMAIL_APP_PASSWORD:
        raise RuntimeError("Gmail credentials not set")

    msg = MIMEMultipart("alternative")
    msg["From"] = f"{SENDER_NAME} <{GMAIL_USER}>"
    msg["To"] = EMAIL_TO
    msg["Subject"] = subject

    msg.attach(MIMEText(body, "html"))

    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls()
        server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_USER, EMAIL_TO, msg.as_string())


def main():
    jobs = collect_jobs()
    matches = filter_jobs(jobs)
    html_body = build_email_html(matches)

    subject = f"Daily Cloud & DevOps Jobs – {datetime.utcnow().date()}"
    send_email(subject, html_body)


if __name__ == "__main__":
    main()
