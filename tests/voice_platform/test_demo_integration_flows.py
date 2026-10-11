"""
End-to-End Integration Tests for Demo Templates
================================================

Exercises every tool in the 4 demo agent templates against real services:
- SmileCare Dental: Calendar + Sheets + SMS
- StyleHub.pk: Sheets + Email
- UMT Admission: Sheets + Email
- UMT Outreach: Calendar + Sheets

Credentials required via environment variables.
Tests skip gracefully when credentials are absent.

Run:
    GOOGLE_CREDS_FILE=/path/to/sa.json \
    TWILIO_ACCOUNT_SID=ACxxx TWILIO_AUTH_TOKEN=xxx TWILIO_FROM_NUMBER=+1xxx \
    TEST_PHONE_NUMBER=+92xxx \
    SMTP_HOST=smtp.gmail.com SMTP_PORT=587 SMTP_USER=user@gmail.com \
    SMTP_PASSWORD=app-password SMTP_FROM_EMAIL=user@gmail.com \
    TEST_EMAIL=test@example.com \
    pytest tests/voice_platform/test_demo_integration_flows.py -v
"""

import json
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from voice_platform.database import GoogleOAuthToken, Integration, User, UserApiKey
from voice_platform.encryption import encrypt
from voice_platform.integrations.executor import WorkflowExecutor
from voice_platform.integrations.plugins.registry import build_default_plugin_registry

# ── Credential checks ────────────────────────────────────────────────────

_HAS_GOOGLE = bool(
    os.environ.get("GOOGLE_CREDS_FILE")
    or os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    or os.path.exists("/tmp/google_oauth_tokens.json")
)
_HAS_TWILIO = bool(os.environ.get("TWILIO_ACCOUNT_SID") and os.environ.get("TWILIO_AUTH_TOKEN") and os.environ.get("TWILIO_FROM_NUMBER") and os.environ.get("TEST_PHONE_NUMBER"))
_HAS_SMTP = bool(os.environ.get("SMTP_HOST") and os.environ.get("SMTP_USER") and os.environ.get("SMTP_PASSWORD") and os.environ.get("SMTP_FROM_EMAIL") and os.environ.get("TEST_EMAIL"))

SKIP_GOOGLE = pytest.mark.skipif(not _HAS_GOOGLE, reason="Google credentials not set (GOOGLE_CREDS_FILE or GOOGLE_SERVICE_ACCOUNT_JSON)")
SKIP_TWILIO = pytest.mark.skipif(not _HAS_TWILIO, reason="Twilio credentials not set (TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER, TEST_PHONE_NUMBER)")
SKIP_SMTP = pytest.mark.skipif(not _HAS_SMTP, reason="SMTP credentials not set (SMTP_HOST, SMTP_USER, SMTP_PASSWORD, SMTP_FROM_EMAIL, TEST_EMAIL)")


# ── Helpers ────────────────────────────────────────────────────────────────

async def _create_api_key(db: AsyncSession, user: User, service: str, key_value: str, secret: str = "", metadata: dict = None) -> UserApiKey:
    """Insert a UserApiKey for a real service."""
    key = UserApiKey(
        user_id=user.id,
        service=service,
        api_key=key_value,
        api_secret=secret or None,
        metadata_json=json.dumps(metadata or {}),
        label=f"Test {service}",
    )
    db.add(key)
    await db.commit()
    await db.refresh(key)
    return key


async def _create_integration(db: AsyncSession, user: User, service_type: str, api_key: UserApiKey, config: dict, name: str) -> Integration:
    """Insert an Integration linked to an API key."""
    integ = Integration(
        user_id=user.id,
        service_type=service_type,
        name=name,
        api_key_id=api_key.id,
        config_json=json.dumps(config),
        is_active=True,
    )
    db.add(integ)
    await db.commit()
    await db.refresh(integ)
    return integ


async def _get_google_creds() -> str:
    """Return the Google service account JSON string."""
    creds_file = os.environ.get("GOOGLE_CREDS_FILE", "")
    if creds_file:
        with open(creds_file) as f:
            return f.read()
    return os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "")


async def _run_step(executor: WorkflowExecutor, integration_id: int, action: str, params: dict) -> dict:
    """Execute a single step via WorkflowExecutor."""
    step = {
        "integration_id": integration_id,
        "action": action,
        "params": params,
    }
    result = await executor.execute_single_step(step)
    return result


# ── Fixtures ───────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def google_api_key(db_session: AsyncSession, test_user: User) -> UserApiKey:
    """Real Google service account key (shared for Calendar + Sheets + Drive)."""
    creds = await _get_google_creds()
    return await _create_api_key(db_session, test_user, "google", creds)


@pytest_asyncio.fixture
async def twilio_api_key(db_session: AsyncSession, test_user: User) -> UserApiKey:
    """Real Twilio credentials."""
    return await _create_api_key(
        db_session, test_user, "twilio",
        key_value=os.environ.get("TWILIO_ACCOUNT_SID", ""),
        secret=os.environ.get("TWILIO_AUTH_TOKEN", ""),
        metadata={"from_number": os.environ.get("TWILIO_FROM_NUMBER", "")},
    )


@pytest_asyncio.fixture
async def smtp_api_key(db_session: AsyncSession, test_user: User) -> UserApiKey:
    """Real SMTP credentials stored as JSON."""
    smtp_config = {
        "host": os.environ.get("SMTP_HOST", ""),
        "port": int(os.environ.get("SMTP_PORT", "587")),
        "username": os.environ.get("SMTP_USER", ""),
        "password": os.environ.get("SMTP_PASSWORD", ""),
        "from_email": os.environ.get("SMTP_FROM_EMAIL", ""),
        "use_tls": True,
    }
    return await _create_api_key(db_session, test_user, "email", json.dumps(smtp_config))


@pytest_asyncio.fixture
async def executor(db_session: AsyncSession, test_user: User) -> WorkflowExecutor:
    """WorkflowExecutor instance for the test user."""
    return WorkflowExecutor(session=db_session, user_id=test_user.id, plugin_registry=build_default_plugin_registry())


@pytest_asyncio.fixture
async def google_oauth(db_session: AsyncSession, test_user: User):
    """Seed Google OAuth tokens into DB if temp token file exists."""
    token_path = "/tmp/google_oauth_tokens.json"
    if not os.path.exists(token_path):
        return
    with open(token_path) as f:
        data = json.load(f)
    from sqlalchemy import delete
    await db_session.execute(delete(GoogleOAuthToken).where(GoogleOAuthToken.user_id == test_user.id))
    token = GoogleOAuthToken(
        user_id=test_user.id,
        access_token=encrypt(data["access_token"]),
        refresh_token=encrypt(data["refresh_token"]),
        token_type=data.get("token_type", "Bearer"),
        expires_at=datetime.fromisoformat(data["expires_at"]),
        scopes=json.dumps(data.get("scopes", [])),
    )
    db_session.add(token)
    await db_session.commit()


# ─── Test A: SmileCare Dental — Appointment Booking Flow ──────────────────

@pytest.mark.asyncio
@SKIP_GOOGLE
@SKIP_TWILIO
async def test_smilecare_dental_flow(
    db_session: AsyncSession,
    test_user: User,
    google_api_key: UserApiKey,
    twilio_api_key: UserApiKey,
    executor: WorkflowExecutor,
    google_oauth,
):
    """
    SmileCare Dental full flow:
    1. Check calendar availability
    2. Book appointment (create calendar event)
    3. Append patient record to sheet
    4. Send SMS confirmation
    5. Cleanup
    """
    # -- Setup integrations --
    tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")
    calendar_integ = await _create_integration(
        db_session, test_user, "google_calendar", google_api_key,
        config={"calendar_id": "primary", "timezone": "UTC"},
        name="SmileCare Calendar",
    )
    sheets_integ = await _create_integration(
        db_session, test_user, "google_sheets", google_api_key,
        config={"spreadsheet_id": "", "sheet_name": "Sheet1"},
        name="SmileCare Patients",
    )
    sms_integ = await _create_integration(
        db_session, test_user, "sms", twilio_api_key,
        config={"account_sid": os.environ["TWILIO_ACCOUNT_SID"], "from_number": os.environ["TWILIO_FROM_NUMBER"]},
        name="SmileCare SMS",
    )

    # 1. Check availability
    avail = await _run_step(executor, calendar_integ.id, "check_availability", {
        "date": tomorrow,
        "duration_minutes": 30,
    })
    assert "busy_slots" in avail or "available_slots" in avail, f"Availability check failed: {avail}"

    # 2. Book appointment
    booking = await _run_step(executor, calendar_integ.id, "book_appointment", {
        "date": tomorrow,
        "time": "14:00",
        "duration_minutes": 30,
        "purpose": "Dental cleaning — SmileCare Test",
        "location": "MM Alam Road, Gulberg III, Lahore",
    })
    assert booking.get("success", False) or "event_id" in booking or "id" in booking, f"Booking failed: {booking}"
    event_id = booking.get("event_id") or booking.get("id")

    # 3. Append patient record to sheet
    sheet_result = await _run_step(executor, sheets_integ.id, "append_row", {
        "values": ["Test Patient", "+92-300-1234567", "Dr. Bilal", tomorrow, "14:00", "Cleaning", "Confirmed"],
    })
    assert isinstance(sheet_result, dict), "Sheet append should return a dict"

    # 4. Send SMS confirmation
    sms_result = await _run_step(executor, sms_integ.id, "send_sms", {
        "to": os.environ["TEST_PHONE_NUMBER"],
        "body": f"SmileCare Dental: Your appointment is confirmed for {tomorrow} at 2:00 PM. Dr. Bilal, MM Alam Road.",
    })
    assert isinstance(sms_result, dict), "SMS should return a dict"

    # 5. Cleanup — delete calendar event
    if event_id:
        await _run_step(executor, calendar_integ.id, "delete_event", {"event_id": event_id})

    print(f"SmileCare flow completed. Booking: {booking}")


# ─── Test B: StyleHub.pk — Order Processing Flow ──────────────────────────

@pytest.mark.asyncio
@SKIP_GOOGLE
@SKIP_SMTP
async def test_stylehub_order_flow(
    db_session: AsyncSession,
    test_user: User,
    google_api_key: UserApiKey,
    smtp_api_key: UserApiKey,
    executor: WorkflowExecutor,
    google_oauth,
):
    """
    StyleHub.pk full flow:
    1. Create a temp spreadsheet with product catalog
    2. Read product catalog
    3. Append order to sheet
    4. Send email confirmation
    5. Cleanup (delete temp spreadsheet)
    """
    # -- Create temp spreadsheet with catalog --
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    creds_json = await _get_google_creds()
    credentials = service_account.Credentials.from_service_account_info(
        json.loads(creds_json),
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    sheets_service = build("sheets", "v4", credentials=credentials)
    spreadsheet = sheets_service.spreadsheets().create(body={"properties": {"title": f"StyleHub Test {uuid.uuid4().hex[:8]}"}}).execute()
    spreadsheet_id = spreadsheet["spreadsheetId"]

    headers = ["Product ID", "Name", "Category", "Price (PKR)", "Stock", "Sizes"]
    rows = [
        ["WU-001", "Embroidered Lawn Suit", "Women", "3500", "12", "S, M, L, XL"],
        ["WU-003", "Cotton Kurti", "Women", "1800", "25", "S, M, L, XL, XXL"],
    ]
    sheets_service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range="Sheet1!A1",
        valueInputOption="USER_ENTERED",
        body={"values": [headers] + rows},
    ).execute()

    # -- Setup integrations --
    sheets_integ = await _create_integration(
        db_session, test_user, "google_sheets", google_api_key,
        config={"spreadsheet_id": spreadsheet_id, "sheet_name": "Sheet1"},
        name="StyleHub Catalog",
    )
    email_integ = await _create_integration(
        db_session, test_user, "email", smtp_api_key,
        config={"from_email": os.environ["SMTP_FROM_EMAIL"], "from_name": "StyleHub.pk"},
        name="StyleHub Email",
    )

    # 1. Read product catalog
    catalog = await _run_step(executor, sheets_integ.id, "read_rows", {
        "range": "Sheet1!A1:F3",
    })
    assert "rows" in catalog or "values" in catalog, f"Read failed: {catalog}"
    data = catalog.get("rows") or catalog.get("values", [])
    assert len(data) >= 2, "Catalog should have header + at least 1 row"

    # 2. Append order
    order_row = ["WU-001", "S", "Red", "1", "Ayesha Khan", "Gulberg, Lahore", "+92-300-1112233", "COD", tomorrow]
    append_result = await _run_step(executor, sheets_integ.id, "append_row", {
        "values": order_row,
    })
    assert isinstance(append_result, dict), "Append should return dict"

    # 3. Send email confirmation
    email_result = await _run_step(executor, email_integ.id, "send_email", {
        "to": os.environ["TEST_EMAIL"],
        "subject": "StyleHub.pk Order Confirmation",
        "body": f"Thank you for your order! Product: WU-001, Size: S, Color: Red. Total: PKR 3,500. Estimated delivery: {tomorrow}.",
    })
    assert isinstance(email_result, dict), "Email should return dict"
    assert email_result.get("success") is True, f"Email send failed: {email_result.get('error', 'unknown')}"

    # 4. Cleanup — delete temp spreadsheet via Drive API
    drive_service = build("drive", "v3", credentials=credentials)
    drive_service.files().delete(fileId=spreadsheet_id).execute()

    print(f"StyleHub flow completed. Spreadsheet: {spreadsheet_id}")


# ─── Test C: UMT Admission — Inquiry Logging Flow ────────────────────────

@pytest.mark.asyncio
@SKIP_GOOGLE
@SKIP_SMTP
async def test_umt_admission_flow(
    db_session: AsyncSession,
    test_user: User,
    google_api_key: UserApiKey,
    smtp_api_key: UserApiKey,
    executor: WorkflowExecutor,
    google_oauth,
):
    """
    UMT Admission full flow:
    1. Create temp sheet with inquiry log
    2. Read existing inquiries
    3. Append new student inquiry
    4. Send email with admission brochure
    5. Cleanup
    """
    # -- Create temp spreadsheet --
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    creds_json = await _get_google_creds()
    credentials = service_account.Credentials.from_service_account_info(
        json.loads(creds_json),
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    sheets_service = build("sheets", "v4", credentials=credentials)
    spreadsheet = sheets_service.spreadsheets().create(body={"properties": {"title": f"UMT Test {uuid.uuid4().hex[:8]}"}}).execute()
    spreadsheet_id = spreadsheet["spreadsheetId"]

    headers = ["Timestamp", "Name", "Phone", "Program", "Marks", "City", "Status", "Follow-up Date"]
    sample = [["2026-06-01 10:30", "Ahmed Khan", "+92-300-1234567", "BSCS", "920", "Lahore", "Interested", "2026-06-05"]]
    sheets_service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range="Sheet1!A1",
        valueInputOption="USER_ENTERED",
        body={"values": [headers] + sample},
    ).execute()

    # -- Setup integrations --
    sheets_integ = await _create_integration(
        db_session, test_user, "google_sheets", google_api_key,
        config={"spreadsheet_id": spreadsheet_id, "sheet_name": "Sheet1"},
        name="UMT Inquiries",
    )
    email_integ = await _create_integration(
        db_session, test_user, "email", smtp_api_key,
        config={"from_email": os.environ["SMTP_FROM_EMAIL"], "from_name": "UMT Admissions"},
        name="UMT Email",
    )

    # 1. Read existing inquiries
    inquiries = await _run_step(executor, sheets_integ.id, "read_rows", {
        "range": "Sheet1!A1:H2",
    })
    data = inquiries.get("rows") or inquiries.get("values", [])
    assert len(data) >= 1, "Should have at least header row"

    # 2. Append new inquiry
    new_inquiry = [datetime.now().strftime("%Y-%m-%d %H:%M"), "Fatima Ali", "+92-321-9876543", "BBA", "880", "Karachi", "New", tomorrow]
    append_result = await _run_step(executor, sheets_integ.id, "append_row", {
        "values": new_inquiry,
    })
    assert isinstance(append_result, dict), "Append should return dict"

    # 3. Send brochure email
    email_result = await _run_step(executor, email_integ.id, "send_email", {
        "to": os.environ["TEST_EMAIL"],
        "subject": "UMT Lahore — Your Admission Guide",
        "body": (
            "Assalam-o-Alaikum Fatima!\n\n"
            "Thank you for your interest in UMT. Based on your Intermediate marks (880), "
            "you are eligible for a 50% scholarship on our BBA program. "
            "Apply at admissions.umt.edu.pk.\n\n"
            "Best regards,\nUMT Admissions Team"
        ),
    })
    assert isinstance(email_result, dict), "Email should return dict"
    assert email_result.get("success") is True, f"Email send failed: {email_result.get('error', 'unknown')}"

    # 4. Cleanup
    drive_service = build("drive", "v3", credentials=credentials)
    drive_service.files().delete(fileId=spreadsheet_id).execute()

    print(f"UMT Admission flow completed. Spreadsheet: {spreadsheet_id}")


# ─── Test D: UMT Outreach — Lead Qualification Flow ──────────────────────

@pytest.mark.asyncio
@SKIP_GOOGLE
async def test_umt_outreach_flow(
    db_session: AsyncSession,
    test_user: User,
    google_api_key: UserApiKey,
    executor: WorkflowExecutor,
    google_oauth,
):
    """
    UMT Outreach full flow:
    1. Create temp sheet with lead CRM
    2. Book campus visit appointment (calendar)
    3. Append lead details to sheet
    4. Cleanup
    """
    # -- Create temp spreadsheet --
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    creds_json = await _get_google_creds()
    credentials = service_account.Credentials.from_service_account_info(
        json.loads(creds_json),
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    sheets_service = build("sheets", "v4", credentials=credentials)
    spreadsheet = sheets_service.spreadsheets().create(body={"properties": {"title": f"UMT Outreach Test {uuid.uuid4().hex[:8]}"}}).execute()
    spreadsheet_id = spreadsheet["spreadsheetId"]

    headers = ["Call Date", "Name", "Phone", "Program", "Marks", "City", "Scholarship", "Next Action", "Next Call"]
    sample = [["2026-06-01", "Hamza Sheikh", "+92-300-2223344", "BSCS", "930", "Lahore", "Yes (75%)", "Send brochure", "2026-06-05"]]
    sheets_service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range="Sheet1!A1",
        valueInputOption="USER_ENTERED",
        body={"values": [headers] + sample},
    ).execute()

    # -- Setup integrations --
    calendar_integ = await _create_integration(
        db_session, test_user, "google_calendar", google_api_key,
        config={"calendar_id": "primary", "timezone": "UTC"},
        name="UMT Outreach Calendar",
    )
    sheets_integ = await _create_integration(
        db_session, test_user, "google_sheets", google_api_key,
        config={"spreadsheet_id": spreadsheet_id, "sheet_name": "Sheet1"},
        name="UMT Outreach CRM",
    )

    # 1. Book campus visit
    visit_date = (datetime.now(timezone.utc) + timedelta(days=3)).strftime("%Y-%m-%d")
    booking = await _run_step(executor, calendar_integ.id, "book_appointment", {
        "date": visit_date,
        "time": "11:00",
        "duration_minutes": 60,
        "purpose": "UMT Campus Visit — Hamza Sheikh",
        "location": "UMT Main Campus, Lahore",
    })
    assert booking.get("success", False) or "event_id" in booking or "id" in booking, f"Booking failed: {booking}"
    event_id = booking.get("event_id") or booking.get("id")

    # 2. Append lead
    lead = [datetime.now().strftime("%Y-%m-%d"), "Zain Abbas", "+92-333-8889900", "BS SE", "910", "Rawalpindi", "Yes (75%)", "Campus visit booked", visit_date]
    append_result = await _run_step(executor, sheets_integ.id, "append_row", {
        "values": lead,
    })
    assert isinstance(append_result, dict), "Append should return dict"

    # 3. Cleanup
    if event_id:
        await _run_step(executor, calendar_integ.id, "delete_event", {"event_id": event_id})
    drive_service = build("drive", "v3", credentials=credentials)
    drive_service.files().delete(fileId=spreadsheet_id).execute()

    print(f"UMT Outreach flow completed. Event: {event_id}, Spreadsheet: {spreadsheet_id}")
