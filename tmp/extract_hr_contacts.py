import csv
import re
from pathlib import Path

import pdfplumber


SOURCE = Path(r"C:\Users\user\Downloads\Tech_Company_HR_Directory.pdf")
OUTPUT = Path(r"C:\Users\user\Desktop\Knowra\hr_contacts.csv")
EMAIL_RE = re.compile(r"^[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}$", re.I)


def group_lines(words, tolerance=2.0):
    lines = []
    for word in sorted(words, key=lambda item: (item["top"], item["x0"])):
        for line in reversed(lines[-3:]):
            if abs(line[0]["top"] - word["top"]) <= tolerance:
                line.append(word)
                break
        else:
            lines.append([word])
    return [sorted(line, key=lambda item: item["x0"]) for line in lines]


contacts = []
with pdfplumber.open(SOURCE) as document:
    for page_number, page in enumerate(document.pages[:66], start=1):
        current_company = None
        current_index = None
        for line in group_lines(page.extract_words()):
            emails = [word["text"] for word in line if word["x0"] >= 590 and EMAIL_RE.match(word["text"])]
            if not emails:
                continue

            index_words = [word["text"] for word in line if word["x0"] < 65 and word["text"].isdigit()]
            company_words = [word["text"] for word in line if 65 <= word["x0"] < 240]
            if index_words and company_words:
                current_index = int(index_words[0])
                current_company = " ".join(company_words)

            if current_company is None or current_index is None:
                raise RuntimeError(f"Contact without a company on page {page_number}: {emails}")

            name_words = [word["text"] for word in line if 240 <= word["x0"] < 400]
            designation_words = [word["text"] for word in line if 400 <= word["x0"] < 590]
            contacts.append(
                {
                    "CompanyIndex": current_index,
                    "Company": current_company,
                    "HRName": " ".join(name_words),
                    "Designation": " ".join(designation_words),
                    "Email": emails[0],
                    "Page": page_number,
                }
            )

if len({row["CompanyIndex"] for row in contacts}) != 1332:
    raise RuntimeError("Did not recover all 1,332 companies")

with OUTPUT.open("w", newline="", encoding="utf-8-sig") as stream:
    writer = csv.DictWriter(stream, fieldnames=contacts[0].keys())
    writer.writeheader()
    writer.writerows(contacts)

print(f"Wrote {len(contacts)} contacts for 1,332 companies to {OUTPUT}")
