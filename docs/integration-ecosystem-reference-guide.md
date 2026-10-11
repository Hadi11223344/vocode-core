# Integration Ecosystem + Variable Extraction — Reference Guide

Practical guide to configuring and troubleshooting the platform's integration nodes: Google Calendar, Google Sheets, Google Drive MCP, Email (SMTP), SMS, Webhooks, Custom API, MCP tools, CRMs, support, e-commerce, productivity, and project-management integrations. Includes how variable extraction feeds them.

---

## 1. How Integrations Work

### 1.1 Storage model

Two database tables are involved:

- **`integrations`** — one row per connected service per user
  - `service_type` — e.g., `google_calendar`, `sms`, `webhook`
  - `name` — user-defined label
  - `api_key_id` → `user_api_keys.id`
  - `config_json` — service-specific config (spreadsheet_id, calendar_id, etc.)

- **`user_api_keys`** — encrypted credentials per user per service
  - `service` — e.g., `google_calendar`, `twilio`, `smtp`
  - `api_key` — primary secret (encrypted at rest)
  - `api_secret` — secondary secret (e.g., Twilio auth_token, webhook URL)

### 1.2 Runtime flow

When a graph node runs:

1. `WorkflowExecutor._execute_graph_node` identifies `service_type`
2. Loads the active `Integration` row and its `UserApiKey`
3. Decrypts credentials via `_load_api_key_and_secret`
4. Resolves `{{variable}}` templates in params
5. Calls the integration-specific handler
6. Stores `result` in context as `node_{id}_result` and `last_result`

### 1.3 Google OAuth vs service account

Google integrations support two auth methods:

| Method | Best for | Setup |
|--------|----------|-------|
| OAuth | End-user Google accounts | Settings → Integrations → Connect Google |
| Service account JSON | Workspace / shared calendars/sheets | Upload JSON key in `/api/keys` |

OAuth is preferred. Service accounts cannot access a user's `"primary"` calendar unless explicitly shared.

---

## 2. Google Calendar

### 2.1 Config fields

```json
{
  "calendar_id": "primary",
  "timezone": "Asia/Karachi"
}
```

- `calendar_id` — Google Calendar ID. `"primary"` only works with OAuth.
- `timezone` — IANA string. The agent's `timezone` field overrides this.

### 2.2 Actions

| Action | Required params | Optional params | Result keys |
|--------|-----------------|-----------------|-------------|
| `create_event` | `summary`/`title`, `start` or (`date` + `time`) | `end`, `duration_minutes`, `description`, `location`, `attendees` | `id`, `summary`, `start`, `end`, `html_link`, `status` |
| `list_events` | — | `max_results`, `time_min` | `events` list |
| `update_event` | `event_id` | `summary`, `start`, `end`, `description` | `id`, `summary`, `status` |
| `delete_event` | `event_id` | — | `event_id`, `status: deleted` |
| `check_availability` | `date` | `duration_minutes`, `business_hours_start`, `business_hours_end` | `date`, `busy_slots`, `available_slots`, `total_events` |
| `book_appointment` | `date`, `time` | `duration_minutes`, `purpose`/`summary`, `location`, `attendees` | same as `create_event` or error on conflict |

### 2.3 Date/time handling

The executor normalizes `time` to `HH:MM` and builds an ISO datetime from `date` + `time` in the agent timezone. If `date` already contains a `T` it uses it directly.

Example node params:

```json
{
  "summary": "Appointment for {{caller_name}}",
  "date": "{{preferred_date}}",
  "time": "{{preferred_time}}",
  "duration_minutes": 60
}
```

### 2.4 Common errors

| Error | Cause | Fix |
|-------|-------|-----|
| `Google Calendar not connected` | No OAuth token and no service account JSON | Connect Google account or add a service account key |
| `missing a valid datetime` | `date`/`time` templates unresolved | Add `variables_to_extract: ["preferred_date", "preferred_time"]` on the conversation node that asks for them |
| `Service account cannot access 'primary'` | Service account + `calendar_id=primary` | Use OAuth or share a specific calendar with the service account |
| `Time conflict` (book_appointment) | Slot overlaps with a busy event | Branch on `result.available_slots` and offer alternatives |

---

## 3. Google Sheets

### 3.1 Config fields

```json
{
  "spreadsheet_id": "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms",
  "sheet_name": "Sheet1"
}
```

- `spreadsheet_id` — required, from the sheet URL
- `sheet_name` — tab name. Falls back to the first tab if not found.

### 3.2 Actions

| Action | Required params | Optional params | Result keys |
|--------|-----------------|-----------------|-------------|
| `read_rows` | — | `range`, `max_rows` | `rows`, `count` |
| `append_row` | values | — | `updated_range`, `updated_rows`, `row_number`, `status` |
| `update_row` | `row_number`, values | — | `updated_range`, `updated_cells`, `status` |
| `search_rows` | `column`, `query` | `max_results` | `matches`, `count` |
| `get_headers` | — | — | `headers` |

### 3.3 Value formats

`append_row` accepts:

- A list: `"values": ["{{caller_name}}", "{{preferred_date}}"]`
- A comma-separated string: `"values": "John,2025-08-15"`
- Named params: it also scans `params` for keys `name`, `phone`, `email`, `notes`, `purpose`, `date`, `time`, `status`, `summary`, `description`, `location`, `attendee_email`

### 3.4 Common errors

| Error | Cause | Fix |
|-------|-------|-----|
| `spreadsheet_id is required` | Missing in integration config | Add it in Settings → Integrations |
| `Sheet 'X' not found` | Wrong tab name | Check tab name; executor auto-falls back to first tab |
| Append fails with 403 | Service account not shared the sheet | Share the spreadsheet with the service account email |

---

## 4. Google Drive MCP

### 4.1 Two Drive paths

There are two ways the platform interacts with Google Drive:

1. **`google_drive_mcp` integration** — legacy/existing integration type, can be configured like any other integration.
2. **`mcp_tool` node with a Google-hosted MCP server** — uses OAuth auto-resolution for `drivemcp.googleapis.com`.

### 4.2 Drive API client actions

`voice_platform/integrations/google_drive_client.py` supports:

- `read_file_content(file_id)`
- `list_files(query, page_size)`
- `search_files(query, page_size)`

Result shape:

```python
{
  "status": "ok",
  "content": "...",        # read_file_content
  "files": [...],          # list/search
  "count": 5,
}
```

### 4.3 OAuth auto-resolution

For `mcp_tool` nodes pointing at `drivemcp.googleapis.com`, the executor automatically calls `GoogleOAuthManager.get_credentials(user_id)` and injects the OAuth token. No static API key is needed if the user has connected Google.

---

## 5. Email (SMTP)

### 5.1 Credentials

Email can be sent via:

- Platform-wide SMTP settings in `.env` (`SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, etc.)
- An `email` integration with its own `api_key_id` and config

### 5.2 Config fields

```json
{
  "smtp_host": "smtp.gmail.com",
  "smtp_port": 587,
  "smtp_user": "you@gmail.com",
  "from_email": "you@gmail.com",
  "from_name": "VOIA Assistant",
  "use_tls": true
}
```

### 5.3 Action: `send_email`

| Param | Required | Notes |
|-------|----------|-------|
| `to` | yes | Recipient email |
| `subject` | yes | Subject line |
| `body` | yes | Plain text body |
| `html_body` | no | Optional HTML version |
| `cc` | no | Comma-separated CC list |
| `attachments` | no | List of `{filename, content, mime_type}` |

Result shape:

```python
{
  "success": True,
  "to": "...",
  "subject": "...",
  "cc": "...",
  "attachments_count": 0,
}
```

### 5.4 Common errors

| Error | Cause | Fix |
|-------|-------|-----|
| `SMTP connection failed` | Wrong host/port/credentials | Verify SMTP settings and use app-specific password for Gmail |
| `Recipient email address is required` | `to` missing or unresolved | Ensure `{{email}}` was extracted or provide literal address |

---

## 6. SMS (Twilio)

### 6.1 Credentials

SMS uses Twilio credentials. It can be configured:

- Platform-wide via `.env` (`TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_PHONE_NUMBER`)
- As an `sms` integration with `account_sid`, `auth_token`, `from_number` in config/secret

### 6.2 Config fields

```json
{
  "from_number": "+15551234567"
}
```

- `api_key` (or `api_secret`) holds `auth_token`
- `account_sid` goes in config or `api_key.metadata_json`

### 6.3 Action: `send_sms`

| Param | Required | Notes |
|-------|----------|-------|
| `to` | yes | E.164 phone number |
| `body` | yes | Message text (truncated to 1600 chars) |
| `from_number` | no | Overrides integration default |
| `media_url` | no | Public URL for MMS media |

Result shape:

```python
{
  "message_sid": "SM...",
  "status": "queued",
  "to": "...",
  "body_preview": "...",
  "success": True,
}
```

### 6.4 Common errors

| Error | Cause | Fix |
|-------|-------|-----|
| `Twilio credentials not configured` | Missing account_sid/auth_token | Add Twilio credentials in `.env` or integration |
| `No sender phone number configured` | Missing `from_number` | Set `from_number` in integration config |
| SMS fails after sending | Invalid `to` number or Twilio restrictions | Verify number format and Twilio geo permissions |

---

## 7. Webhook / Zapier / Make / Slack / Discord / Teams

### 7.1 Unified webhook handler

These services all route through `_execute_webhook_action` → `WebhookClient`.

### 7.2 Credentials

- `api_secret` holds the webhook URL (`webhook_url` is injected into config)
- `api_key` can be used as a Bearer token in the `Authorization` header

### 7.3 Config fields

```json
{
  "base_url": "https://hooks.zapier.com",
  "default_headers": {"Content-Type": "application/json"}
}
```

### 7.4 Actions and params

| Action | Params | Notes |
|--------|--------|-------|
| `send_message` / `send` / `post` | `payload`/`body`, `headers` | POST JSON payload |
| `trigger` | `payload` | Alias for POST |

The executor builds:

```python
url = params.get("url") or config.get("url") or config.get("webhook_url") or config.get("base_url")
method = params.get("method", "POST")
body = params.get("body", params.get("payload", {}))
```

### 7.5 Result shape

```python
{
  "success": response.is_success,
  "status_code": 200,
  "body": {...} or "raw text",
}
```

### 7.6 SSRF protection

`WebhookClient._is_safe_url()` blocks:

- `localhost`, `127.0.0.1`, `0.0.0.0`, `::1`
- `169.254.169.254`, `metadata.google.internal`
- Private IP literals (`10.*`, `192.168.*`, `172.16-31.*`)

---

## 8. Custom API Node

### 8.1 Config fields

```json
{
  "url": "https://api.example.com/v1/customers",
  "method": "POST",
  "headers": {"X-Api-Key": "{{api_key}}"},
  "body": {"name": "{{caller_name}}", "email": "{{email}}"},
  "api_key_id": 42,
  "response_mappings": {
    "customer_id": "$.data.id",
    "customer_status": "$.data.status"
  }
}
```

### 8.2 Auth

If `api_key_id` is set, the executor loads the API key and sends:

```
Authorization: Bearer {api_key}
```

This can be overridden by an explicit `auth_header` in config/params.

### 8.3 Response mappings

Uses JSONPath-like notation (only `$.<dot>.<path>` supported). Extracted values are merged into context:

```python
{"customer_id": "123", "customer_status": "active"} → context.update(...)
```

Result includes `result["extracted"]`.

### 8.4 Common errors

| Error | Cause | Fix |
|-------|-------|-----|
| `URL blocked by security policy` | URL points to internal/private host | Use a public URL |
| `Request timed out` | Slow downstream API | Increase timeout or retry; default is 30s with 3 retries |
| Extracted values are None | JSONPath doesn't match response body | Test response shape and adjust mappings |

---

## 9. MCP Tool Node

### 9.1 Config fields

```json
{
  "server_url": "https://mcp.example.com",
  "auth_token": "sk-...",
  "tool_name": "lookup_customer",
  "parameters": {"email": "{{email}}"}
}
```

### 9.2 Google MCP auto-auth

If `server_url` host is one of:

- `drivemcp.googleapis.com`
- `calendarmcp.googleapis.com`
- `gmailmcp.googleapis.com`
- `peoplemcp.googleapis.com`

and no `auth_token` is provided, the executor resolves the user's Google OAuth token automatically.

### 9.3 Result handling

The result is stored as `node_{id}_result` and `last_result`. It is also capped to `MAX_RESPONSE_CHARS = 4000` by `McpClient` to protect the LLM context window.

### 9.4 Security

- `auth_token` is never logged
- URLs are validated by `_is_safe_url()` (SSRF protection)
- Response is truncated to 4000 characters

---

## 10. CRM, Support, E-commerce, Productivity, Project Management

### 10.1 CRM actions

| Service | Actions |
|---------|---------|
| **HubSpot** | `create_contact`, `update_contact`, `get_contact`, `search_contacts`, `create_deal`, `update_deal`, `search_deals`, `create_note`, `add_note`, `associate` |
| **Salesforce** | `create_lead`, `update_lead`, `create_contact`, `update_contact`, `create_opportunity`, `update_opportunity`, `get_record`, `search_records`, `query` |
| **Pipedrive** | `create_person`, `update_person`, `search_persons`, `create_deal`, `update_deal`, `search_deals`, `add_note`, `create_activity` |
| **GoHighLevel** | `create_contact`, `update_contact`, `create_opportunity`, `add_tag`, `send_sms`, `create_task` |

All CRM handlers load a dedicated client with `api_key` and `config`.

### 10.2 Support actions

| Service | Actions |
|---------|---------|
| **Zendesk** | `create_ticket`, `update_ticket`, `search_tickets`, `add_comment` |
| **Freshdesk** | `create_ticket`, `update_ticket`, `search_tickets`, `add_note` |
| **Intercom** | `create_conversation`, `send_message`, `search_contacts` |

### 10.3 E-commerce actions

| Service | Actions |
|---------|---------|
| **Stripe** | `create_payment_intent`, `create_customer`, `create_invoice`, `list_invoices` |
| **Shopify** | `create_order`, `get_order`, `search_products`, `get_customer` |

### 10.4 Productivity actions

| Service | Actions |
|---------|---------|
| **Notion** | `create_page`, `update_page`, `search_pages` |
| **Airtable** | `create_record`, `update_record`, `search_records` |

### 10.5 Project management actions

| Service | Actions |
|---------|---------|
| **Jira** | `create_issue`, `update_issue`, `search_issues`, `add_comment` |
| **Linear** | `create_issue`, `update_issue`, `search_issues` |

For all of these, the relevant `service_type` node maps to a handler in `WorkflowExecutor._execute_action`. Detailed request/response shapes are in the individual client files under `voice_platform/integrations/`.

---

## 11. Variable Extraction

### 11.1 Mechanisms

There are three ways variables get into context:

1. **Pre-populated** — `caller_name`, `caller_phone`, `transcript`, `user_id`
2. **Conversation-node explicit extraction** — `variables_to_extract` in a conversation node's config
3. **Just-in-time extraction** — before an action node runs, the executor scans its params for `{{var}}` and extracts missing ones from the transcript
4. **Look-ahead extraction** — when a conversation node pauses, queued downstream nodes are scanned for `{{var}}` patterns so those variables are captured from the next user message

### 11.2 Template syntax

Variables are referenced with double curly braces:

```json
{
  "summary": "Appointment for {{caller_name}}",
  "date": "{{preferred_date}}",
  "time": "{{preferred_time}}"
}
```

### 11.3 `_llm_extract`

The LLM is given:

```
You are a precise extraction assistant.
Extract ONLY the requested value from the text.
Return ONLY the value — no explanation, no quotes, no markdown.
If the value is not present, respond with exactly: NOT_FOUND
```

If the response is `NOT_FOUND` or empty, the variable is left unset in context.

### 11.4 Fallback regex

If the LLM is unavailable and the variable name contains `"email"`, a regex fallback extracts the first email address from the transcript.

### 11.5 Best practices

- Set `variables_to_extract` on the conversation node that asks for the value
- Use variable names consistently across nodes
- For complex extractions (e.g., date ranges), use an `extract_variable` node with a custom prompt
- Check that downstream action params reference the exact variable name

---

## 12. Common Integration Errors & Fixes

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `No active integration configured for service 'google_calendar'` | Integration not connected or inactive | Connect it in Settings → Integrations |
| `Google Calendar not connected` | No OAuth token and no service account JSON | Connect Google or upload service account key |
| `missing a valid datetime` | `date`/`time` template unresolved | Add `variables_to_extract` and ensure user provides the value |
| `Service account cannot access 'primary'` | Service account trying to access primary calendar | Use OAuth or share a specific calendar |
| `spreadsheet_id is required` | Missing Sheets config | Add spreadsheet ID in integration config |
| `SMTP connection failed` | Bad SMTP credentials | Use app-specific password; verify host/port |
| `No sender phone number configured` | Missing Twilio `from_number` | Set it in the SMS integration config |
| `URL blocked by security policy` | Webhook points to private IP | Use public URL |
| `Request timed out` | Slow API / network | Check downstream health; default 30s timeout |
| MCP returns truncated data | Response > 4000 chars | This is by design; use a tool with a narrower query |
| OAuth token expired | Refresh token invalid or revoked | Re-connect Google account |

---

## 13. Best Practices

### 13.1 Google integrations

- Use OAuth for end-user accounts
- Never use `calendar_id=primary` with service accounts
- Share the specific calendar/sheet with the service account email
- Set the agent `timezone` field for correct local time

### 13.2 Webhooks and custom APIs

- Store webhook URLs as `api_secret`, not in config JSON
- Use `response_mappings` to extract exactly the fields you need
- Avoid sending secrets in query params

### 13.3 Email and SMS

- Use platform SMTP/Twilio settings only when you want global defaults
- Use per-user integrations when different users need different credentials
- Always include a fallback if `to` is missing

### 13.4 Variable extraction

- Ask for one thing at a time
- Match `variables_to_extract` names to action params
- Use `extract_variable` nodes for mid-flow extraction from the transcript
- Test unresolved-variable cases by omitting the value in playground

---

## 14. Code Reference

### 14.1 Key files

| File | Responsibility |
|------|----------------|
| `voice_platform/integrations/executor.py` | `_execute_action`, all per-service handlers, template resolution |
| `voice_platform/integrations/google_calendar.py` | Google Calendar client |
| `voice_platform/integrations/google_sheets.py` | Google Sheets client |
| `voice_platform/integrations/google_drive_client.py` | Google Drive API client |
| `voice_platform/integrations/google_oauth.py` | OAuth flow and token refresh |
| `voice_platform/integrations/email_client.py` | SMTP email client |
| `voice_platform/integrations/sms_client.py` | Twilio SMS client |
| `voice_platform/integrations/webhook_client.py` | Generic HTTP client + JSONPath extraction |
| `voice_platform/integrations/mcp_client.py` | MCP JSON-RPC client |
| `voice_platform/api/playground_routes.py` | `_extract_conversation_variables`, JIT, lookahead extraction |

### 14.2 Important method signatures

```python
# executor.py
async def _execute_action(self, service_type, action, params, api_key, config)
async def _execute_calendar_action(self, action, params, api_key, config)
async def _execute_sheets_action(self, action, params, api_key, config)
async def _execute_webhook_action(self, action, params, api_key, config)
async def _execute_mcp_tool_node(self, node_id, params, config, context)
async def _execute_custom_api_node(self, node_id, params, config, context)
def _resolve_templates(self, params, context)
async def _llm_extract(self, transcript, prompt, variable_name)

# google_oauth.py
class GoogleOAuthManager:
    async def get_authorization_url(user_id, redirect_uri, scopes=None)
    async def exchange_code(code, state)
    async def get_credentials(user_id)
    async def revoke(user_id)

# playground_routes.py (FlowPlaygroundConversation)
async def _extract_conversation_variables(self, event_callback=None)
```

---

## 15. Quick Checklist for Adding a New Integration

- [ ] Add `service_type` to `VALID_INTEGRATION_TYPES` in `database.py`
- [ ] Add to `known_service_types` in `WorkflowExecutor._execute_graph_node`
- [ ] Add a route in `_execute_action`
- [ ] Implement or import the client in `voice_platform/integrations/`
- [ ] Handle auth (API key, OAuth, webhook secret, etc.)
- [ ] Return structured `{success, error, ...}` dict
- [ ] Add frontend node type/config in `frontend/src/components/workflow/WorkflowNodes.tsx` if needed
- [ ] Update `user_api_keys.VALID_KEY_SERVICES` if the integration stores a key
- [ ] Write tests in `tests/voice_platform/test_workflow_executor.py`
