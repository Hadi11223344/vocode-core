#!/usr/bin/env python3
"""
Seed Demo Data for VOIA Templates
====================================

Creates Google Sheets with sample data for each demo template:
- StyleHub.pk: Product catalog (ID, Name, Category, Price, Stock, Size)
- UMT Admission: Inquiry log (Name, Phone, Program, Marks, City, Status)
- SmileCare Dental: Patient records (Name, Phone, Doctor, Date, Time, Symptoms)
- UMT Outreach: Lead CRM (Name, Phone, Program, Marks, City, Follow-up Date)

Usage:
    GOOGLE_CREDS_JSON='{"type":"service_account",...}' python scripts/seed_demo_data.py
    # Or save credentials to a file and pass the path:
    python scripts/seed_demo_data.py --creds-file /path/to/service-account.json

Output:
    Prints spreadsheet IDs to paste into your integration configs.

Prerequisites:
    pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib
    Service account must have access to Google Sheets API.
"""

import argparse
import json
import os
import sys
from typing import List


def get_service(creds_json: str):
    """Build Google Sheets API service from service account JSON."""
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    creds_data = json.loads(creds_json)
    credentials = service_account.Credentials.from_service_account_info(
        creds_data,
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    return build("sheets", "v4", credentials=credentials)


def create_sheet(service, title: str) -> str:
    """Create a new spreadsheet and return its ID."""
    body = {"properties": {"title": title}}
    result = service.spreadsheets().create(body=body).execute()
    return result["spreadsheetId"]


def populate_sheet(service, spreadsheet_id: str, sheet_name: str, headers: List[str], rows: List[List[str]]):
    """Write headers and rows to a sheet."""
    data = [headers] + rows
    body = {"values": data}
    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=f"{sheet_name}!A1",
        valueInputOption="USER_ENTERED",
        body=body,
    ).execute()


def make_public(service, spreadsheet_id: str):
    """Make sheet readable by anyone with the link (simplifies demo sharing)."""
    from googleapiclient.discovery import build
    drive_service = build("drive", "v3", credentials=service._http.credentials)
    drive_service.permissions().create(
        fileId=spreadsheet_id,
        body={"role": "reader", "type": "anyone"},
    ).execute()


# ─── Demo Data ─────────────────────────────────────────────────────

STYLEHUB_HEADERS = ["Product ID", "Name", "Category", "Price (PKR)", "Stock", "Sizes"]
STYLEHUB_ROWS = [
    ["WU-001", "Embroidered Lawn Suit", "Women", "3500", "12", "S, M, L, XL"],
    ["WU-002", "Chiffon Dupatta Set", "Women", "2800", "8", "M, L"],
    ["WU-003", "Cotton Kurti", "Women", "1800", "25", "S, M, L, XL, XXL"],
    ["MU-001", "Men's Kurta Shalwar", "Men", "2200", "15", "M, L, XL"],
    ["MU-002", "Waistcoat", "Men", "1500", "10", "M, L, XL"],
    ["MU-003", "Sherwani Style Kurta", "Men", "4500", "5", "L, XL"],
    ["AC-001", "Pearl Earrings", "Accessories", "850", "30", "One Size"],
    ["AC-002", "Clutch Bag", "Accessories", "1200", "18", "One Size"],
]

UMT_ADMISSION_HEADERS = ["Timestamp", "Name", "Phone", "Program", "Intermediate Marks", "City", "Status", "Follow-up Date"]
UMT_ADMISSION_ROWS = [
    ["2026-06-01 10:30", "Ahmed Khan", "+92-300-1234567", "BSCS", "920", "Lahore", "Interested", "2026-06-05"],
    ["2026-06-01 14:15", "Fatima Ali", "+92-321-9876543", "BBA", "880", "Karachi", "Applied", "2026-06-03"],
    ["2026-06-02 09:00", "Usman Tariq", "+92-333-4567890", "BS AI", "950", "Islamabad", "Interested", "2026-06-06"],
    ["2026-06-02 16:45", "Ayesha Malik", "+92-312-6543210", "MBA", "860", "Lahore", "Call Back", "2026-06-04"],
]

SMILECARE_HEADERS = ["Patient Name", "Phone", "Doctor", "Appointment Date", "Time", "Symptoms", "Status"]
SMILECARE_ROWS = [
    ["Bilal Hussain", "+92-300-1112233", "Dr. Bilal Ahmed", "2026-06-15", "10:00", "Severe toothache, root canal needed", "Confirmed"],
    ["Sana Qureshi", "+92-321-4445566", "Dr. Sana Tariq", "2026-06-16", "14:30", "Teeth whitening consultation", "Confirmed"],
    ["Omar Farooq", "+92-333-7778899", "Dr. Imran Malik", "2026-06-17", "11:00", "Wisdom tooth extraction", "Pending"],
    ["Hina Raza", "+92-312-3334455", "Dr. Hina Rashid", "2026-06-18", "09:30", "Child's first dental checkup", "Confirmed"],
]

UMT_OUTREACH_HEADERS = ["Call Date", "Name", "Phone", "Program", "Marks", "City", "Scholarship Eligible", "Next Action", "Next Call Date"]
UMT_OUTREACH_ROWS = [
    ["2026-06-01", "Hamza Sheikh", "+92-300-2223344", "BSCS", "930", "Lahore", "Yes (75%)", "Send brochure", "2026-06-05"],
    ["2026-06-01", "Mariam Javed", "+92-321-5556677", "BBA", "890", "Faisalabad", "Yes (50%)", "Campus visit", "2026-06-08"],
    ["2026-06-02", "Zain Abbas", "+92-333-8889900", "BS SE", "910", "Rawalpindi", "Yes (75%)", "Follow-up call", "2026-06-06"],
    ["2026-06-02", "Laiba Noor", "+92-312-1112233", "MBA", "870", "Multan", "Yes (50%)", "Application link", "2026-06-07"],
]


def main():
    parser = argparse.ArgumentParser(description="Seed demo data for VOIA templates")
    parser.add_argument("--creds-file", help="Path to Google service account JSON file")
    parser.add_argument("--make-public", action="store_true", help="Make sheets publicly readable")
    args = parser.parse_args()

    # Load credentials
    creds_json = os.environ.get("GOOGLE_CREDS_JSON", "")
    if args.creds_file:
        with open(args.creds_file) as f:
            creds_json = f.read()
    if not creds_json:
        print("ERROR: Set GOOGLE_CREDS_JSON env var or use --creds-file")
        sys.exit(1)

    service = get_service(creds_json)
    print("Creating demo spreadsheets...\n")

    # StyleHub
    stylehub_id = create_sheet(service, "StyleHub.pk - Product Catalog")
    populate_sheet(service, stylehub_id, "Sheet1", STYLEHUB_HEADERS, STYLEHUB_ROWS)
    if args.make_public:
        make_public(service, stylehub_id)
    print(f"StyleHub.pk Catalog:  https://docs.google.com/spreadsheets/d/{stylehub_id}/edit")
    print(f"  Spreadsheet ID:     {stylehub_id}")
    print(f"  Use in StyleHub integration config: {{'spreadsheet_id': '{stylehub_id}'}}")
    print()

    # UMT Admission
    umt_id = create_sheet(service, "UMT Admission - Inquiry Log")
    populate_sheet(service, umt_id, "Sheet1", UMT_ADMISSION_HEADERS, UMT_ADMISSION_ROWS)
    if args.make_public:
        make_public(service, umt_id)
    print(f"UMT Admission Log:    https://docs.google.com/spreadsheets/d/{umt_id}/edit")
    print(f"  Spreadsheet ID:     {umt_id}")
    print(f"  Use in UMT integration config: {{'spreadsheet_id': '{umt_id}'}}")
    print()

    # SmileCare
    smile_id = create_sheet(service, "SmileCare Dental - Patient Records")
    populate_sheet(service, smile_id, "Sheet1", SMILECARE_HEADERS, SMILECARE_ROWS)
    if args.make_public:
        make_public(service, smile_id)
    print(f"SmileCare Records:    https://docs.google.com/spreadsheets/d/{smile_id}/edit")
    print(f"  Spreadsheet ID:     {smile_id}")
    print(f"  Use in SmileCare integration config: {{'spreadsheet_id': '{smile_id}'}}")
    print()

    # UMT Outreach
    outreach_id = create_sheet(service, "UMT Outreach - Lead CRM")
    populate_sheet(service, outreach_id, "Sheet1", UMT_OUTREACH_HEADERS, UMT_OUTREACH_ROWS)
    if args.make_public:
        make_public(service, outreach_id)
    print(f"UMT Outreach CRM:     https://docs.google.com/spreadsheets/d/{outreach_id}/edit")
    print(f"  Spreadsheet ID:     {outreach_id}")
    print(f"  Use in UMT Outreach integration config: {{'spreadsheet_id': '{outreach_id}'}}")
    print()

    print("Done! Copy the spreadsheet IDs into your integration configs.")


if __name__ == "__main__":
    main()
