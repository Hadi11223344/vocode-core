"""
Integration Setup Guides
=========================

Comprehensive setup instructions, API key guidance, official doc links,
field-level help, and example configs for every supported integration.

Each guide is keyed by integration type ID and merged into the
``/api/integrations/types`` response so the frontend can render
rich, user-friendly setup experiences.
"""

INTEGRATION_GUIDES: dict[str, dict] = {
    # ── Google Calendar ──────────────────────────────────────────
    "google_calendar": {
        "setup_guide": {
            "title": "Connect Google Calendar",
            "estimated_time": "5 minutes",
            "difficulty": "Easy",
            "docs_url": "https://developers.google.com/calendar/api/quickstart/python",
            "steps": [
                {
                    "step": 1,
                    "title": "Connect your Google account",
                    "description": "Click Connect with Google in VOIA and approve the Calendar access request.",
                },
                {
                    "step": 2,
                    "title": "Set the calendar to use",
                    "description": "Choose the calendar ID in the config below. 'primary' works for your main calendar when using OAuth.",
                },
                {
                    "step": 3,
                    "title": "Optional: use a service account",
                    "description": "If you prefer server-to-server auth, paste the full Google service account JSON key below instead of using OAuth.",
                },
                {
                    "step": 4,
                    "title": "Save the integration",
                    "description": "Fill in the remaining config fields and click Create Integration so workflows can reference this calendar connection.",
                },
            ],
            "notes": [
                "OAuth tokens are stored securely in the backend and do not appear as a visible key in the dashboard.",
                "The Calendar ID for your primary calendar is usually 'primary' or your email address.",
                "Service account JSON is optional and only needed if you want to bypass OAuth.",
            ],
        },
        "field_overrides": {
            "calendar_id": {
                "label": "Calendar ID",
                "placeholder": "primary",
                "help_text": "Use 'primary' for your main calendar when using OAuth, or the ID of a shared calendar if you use the service-account fallback.",
            },
            "timezone": {
                "label": "Default Timezone",
                "placeholder": "America/New_York",
                "help_text": "IANA timezone identifier. All events will use this timezone unless overridden. Examples: America/Los_Angeles, Europe/London, Asia/Tokyo.",
            },
        },
        "api_key_help": "OAuth is recommended. If you prefer service-account fallback, paste the full JSON contents of your Google Service Account key file here.",
        "agent_usage": {
            "tools": ["check_calendar", "create_event", "book_appointment"],
            "trigger_phrases": [
                "when are you available",
                "book an appointment",
                "schedule a meeting",
                "what times do you have",
                "check my calendar",
            ],
            "example_scenario": (
                "Caller: Can we schedule a demo for next Tuesday at 2 PM?\n"
                "Agent: Let me check my calendar for Tuesday.\n"
                "[Agent calls check_calendar tool]\n"
                "Agent: Tuesday at 2 PM is available. What should I title the meeting?\n"
                "Caller: Product demo call\n"
                "[Agent calls create_event tool with title='Product demo call', start='2026-06-16T14:00:00']\n"
                "Agent: Done! I've booked the demo for Tuesday, June 16th at 2 PM."
            ),
            "parameters": [
                {"name": "date", "description": "Date to check (YYYY-MM-DD)", "required": False, "example": "2026-06-16"},
                {"name": "summary", "description": "Event title", "required": True, "example": "Product demo call"},
                {"name": "start", "description": "Start datetime (ISO 8601)", "required": True, "example": "2026-06-16T14:00:00"},
                {"name": "end", "description": "End datetime (ISO 8601)", "required": False, "example": "2026-06-16T15:00:00"},
            ],
        },
    },

    # ── Google Sheets ────────────────────────────────────────────
    "google_sheets": {
        "setup_guide": {
            "title": "Connect Google Sheets",
            "estimated_time": "5 minutes",
            "difficulty": "Easy",
            "docs_url": "https://developers.google.com/sheets/api/quickstart/python",
            "steps": [
                {
                    "step": 1,
                    "title": "Connect your Google account",
                    "description": "Click Connect with Google in VOIA and approve the Sheets access request.",
                },
                {
                    "step": 2,
                    "title": "Copy the Spreadsheet ID",
                    "description": "Paste the spreadsheet ID in the config below. It is the long string between /d/ and /edit in the URL.",
                },
                {
                    "step": 3,
                    "title": "Optional: use a service account",
                    "description": "If you prefer server-to-server auth, paste the full Google service account JSON key below instead of using OAuth.",
                },
                {
                    "step": 4,
                    "title": "Save the integration",
                    "description": "Fill in the remaining config fields and click Create Integration so workflows can reference this sheet connection.",
                },
            ],
            "notes": [
                "OAuth tokens are stored securely in the backend and do not appear as a visible key in the dashboard.",
                "The spreadsheet ID is the long string between /d/ and /edit in the Sheet URL.",
                "Service account JSON is optional and only needed if you want to bypass OAuth.",
            ],
        },
        "field_overrides": {
            "spreadsheet_id": {
                "label": "Spreadsheet ID",
                "placeholder": "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms",
                "help_text": "Copy from the Google Sheets URL: docs.google.com/spreadsheets/d/{THIS_PART}/edit",
            },
            "sheet_name": {
                "label": "Worksheet Name",
                "placeholder": "Sheet1",
                "help_text": "The name of the specific tab/worksheet. Check the tabs at the bottom of your Google Sheet.",
            },
        },
        "api_key_help": "OAuth is recommended. If you prefer service-account fallback, paste the full JSON contents of your Google Service Account key file here.",
        "agent_usage": {
            "tools": ["read_sheet", "append_sheet"],
            "trigger_phrases": [
                "what's in the spreadsheet",
                "log this to the sheet",
                "check the inventory",
                "read the menu",
                "add this to the list",
            ],
            "example_scenario": (
                "Caller: What's on the menu today?\n"
                "Agent: Let me check the spreadsheet for you.\n"
                "[Agent calls read_sheet tool]\n"
                "Agent: Today's specials are chicken biryani for PKR 350 and beef karahi for PKR 450.\n"
                "Caller: Great, I'll have the chicken biryani. Can you log my order?\n"
                "Agent: Sure! What's your name and phone number?\n"
                "Caller: Ali, +923001234567\n"
                "[Agent calls append_sheet with values ['Ali', '+923001234567', 'Chicken Biryani', 'PKR 350']]\n"
                "Agent: Done! Your order has been logged."
            ),
            "parameters": [
                {"name": "range", "description": "A1 notation range, e.g. 'A1:D10'", "required": False, "example": "A1:D10"},
                {"name": "values", "description": "List of cell values for the new row", "required": True, "example": "['Ali', 'Chicken Biryani', 'PKR 350']"},
            ],
        },
    },

    # ── SMS (Twilio) ─────────────────────────────────────────────
    "sms": {
        "setup_guide": {
            "title": "Connect Twilio SMS",
            "estimated_time": "3 minutes",
            "difficulty": "Easy",
            "docs_url": "https://www.twilio.com/docs/sms/quickstart",
            "steps": [
                {
                    "step": 1,
                    "title": "Create a Twilio Account",
                    "description": "Sign up at twilio.com. You'll get a free trial with credits to test.",
                    "link": "https://www.twilio.com/try-twilio",
                },
                {
                    "step": 2,
                    "title": "Get Your Account SID & Auth Token",
                    "description": "From your Twilio Console dashboard, find your Account SID and Auth Token. These are displayed prominently on the main page.",
                    "link": "https://console.twilio.com/",
                },
                {
                    "step": 3,
                    "title": "Get or Buy a Phone Number",
                    "description": "Go to Phone Numbers → Manage → Buy a Number. Choose one with SMS capabilities. Note the number in E.164 format (e.g., +1234567890).",
                    "link": "https://console.twilio.com/us1/develop/phone-numbers/manage/incoming",
                },
                {
                    "step": 4,
                    "title": "Configure in VOIA",
                    "description": "Enter your Account SID and Auth Token in the config, and set your 'from' phone number.",
                },
            ],
            "notes": [
                "Trial accounts can only send to verified phone numbers.",
                "Phone numbers must be in E.164 format: +[country code][number] (e.g., +14155551234).",
                "Upgrade your account to send SMS to any number.",
            ],
        },
        "field_overrides": {
            "account_sid": {
                "label": "Account SID",
                "placeholder": "ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
                "help_text": "Found on your Twilio Console dashboard. Starts with 'AC'.",
            },
            "auth_token": {
                "label": "Auth Token",
                "placeholder": "your_auth_token_here",
                "help_text": "Found on your Twilio Console dashboard. Click the eye icon to reveal it. Keep this secret!",
            },
            "from_number": {
                "label": "From Phone Number",
                "placeholder": "+14155551234",
                "help_text": "Your Twilio phone number in E.164 format. Must be SMS-capable.",
            },
        },
        "api_key_help": "Not required — enter your Account SID and Auth Token in the config fields below instead.",
        "agent_usage": {
            "tools": ["send_sms"],
            "trigger_phrases": [
                "send me a text",
                "text me the details",
                "send an SMS",
                "message me",
            ],
            "example_scenario": (
                "Caller: Can you text me the confirmation?\n"
                "Agent: Sure! What's your phone number?\n"
                "Caller: +14155551234\n"
                "Agent: What should the message say?\n"
                "Caller: Just Appointment confirmed for Thursday 2 PM\n"
                "[Agent calls send_sms tool with to='+14155551234', body='Appointment confirmed for Thursday 2 PM']\n"
                "Agent: Done! I've sent the confirmation text."
            ),
            "parameters": [
                {"name": "to", "description": "Recipient phone number (E.164 format)", "required": True, "example": "+14155551234"},
                {"name": "body", "description": "Message text (max 1600 chars)", "required": True, "example": "Appointment confirmed for Thursday 2 PM"},
            ],
        },
    },

    # ── Email (SMTP) ─────────────────────────────────────────────
    "email": {
        "setup_guide": {
            "title": "Connect Email (SMTP)",
            "estimated_time": "3 minutes",
            "difficulty": "Easy",
            "docs_url": "https://support.google.com/a/answer/176600",
            "steps": [
                {
                    "step": 1,
                    "title": "Choose an Email Provider",
                    "description": "You can use Gmail, Outlook, or any SMTP provider. We recommend Gmail with App Passwords or a dedicated transactional service like SendGrid/Mailgun.",
                },
                {
                    "step": 2,
                    "title": "Get SMTP Credentials",
                    "description": "For Gmail: Enable 2FA on your Google account, then create an App Password at myaccount.google.com → Security → App Passwords. For Outlook: use your regular password with smtp.office365.com:587.",
                    "link": "https://myaccount.google.com/apppasswords",
                },
                {
                    "step": 3,
                    "title": "Configure SMTP Settings",
                    "description": "Enter your SMTP host, port, username, and the app password. For Gmail: host=smtp.gmail.com, port=587. For Outlook: host=smtp.office365.com, port=587.",
                },
            ],
            "notes": [
                "Gmail SMTP: host=smtp.gmail.com, port=587, TLS=true.",
                "Outlook SMTP: host=smtp.office365.com, port=587, TLS=true.",
                "For high-volume email, use SendGrid or Mailgun instead of personal email.",
                "Gmail requires an App Password (not your regular password) when 2FA is enabled.",
            ],
        },
        "field_overrides": {
            "smtp_host": {
                "label": "SMTP Host",
                "placeholder": "smtp.gmail.com",
                "help_text": "Gmail: smtp.gmail.com | Outlook: smtp.office365.com | Yahoo: smtp.mail.yahoo.com",
            },
            "smtp_port": {
                "label": "SMTP Port",
                "placeholder": "587",
                "help_text": "Use 587 for TLS (recommended) or 465 for SSL. Most providers use 587.",
            },
            "smtp_user": {
                "label": "SMTP Username",
                "placeholder": "you@gmail.com",
                "help_text": "Usually your full email address.",
            },
            "from_email": {
                "label": "Sender Email",
                "placeholder": "noreply@yourcompany.com",
                "help_text": "The 'From' address recipients will see. Must match or be authorized by your SMTP provider.",
            },
            "from_name": {
                "label": "Sender Name",
                "placeholder": "VOIA",
                "help_text": "Display name shown to recipients (e.g., 'Your Company Name').",
            },
            "use_tls": {
                "label": "Use TLS Encryption",
                "help_text": "Enable TLS for secure email delivery. Should be enabled for port 587.",
            },
        },
        "api_key_help": "Enter your SMTP password (or App Password for Gmail) as the API key.",
        "agent_usage": {
            "tools": ["send_email"],
            "trigger_phrases": [
                "send me an email",
                "email me the details",
                "can you email that",
                "send a confirmation email",
                "email me the summary",
            ],
            "example_scenario": (
                "Caller: Can you email me the appointment details?\n"
                "Agent: Sure! What's your email address?\n"
                "Caller: john@example.com\n"
                "Agent: What subject should I use?\n"
                "Caller: Appointment Confirmation\n"
                "[Agent calls send_email tool with to='john@example.com', subject='Appointment Confirmation', body='Your appointment is confirmed for Thursday at 2 PM.']\n"
                "Agent: Done! I've sent the confirmation to john@example.com."
            ),
            "parameters": [
                {"name": "to", "description": "Recipient email address", "required": True, "example": "john@example.com"},
                {"name": "subject", "description": "Email subject line", "required": True, "example": "Appointment Confirmation"},
                {"name": "body", "description": "Plain text email body", "required": True, "example": "Your appointment is confirmed for Thursday at 2 PM."},
            ],
        },
    },

    # ── Webhook / REST API ───────────────────────────────────────
    "webhook": {
        "setup_guide": {
            "title": "Connect Webhook / REST API",
            "estimated_time": "2 minutes",
            "difficulty": "Medium",
            "docs_url": "https://developer.mozilla.org/en-US/docs/Web/HTTP/Overview",
            "steps": [
                {
                    "step": 1,
                    "title": "Get Your API Endpoint",
                    "description": "Determine the base URL of the API you want to call. This could be any REST API (your own backend, a third-party service, etc.).",
                },
                {
                    "step": 2,
                    "title": "Get Authentication Details",
                    "description": "Most APIs require authentication. Common methods: API key in header, Bearer token, or Basic auth. Check the API documentation.",
                },
                {
                    "step": 3,
                    "title": "Configure in VOIA",
                    "description": "Set the base URL and any default headers (like Authorization). In workflows, you'll specify the exact path and request body.",
                },
            ],
            "notes": [
                "This is a generic integration for any REST API not specifically listed.",
                "Set authentication headers in 'default_headers' (e.g., {\"Authorization\": \"Bearer your_token\"}).",
                "The timeout controls how long to wait for a response before giving up.",
                "Retry count specifies automatic retries on network failures.",
            ],
        },
        "field_overrides": {
            "base_url": {
                "label": "Base URL",
                "placeholder": "https://api.example.com/v1",
                "help_text": "The root URL of the API. Workflow steps will append paths to this.",
            },
            "default_headers": {
                "label": "Default Headers (JSON)",
                "placeholder": '{"Authorization": "Bearer your_token"}',
                "help_text": "Headers sent with every request. Use for API keys or auth tokens. Must be valid JSON.",
            },
            "timeout": {
                "label": "Timeout (seconds)",
                "placeholder": "30",
                "help_text": "How long to wait for a response. Increase for slow APIs. Default: 30s.",
            },
            "retry_count": {
                "label": "Retry Count",
                "placeholder": "1",
                "help_text": "Number of automatic retries on network failure. Set to 0 to disable retries.",
            },
        },
        "api_key_help": "If the API uses an API key for auth, paste it here. It will be stored securely. Otherwise, put auth info in default_headers.",
        "agent_usage": {
            "tools": ["webhook"],
            "trigger_phrases": [
                "trigger my webhook",
                "call the API",
                "send data to my backend",
            ],
            "example_scenario": (
                "Caller: Please log this lead to my CRM\n"
                "Agent: I'll send the lead details to your webhook now.\n"
                "[Agent calls webhook tool with data={name: 'John Doe', phone: '+1234567890', interest: 'Enterprise plan'}]\n"
                "Agent: Done! The lead has been forwarded to your system."
            ),
            "parameters": [
                {"name": "data", "description": "JSON data to send to the webhook", "required": True, "example": '{"name": "John Doe", "phone": "+1234567890"}'},
            ],
        },
    },

    # ── Knowledge Base ───────────────────────────────────────────
    "knowledge_base": {
        "setup_guide": {
            "title": "Setup Knowledge Base (RAG)",
            "estimated_time": "2 minutes",
            "difficulty": "Easy",
            "docs_url": "https://docs.voia.ai/knowledge-base",
            "steps": [
                {
                    "step": 1,
                    "title": "Prepare Your Content",
                    "description": "Gather the documents, FAQs, or URLs you want the AI to reference during calls. Supported: plain text, PDFs, web URLs.",
                },
                {
                    "step": 2,
                    "title": "Create the Integration",
                    "description": "Give it a descriptive name (e.g., 'Product FAQ' or 'Company Handbook'). Configure chunk size and similarity thresholds.",
                },
                {
                    "step": 3,
                    "title": "Add Content Via Workflow",
                    "description": "Use the Knowledge Base node in your workflow to upload and query content. The AI will retrieve relevant chunks during calls to provide accurate answers.",
                },
            ],
            "notes": [
                "Smaller chunk sizes (200-300) work better for FAQ-style content.",
                "Larger chunk sizes (500-1000) work better for long-form documents.",
                "Lower similarity thresholds return more results but may be less relevant.",
                "No external API key needed — this uses VOIA's built-in TF-IDF search engine.",
            ],
        },
        "field_overrides": {
            "chunk_size": {
                "label": "Chunk Size (characters)",
                "placeholder": "500",
                "help_text": "How many characters per text chunk. Smaller = more precise retrieval, larger = more context per result.",
            },
            "max_chunks_per_query": {
                "label": "Max Results Per Query",
                "placeholder": "3",
                "help_text": "Maximum number of relevant chunks returned per question. More = broader context but slower.",
            },
            "min_similarity": {
                "label": "Minimum Similarity Score",
                "placeholder": "0.05",
                "help_text": "Threshold (0-1) for how similar a chunk must be to the query. Lower = more results, higher = stricter matching.",
            },
        },
        "api_key_help": "No API key required. Knowledge Base uses VOIA's built-in search engine.",
    },

    # ── Slack ────────────────────────────────────────────────────
    "slack": {
        "setup_guide": {
            "title": "Connect Slack",
            "estimated_time": "3 minutes",
            "difficulty": "Easy",
            "docs_url": "https://api.slack.com/messaging/webhooks",
            "steps": [
                {
                    "step": 1,
                    "title": "Create a Slack App",
                    "description": "Go to api.slack.com/apps → Create New App → choose 'From scratch'. Select your workspace.",
                    "link": "https://api.slack.com/apps?new_app=1",
                },
                {
                    "step": 2,
                    "title": "Enable Incoming Webhooks",
                    "description": "In your app settings → Features → Incoming Webhooks → toggle it ON.",
                },
                {
                    "step": 3,
                    "title": "Create a Webhook URL",
                    "description": "Click 'Add New Webhook to Workspace' → select the channel → copy the Webhook URL.",
                },
                {
                    "step": 4,
                    "title": "Paste in VOIA",
                    "description": "Paste the webhook URL into the config. Optionally set a default channel name.",
                },
            ],
            "notes": [
                "Each webhook URL is tied to a specific channel.",
                "To post to multiple channels, create multiple integrations.",
                "Webhook URLs start with https://hooks.slack.com/services/",
                "Messages support Slack's mrkdwn formatting.",
            ],
        },
        "field_overrides": {
            "webhook_url": {
                "label": "Webhook URL",
                "placeholder": "https://hooks.slack.com/services/T00000/B00000/XXXX",
                "help_text": "Your Slack Incoming Webhook URL. Found in Slack App → Incoming Webhooks. Keep this secret!",
            },
            "default_channel": {
                "label": "Default Channel",
                "placeholder": "general",
                "help_text": "Channel name without the # symbol. The webhook is already tied to a channel, but this helps label it.",
            },
        },
        "api_key_help": "No separate API key needed. The Webhook URL contains the authentication.",
        "agent_usage": {
            "tools": ["webhook"],
            "trigger_phrases": [
                "post to slack",
                "send a slack message",
                "notify my team",
                "alert the channel",
            ],
            "example_scenario": (
                "Caller: Can you notify the team about this order?\n"
                "Agent: I'll post a message to the Slack channel right away.\n"
                "[Agent calls webhook tool with data={text: 'New order received: 2x Chicken Biryani, PKR 700'}]\n"
                "Agent: Done! The team has been notified in Slack."
            ),
            "parameters": [
                {"name": "data", "description": "JSON data sent to the Slack webhook", "required": True, "example": '{"text": "New order received"}'},
            ],
        },
    },

    # ── Zapier ───────────────────────────────────────────────────
    "zapier": {
        "setup_guide": {
            "title": "Connect Zapier",
            "estimated_time": "5 minutes",
            "difficulty": "Easy",
            "docs_url": "https://zapier.com/help/create/code-webhooks/trigger-zaps-from-webhooks",
            "steps": [
                {
                    "step": 1,
                    "title": "Create a New Zap",
                    "description": "Log into Zapier → click 'Create Zap'. For the trigger, choose 'Webhooks by Zapier' → 'Catch Hook'.",
                    "link": "https://zapier.com/app/editor",
                },
                {
                    "step": 2,
                    "title": "Copy the Webhook URL",
                    "description": "Zapier will generate a unique webhook URL. Copy it — this is what VOIA will send data to.",
                },
                {
                    "step": 3,
                    "title": "Set Up Your Action",
                    "description": "Choose what Zapier should do when triggered (e.g., create a Google Sheet row, send an email, update a CRM). Follow Zapier's prompts.",
                },
                {
                    "step": 4,
                    "title": "Paste URL in VOIA",
                    "description": "Paste the Zapier Webhook URL into the config. When workflows execute, data will be sent to Zapier automatically.",
                },
                {
                    "step": 5,
                    "title": "Test the Connection",
                    "description": "In Zapier, click 'Test trigger' to verify. Then activate ('Turn on') your Zap.",
                },
            ],
            "notes": [
                "Free Zapier accounts allow 100 tasks/month.",
                "VOIA sends call data as JSON. Map fields in Zapier's action step.",
                "Zapier webhook URLs start with https://hooks.zapier.com/",
                "You can chain multiple Zapier actions in a single Zap.",
            ],
        },
        "field_overrides": {
            "webhook_url": {
                "label": "Zapier Webhook URL",
                "placeholder": "https://hooks.zapier.com/hooks/catch/123456/abcdef/",
                "help_text": "The 'Catch Hook' URL from your Zapier trigger. Found when creating a Zap with 'Webhooks by Zapier'.",
            },
        },
        "api_key_help": "No API key required. The webhook URL includes authentication.",
        "agent_usage": {
            "tools": ["webhook"],
            "trigger_phrases": [
                "trigger my zap",
                "run my automation",
                "send to zapier",
            ],
            "example_scenario": (
                "Caller: Please add me to your mailing list\n"
                "Agent: I'll trigger your Zapier automation now.\n"
                "[Agent calls webhook tool with data={email: 'john@example.com', name: 'John Doe', source: 'phone_call'}]\n"
                "Agent: Done! Zapier will add you to the mailing list."
            ),
            "parameters": [
                {"name": "data", "description": "JSON data sent to the Zapier webhook", "required": True, "example": '{"email": "john@example.com", "name": "John Doe"}'},
            ],
        },
    },

    # ── HubSpot CRM ──────────────────────────────────────────────
    "hubspot": {
        "setup_guide": {
            "title": "Connect HubSpot CRM",
            "estimated_time": "5 minutes",
            "difficulty": "Easy",
            "docs_url": "https://developers.hubspot.com/docs/api/overview",
            "steps": [
                {
                    "step": 1,
                    "title": "Log Into HubSpot",
                    "description": "Go to your HubSpot account. You need at least a free CRM account.",
                    "link": "https://app.hubspot.com/",
                },
                {
                    "step": 2,
                    "title": "Create a Private App",
                    "description": "Go to Settings → Integrations → Private Apps → Create a private app. Name it 'VOIA Integration'.",
                    "link": "https://app.hubspot.com/private-apps/",
                },
                {
                    "step": 3,
                    "title": "Set Permissions (Scopes)",
                    "description": "Under Scopes → CRM, enable: crm.objects.contacts.read, crm.objects.contacts.write, crm.objects.deals.read, crm.objects.deals.write. Click 'Create app'.",
                },
                {
                    "step": 4,
                    "title": "Copy the Access Token",
                    "description": "After creation, copy the access token shown. This is your API key for VOIA.",
                },
            ],
            "notes": [
                "HubSpot Private Apps use Bearer token authentication.",
                "Free CRM has API rate limits (100 requests per 10 seconds).",
                "The access token should be kept secret — it grants full access to the scopes you selected.",
                "You can always regenerate the token from the Private App settings.",
            ],
        },
        "field_overrides": {
            "base_url": {
                "label": "API Base URL",
                "placeholder": "https://api.hubapi.com",
                "help_text": "HubSpot API base URL. Use the default unless you have a custom setup.",
            },
        },
        "api_key_help": "Paste your HubSpot Private App access token. Found in Settings → Integrations → Private Apps → your app → Access Token.",
        "agent_usage": {
            "tools": ["webhook"],
            "trigger_phrases": [
                "log this to hubspot",
                "create a contact in crm",
                "add to my crm",
            ],
            "example_scenario": (
                "Caller: I'd like to book a consultation\n"
                "Agent: Great! Let me capture your details and log them to HubSpot.\n"
                "[Agent calls webhook tool with data={firstname: 'John', lastname: 'Doe', email: 'john@example.com', phone: '+1234567890'}]\n"
                "Agent: Done! I've created a contact in HubSpot for you."
            ),
            "parameters": [
                {"name": "data", "description": "JSON payload for HubSpot API", "required": True, "example": '{"firstname": "John", "lastname": "Doe", "email": "john@example.com"}'},
            ],
        },
    },

    # ── Cal.com ──────────────────────────────────────────────────
    "cal_com": {
        "setup_guide": {
            "title": "Connect Cal.com",
            "estimated_time": "3 minutes",
            "difficulty": "Easy",
            "docs_url": "https://cal.com/docs/enterprise-features/api",
            "steps": [
                {
                    "step": 1,
                    "title": "Log Into Cal.com",
                    "description": "Go to cal.com and log into your account (or create one for free).",
                    "link": "https://app.cal.com/",
                },
                {
                    "step": 2,
                    "title": "Generate an API Key",
                    "description": "Go to Settings → Developer → API Keys → Create New. Copy the generated key.",
                    "link": "https://app.cal.com/settings/developer/api-keys",
                },
                {
                    "step": 3,
                    "title": "Find Your Event Type ID",
                    "description": "Go to Event Types → click the event you want to book → the ID is in the URL: cal.com/event-types/{ID}.",
                },
                {
                    "step": 4,
                    "title": "Configure in VOIA",
                    "description": "Enter the event type ID in the config. Set the API key.",
                },
            ],
            "notes": [
                "Free plan supports one event type.",
                "The API key provides access to all your Cal.com event types.",
                "Self-hosted Cal.com users should change the base_url to their instance URL.",
            ],
        },
        "field_overrides": {
            "base_url": {
                "label": "API Base URL",
                "placeholder": "https://api.cal.com/v1",
                "help_text": "Default Cal.com API URL. Change only if you self-host Cal.com.",
            },
            "event_type_id": {
                "label": "Event Type ID",
                "placeholder": "12345",
                "help_text": "The numeric ID of the event type to book. Found in the URL when editing an event type.",
            },
        },
        "api_key_help": "Your Cal.com API key. Generate at Settings → Developer → API Keys.",
    },

    # ── Calendly ─────────────────────────────────────────────────
    "calendly": {
        "setup_guide": {
            "title": "Connect Calendly",
            "estimated_time": "5 minutes",
            "difficulty": "Easy",
            "docs_url": "https://developer.calendly.com/getting-started",
            "steps": [
                {
                    "step": 1,
                    "title": "Log Into Calendly",
                    "description": "Go to calendly.com and sign in to your account.",
                    "link": "https://calendly.com/login",
                },
                {
                    "step": 2,
                    "title": "Generate a Personal Access Token",
                    "description": "Go to Integrations → API & Webhooks → Generate New Token. Name it 'VOIA' and copy it.",
                    "link": "https://calendly.com/integrations/api_webhooks",
                },
                {
                    "step": 3,
                    "title": "Get Your Organization URI",
                    "description": "Make a GET request to https://api.calendly.com/users/me with your token to find your organization URI (starts with https://api.calendly.com/organizations/...).",
                },
                {
                    "step": 4,
                    "title": "Find Event Type URI",
                    "description": "List your event types via the API or find the event type URI from the Calendly dashboard URLs. It starts with https://api.calendly.com/event_types/...",
                },
            ],
            "notes": [
                "Personal Access Tokens don't expire unless revoked.",
                "Organization URI is required for availability queries.",
                "Calendly's free plan supports one active event type.",
                "The API token has access to all event types in your account.",
            ],
        },
        "field_overrides": {
            "base_url": {
                "label": "API Base URL",
                "placeholder": "https://api.calendly.com",
                "help_text": "Calendly API base URL. Use the default value.",
            },
            "event_type_uri": {
                "label": "Event Type URI",
                "placeholder": "https://api.calendly.com/event_types/XXXXXXXX",
                "help_text": "Full URI of the Calendly event type. Found via the API or dashboard.",
            },
            "organization_uri": {
                "label": "Organization URI",
                "placeholder": "https://api.calendly.com/organizations/XXXXXXXX",
                "help_text": "Your organization URI. Get it by calling GET /users/me with your token.",
            },
        },
        "api_key_help": "Your Calendly Personal Access Token. Generate at Integrations → API & Webhooks.",
        "agent_usage": {
            "tools": ["webhook"],
            "trigger_phrases": [
                "book a meeting",
                "schedule a call",
                "find a slot",
            ],
            "example_scenario": (
                "Caller: Can we book a 30-minute intro call?\n"
                "Agent: Let me check availability and schedule it for you.\n"
                "[Agent calls webhook tool with data={event_type_uri: 'https://api.calendly.com/event_types/ABC', invitee_email: 'john@example.com'}]\n"
                "Agent: Done! I've scheduled the call. You'll receive a calendar invite shortly."
            ),
            "parameters": [
                {"name": "data", "description": "JSON payload for Calendly API", "required": True, "example": '{"event_type_uri": "https://api.calendly.com/event_types/ABC", "invitee_email": "john@example.com"}'},
            ],
        },
    },

    # ── Salesforce ───────────────────────────────────────────────
    "salesforce": {
        "setup_guide": {
            "title": "Connect Salesforce",
            "estimated_time": "10 minutes",
            "difficulty": "Medium",
            "docs_url": "https://developer.salesforce.com/docs/atlas.en-us.api_rest.meta/api_rest/",
            "steps": [
                {
                    "step": 1,
                    "title": "Log Into Salesforce",
                    "description": "Go to login.salesforce.com. You need a Salesforce org (Developer Edition is free).",
                    "link": "https://developer.salesforce.com/signup",
                },
                {
                    "step": 2,
                    "title": "Create a Connected App",
                    "description": "Go to Setup → App Manager → New Connected App. Enable OAuth, add scopes: 'api', 'refresh_token'. Set callback URL to https://login.salesforce.com/services/oauth2/callback.",
                    "link": "https://login.salesforce.com/",
                },
                {
                    "step": 3,
                    "title": "Get Consumer Key & Secret",
                    "description": "After saving, note the Consumer Key and Consumer Secret from the Connected App details.",
                },
                {
                    "step": 4,
                    "title": "Generate an Access Token",
                    "description": "Use the OAuth 2.0 username-password flow or the Salesforce CLI to generate an access token. For simple setups, create a Security Token from your profile settings.",
                },
                {
                    "step": 5,
                    "title": "Find Your Instance URL",
                    "description": "Your instance URL looks like https://yourorg.my.salesforce.com or https://yourorg.lightning.force.com. Check the URL when logged in.",
                },
            ],
            "notes": [
                "Developer Edition is free and includes full API access.",
                "API rate limits depend on your Salesforce edition.",
                "Access tokens expire — use refresh tokens for production.",
                "The instance URL is unique to your Salesforce org.",
            ],
        },
        "field_overrides": {
            "instance_url": {
                "label": "Instance URL",
                "placeholder": "https://yourorg.my.salesforce.com",
                "help_text": "Your Salesforce org URL. Found in the browser address bar when logged into Salesforce.",
            },
            "api_version": {
                "label": "API Version",
                "placeholder": "v59.0",
                "help_text": "Salesforce REST API version. Use the latest stable version (v59.0+).",
            },
        },
        "api_key_help": "Your Salesforce access token (Bearer token). Generate via OAuth flow or Salesforce CLI: sf org display --target-org your-org.",
        "agent_usage": {
            "tools": ["webhook"],
            "trigger_phrases": [
                "create a lead",
                "log this to salesforce",
                "add to my crm",
            ],
            "example_scenario": (
                "Caller: I'd like a demo of your product\n"
                "Agent: Great! Let me capture your details and create a lead in Salesforce.\n"
                "[Agent calls webhook tool with data={FirstName: 'John', LastName: 'Doe', Email: 'john@example.com', Phone: '+1234567890', Company: 'Acme Corp'}]\n"
                "Agent: Done! I've created a lead in Salesforce. Our sales team will reach out soon."
            ),
            "parameters": [
                {"name": "data", "description": "JSON payload for Salesforce API", "required": True, "example": '{"FirstName": "John", "LastName": "Doe", "Email": "john@example.com", "Company": "Acme Corp"}'},
            ],
        },
    },

    # ── Pipedrive ────────────────────────────────────────────────
    "pipedrive": {
        "setup_guide": {
            "title": "Connect Pipedrive",
            "estimated_time": "3 minutes",
            "difficulty": "Easy",
            "docs_url": "https://developers.pipedrive.com/docs/api/v1",
            "steps": [
                {
                    "step": 1,
                    "title": "Log Into Pipedrive",
                    "description": "Go to pipedrive.com and sign in (or start a free trial).",
                    "link": "https://app.pipedrive.com/",
                },
                {
                    "step": 2,
                    "title": "Get Your API Token",
                    "description": "Go to Settings (gear icon) → Personal Preferences → API → copy your personal API token.",
                    "link": "https://app.pipedrive.com/settings/api",
                },
                {
                    "step": 3,
                    "title": "Find Your Pipeline ID (Optional)",
                    "description": "Go to your pipeline view → the pipeline ID is in the URL or you can list pipelines via the API.",
                },
            ],
            "notes": [
                "The personal API token gives full access to your Pipedrive data.",
                "Rate limit: 100 requests per 10 seconds.",
                "Pipeline ID is needed only if you want to auto-assign deals to a specific pipeline.",
            ],
        },
        "field_overrides": {
            "base_url": {
                "label": "API Base URL",
                "placeholder": "https://api.pipedrive.com/v1",
                "help_text": "Pipedrive API URL. Use the default.",
            },
            "default_pipeline_id": {
                "label": "Default Pipeline ID",
                "placeholder": "1",
                "help_text": "Numeric ID of the pipeline for new deals. Found in URL or via API. Leave empty to use default pipeline.",
            },
        },
        "api_key_help": "Your Pipedrive personal API token. Found at Settings → Personal Preferences → API.",
        "agent_usage": {
            "tools": ["webhook"],
            "trigger_phrases": [
                "create a deal",
                "add to pipedrive",
                "log this lead",
            ],
            "example_scenario": (
                "Caller: I'm interested in your service\n"
                "Agent: Let me create a deal in Pipedrive for you.\n"
                "[Agent calls webhook tool with data={title: 'John Doe - Enterprise Inquiry', person_name: 'John Doe', email: 'john@example.com', phone: '+1234567890'}]\n"
                "Agent: Done! I've created a deal in Pipedrive. Our team will follow up within 24 hours."
            ),
            "parameters": [
                {"name": "data", "description": "JSON payload for Pipedrive API", "required": True, "example": '{"title": "John Doe - Enterprise Inquiry", "person_name": "John Doe", "email": "john@example.com"}'},
            ],
        },
    },

    # ── GoHighLevel ──────────────────────────────────────────────
    "gohighlevel": {
        "setup_guide": {
            "title": "Connect GoHighLevel",
            "estimated_time": "5 minutes",
            "difficulty": "Medium",
            "docs_url": "https://highlevel.stoplight.io/docs/integrations/",
            "steps": [
                {
                    "step": 1,
                    "title": "Log Into GoHighLevel",
                    "description": "Go to app.gohighlevel.com and sign in.",
                    "link": "https://app.gohighlevel.com/",
                },
                {
                    "step": 2,
                    "title": "Get Your API Key",
                    "description": "Go to Settings → Business Profile → scroll to API Key section → copy the API key. Or use the Marketplace to create an OAuth app.",
                },
                {
                    "step": 3,
                    "title": "Find Your Location ID",
                    "description": "Your Location ID is visible in the URL when you're in a sub-account: app.gohighlevel.com/v2/location/{LOCATION_ID}/...",
                },
            ],
            "notes": [
                "GoHighLevel API access requires an Agency or SaaS Pro plan.",
                "Location ID identifies the specific sub-account to work with.",
                "Rate limits vary by plan — typically 100 requests per 10 seconds.",
            ],
        },
        "field_overrides": {
            "base_url": {
                "label": "API Base URL",
                "placeholder": "https://rest.gohighlevel.com/v1",
                "help_text": "GoHighLevel API URL. Use the default for v1 API.",
            },
            "location_id": {
                "label": "Location ID",
                "placeholder": "abc123def456",
                "help_text": "Your GHL sub-account Location ID. Found in the URL when inside a sub-account.",
            },
        },
        "api_key_help": "Your GoHighLevel API key. Found at Settings → Business Profile → API Key.",
        "agent_usage": {
            "tools": ["webhook"],
            "trigger_phrases": [
                "create a contact",
                "add to gohighlevel",
                "log this in ghl",
            ],
            "example_scenario": (
                "Caller: Can you add me to your system?\n"
                "Agent: I'll create a contact in GoHighLevel right away.\n"
                "[Agent calls webhook tool with data={firstName: 'John', lastName: 'Doe', email: 'john@example.com', phone: '+1234567890', source: 'phone_call'}]\n"
                "Agent: Done! You're now in our system. You'll receive an SMS follow-up shortly."
            ),
            "parameters": [
                {"name": "data", "description": "JSON payload for GoHighLevel API", "required": True, "example": '{"firstName": "John", "lastName": "Doe", "email": "john@example.com", "phone": "+1234567890"}'},
            ],
        },
    },

    # ── Stripe ───────────────────────────────────────────────────
    "stripe": {
        "setup_guide": {
            "title": "Connect Stripe",
            "estimated_time": "3 minutes",
            "difficulty": "Easy",
            "docs_url": "https://stripe.com/docs/api",
            "steps": [
                {
                    "step": 1,
                    "title": "Create a Stripe Account",
                    "description": "Go to stripe.com and create an account (or log in).",
                    "link": "https://dashboard.stripe.com/register",
                },
                {
                    "step": 2,
                    "title": "Get Your API Key",
                    "description": "Go to Developers → API keys. Copy the Secret key (starts with sk_live_ or sk_test_). Use test keys for development!",
                    "link": "https://dashboard.stripe.com/apikeys",
                },
                {
                    "step": 3,
                    "title": "Configure in VOIA",
                    "description": "Paste your Secret key as the API key. Set your default currency (e.g., 'usd', 'eur', 'gbp').",
                },
            ],
            "notes": [
                "Use sk_test_ keys for development and testing — no real charges are made.",
                "Switch to sk_live_ keys when ready for production.",
                "NEVER share your secret key publicly.",
                "Stripe supports 135+ currencies. Common: usd, eur, gbp, cad, aud.",
            ],
        },
        "field_overrides": {
            "base_url": {
                "label": "API Base URL",
                "placeholder": "https://api.stripe.com/v1",
                "help_text": "Stripe API URL. Use the default.",
            },
            "currency": {
                "label": "Default Currency",
                "placeholder": "usd",
                "help_text": "Three-letter ISO currency code. Common: usd, eur, gbp, cad. Full list at stripe.com/docs/currencies.",
            },
        },
        "api_key_help": "Your Stripe Secret Key. Found at Dashboard → Developers → API Keys. Starts with sk_test_ (testing) or sk_live_ (production).",
        "agent_usage": {
            "tools": ["webhook"],
            "trigger_phrases": [
                "check my payment",
                "create a charge",
                "process payment",
            ],
            "example_scenario": (
                "Caller: Can you check if my payment went through?\n"
                "Agent: Let me look that up in Stripe.\n"
                "[Agent calls webhook tool with data={action: 'list_charges', customer_email: 'john@example.com'}]\n"
                "Agent: Yes, I can see a payment of $99 was processed successfully on June 10th."
            ),
            "parameters": [
                {"name": "data", "description": "JSON payload for Stripe API", "required": True, "example": '{"action": "list_charges", "customer_email": "john@example.com"}'},
            ],
        },
    },

    # ── Shopify ──────────────────────────────────────────────────
    "shopify": {
        "setup_guide": {
            "title": "Connect Shopify",
            "estimated_time": "5 minutes",
            "difficulty": "Medium",
            "docs_url": "https://shopify.dev/docs/api/admin-rest",
            "steps": [
                {
                    "step": 1,
                    "title": "Log Into Shopify Admin",
                    "description": "Go to your Shopify admin at yourstore.myshopify.com/admin.",
                    "link": "https://admin.shopify.com/",
                },
                {
                    "step": 2,
                    "title": "Create a Custom App",
                    "description": "Go to Settings → Apps and sales channels → Develop apps → Create an app. Name it 'VOIA'.",
                },
                {
                    "step": 3,
                    "title": "Configure API Scopes",
                    "description": "In your app → Configuration → Admin API access scopes. Select: read_orders, write_orders, read_products, read_customers. Click Save.",
                },
                {
                    "step": 4,
                    "title": "Install & Get Token",
                    "description": "Click 'Install app' → then go to API credentials → copy the Admin API access token.",
                },
                {
                    "step": 5,
                    "title": "Note Your Shop Domain",
                    "description": "Your shop domain is yourstore.myshopify.com (without https://). Enter this in the config.",
                },
            ],
            "notes": [
                "Custom apps are free to create on any Shopify plan.",
                "Admin API access token is shown only once — save it securely!",
                "API rate limit: 2 requests/second (40 requests in a burst).",
                "The shop domain must be the .myshopify.com domain, not a custom domain.",
            ],
        },
        "field_overrides": {
            "shop_domain": {
                "label": "Shop Domain",
                "placeholder": "yourstore.myshopify.com",
                "help_text": "Your Shopify store's .myshopify.com domain (not your custom domain). Found in Settings → Domains.",
            },
            "api_version": {
                "label": "API Version",
                "placeholder": "2024-01",
                "help_text": "Shopify API version (YYYY-MM format). Use latest stable version.",
            },
        },
        "api_key_help": "Your Shopify Admin API access token. Found in your custom app's API credentials after installation.",
        "agent_usage": {
            "tools": ["webhook"],
            "trigger_phrases": [
                "check my order",
                "what's the status",
                "track my package",
            ],
            "example_scenario": (
                "Caller: Can you check my order status?\n"
                "Agent: Sure, let me look that up in Shopify.\n"
                "[Agent calls webhook tool with data={action: 'get_order', query: 'john@example.com'}]\n"
                "Agent: I found your order #1001 — it's been shipped and should arrive by June 18th."
            ),
            "parameters": [
                {"name": "data", "description": "JSON payload for Shopify API", "required": True, "example": '{"action": "get_order", "query": "john@example.com"}'},
            ],
        },
    },

    # ── Zendesk ──────────────────────────────────────────────────
    "zendesk": {
        "setup_guide": {
            "title": "Connect Zendesk",
            "estimated_time": "3 minutes",
            "difficulty": "Easy",
            "docs_url": "https://developer.zendesk.com/api-reference/",
            "steps": [
                {
                    "step": 1,
                    "title": "Log Into Zendesk",
                    "description": "Go to your Zendesk admin at yourcompany.zendesk.com.",
                    "link": "https://www.zendesk.com/login/",
                },
                {
                    "step": 2,
                    "title": "Generate an API Token",
                    "description": "Go to Admin Center → Apps and integrations → Zendesk API → Token access → Add API token. Copy it.",
                    "link": "https://support.zendesk.com/hc/en-us/articles/4408889192858",
                },
                {
                    "step": 3,
                    "title": "Note Your Subdomain",
                    "description": "Your Zendesk subdomain is the part before .zendesk.com (e.g., if your URL is acme.zendesk.com, the subdomain is 'acme').",
                },
            ],
            "notes": [
                "API tokens use the format: email/token:API_TOKEN for authentication.",
                "Enter just the API token in the key field — VOIA handles the auth format.",
                "Rate limit: 700 requests per minute for Enterprise plans, less for other plans.",
                "Default priority levels: low, normal, high, urgent.",
            ],
        },
        "field_overrides": {
            "subdomain": {
                "label": "Zendesk Subdomain",
                "placeholder": "yourcompany",
                "help_text": "Just the subdomain part (not the full URL). If your URL is acme.zendesk.com, enter 'acme'.",
            },
            "default_priority": {
                "label": "Default Ticket Priority",
                "placeholder": "normal",
                "help_text": "Priority for new tickets. Options: low, normal, high, urgent.",
            },
        },
        "api_key_help": "Your Zendesk API token. Found at Admin Center → Apps and integrations → Zendesk API → Token access.",
        "agent_usage": {
            "tools": ["webhook"],
            "trigger_phrases": [
                "create a ticket",
                "file a complaint",
                "open a support request",
            ],
            "example_scenario": (
                "Caller: I need to report a billing issue\n"
                "Agent: I'll create a support ticket in Zendesk for you right away.\n"
                "[Agent calls webhook tool with data={subject: 'Billing Issue', description: 'Customer reports incorrect charge', requester_email: 'john@example.com'}]\n"
                "Agent: Done! I've created ticket #12345. Our support team will respond within 24 hours."
            ),
            "parameters": [
                {"name": "data", "description": "JSON payload for Zendesk API", "required": True, "example": '{"subject": "Billing Issue", "description": "Incorrect charge", "requester_email": "john@example.com"}'},
            ],
        },
    },

    # ── Intercom ─────────────────────────────────────────────────
    "intercom": {
        "setup_guide": {
            "title": "Connect Intercom",
            "estimated_time": "5 minutes",
            "difficulty": "Easy",
            "docs_url": "https://developers.intercom.com/building-apps/docs/rest-apis",
            "steps": [
                {
                    "step": 1,
                    "title": "Log Into Intercom",
                    "description": "Go to app.intercom.com and sign in.",
                    "link": "https://app.intercom.com/",
                },
                {
                    "step": 2,
                    "title": "Create a Developer App",
                    "description": "Go to Settings → Integrations → Developer Hub → New App. Or use an existing app's token.",
                    "link": "https://app.intercom.com/a/developer-signup",
                },
                {
                    "step": 3,
                    "title": "Get Your Access Token",
                    "description": "In your app settings → Authentication → copy the Access Token. This grants API access.",
                },
            ],
            "notes": [
                "Intercom access tokens don't expire but can be revoked.",
                "Rate limit: 1000 requests per minute for most endpoints.",
                "Contact management requires appropriate plan-level access.",
            ],
        },
        "field_overrides": {
            "base_url": {
                "label": "API Base URL",
                "placeholder": "https://api.intercom.io",
                "help_text": "Intercom API URL. Use the default.",
            },
        },
        "api_key_help": "Your Intercom Access Token. Found in Developer Hub → your app → Authentication.",
        "agent_usage": {
            "tools": ["webhook"],
            "trigger_phrases": [
                "send a message",
                "contact support",
                "start a conversation",
            ],
            "example_scenario": (
                "Caller: Can you send a message to your support team?\n"
                "Agent: I'll start a conversation in Intercom for you.\n"
                "[Agent calls webhook tool with data={message: 'Customer needs help with account setup', user_email: 'john@example.com'}]\n"
                "Agent: Done! Our support team will see your message and reply shortly."
            ),
            "parameters": [
                {"name": "data", "description": "JSON payload for Intercom API", "required": True, "example": '{"message": "Help needed", "user_email": "john@example.com"}'},
            ],
        },
    },

    # ── Freshdesk ────────────────────────────────────────────────
    "freshdesk": {
        "setup_guide": {
            "title": "Connect Freshdesk",
            "estimated_time": "3 minutes",
            "difficulty": "Easy",
            "docs_url": "https://developers.freshdesk.com/api/",
            "steps": [
                {
                    "step": 1,
                    "title": "Log Into Freshdesk",
                    "description": "Go to your Freshdesk portal at yourcompany.freshdesk.com.",
                    "link": "https://freshdesk.com/login",
                },
                {
                    "step": 2,
                    "title": "Get Your API Key",
                    "description": "Click your profile picture (top right) → Profile settings → Your API Key is shown on the right side.",
                },
                {
                    "step": 3,
                    "title": "Note Your Domain",
                    "description": "Your Freshdesk domain is the full URL: yourcompany.freshdesk.com.",
                },
            ],
            "notes": [
                "API key is unique per agent/user.",
                "Rate limits are per plan: Free=50/hr, Growth=200/min, Pro+=400/min.",
                "Priority values: 1=Low, 2=Medium, 3=High, 4=Urgent.",
            ],
        },
        "field_overrides": {
            "domain": {
                "label": "Freshdesk Domain",
                "placeholder": "yourcompany.freshdesk.com",
                "help_text": "Your full Freshdesk domain. Found in the browser URL when logged in.",
            },
            "default_priority": {
                "label": "Default Priority",
                "placeholder": "1",
                "help_text": "Numeric priority for new tickets. 1=Low, 2=Medium, 3=High, 4=Urgent.",
            },
        },
        "api_key_help": "Your Freshdesk API Key. Found at Profile Settings → API Key (right sidebar).",
        "agent_usage": {
            "tools": ["webhook"],
            "trigger_phrases": [
                "create a ticket",
                "file a support request",
                "report an issue",
            ],
            "example_scenario": (
                "Caller: My product arrived damaged\n"
                "Agent: I'm sorry to hear that. I'll create a support ticket in Freshdesk right away.\n"
                "[Agent calls webhook tool with data={subject: 'Damaged Product', description: 'Item arrived broken', email: 'john@example.com'}]\n"
                "Agent: Done! I've created ticket #9876. Our team will reach out with a replacement."
            ),
            "parameters": [
                {"name": "data", "description": "JSON payload for Freshdesk API", "required": True, "example": '{"subject": "Damaged Product", "description": "Item arrived broken", "email": "john@example.com"}'},
            ],
        },
    },

    # ── WhatsApp Business ────────────────────────────────────────
    "whatsapp_cloud": {
        "setup_guide": {
            "title": "Connect WhatsApp Business",
            "estimated_time": "15 minutes",
            "difficulty": "Advanced",
            "docs_url": "https://developers.facebook.com/docs/whatsapp/cloud-api/get-started",
            "steps": [
                {
                    "step": 1,
                    "title": "Create a Meta Developer Account",
                    "description": "Go to developers.facebook.com and create a developer account if you don't have one.",
                    "link": "https://developers.facebook.com/",
                },
                {
                    "step": 2,
                    "title": "Create a Business App",
                    "description": "In the Meta for Developers dashboard → Create App → Business type → add WhatsApp as a product.",
                },
                {
                    "step": 3,
                    "title": "Set Up WhatsApp Business",
                    "description": "Follow the setup wizard to connect your business phone number or use the test number provided.",
                },
                {
                    "step": 4,
                    "title": "Get Your Access Token",
                    "description": "In App Dashboard → WhatsApp → API Setup → copy the temporary access token. For production, create a System User token.",
                },
                {
                    "step": 5,
                    "title": "Get Phone Number ID",
                    "description": "In WhatsApp → API Setup, note the Phone Number ID displayed for your registered number.",
                },
            ],
            "notes": [
                "The temporary access token expires after 24 hours — use a System User token for production.",
                "WhatsApp Business API requires business verification for production use.",
                "Message templates must be pre-approved by Meta before sending.",
                "Test numbers can only message numbers added to the 'To' list in API setup.",
            ],
        },
        "field_overrides": {
            "phone_number_id": {
                "label": "Phone Number ID",
                "placeholder": "1234567890",
                "help_text": "The Phone Number ID from Meta's WhatsApp API Setup page. This is NOT your phone number — it's a numeric ID.",
            },
            "base_url": {
                "label": "Graph API Base URL",
                "placeholder": "https://graph.facebook.com/v18.0",
                "help_text": "Meta Graph API URL. Use the default unless Meta updates the API version.",
            },
        },
        "api_key_help": "Your WhatsApp Cloud API access token. For testing: use the temporary token from API Setup. For production: create a System User token in Business Settings.",
        "agent_usage": {
            "tools": ["send_whatsapp"],
            "trigger_phrases": [
                "send me a whatsapp",
                "message me on whatsapp",
                "whatsapp me the details",
            ],
            "example_scenario": (
                "Caller: Can you send me the order confirmation on WhatsApp?\n"
                "Agent: Sure! What's your WhatsApp number?\n"
                "Caller: +923001234567\n"
                "[Agent calls send_whatsapp tool with to='+923001234567', text='Order #123 confirmed. Total: PKR 3,500']\n"
                "Agent: Done! I've sent the confirmation to your WhatsApp."
            ),
            "parameters": [
                {"name": "to", "description": "Recipient phone number (E.164 format)", "required": True, "example": "+923001234567"},
                {"name": "text", "description": "Message text (max 4096 chars)", "required": True, "example": "Order #123 confirmed. Total: PKR 3,500"},
            ],
        },
    },

    # ── Discord ──────────────────────────────────────────────────
    "discord": {
        "setup_guide": {
            "title": "Connect Discord",
            "estimated_time": "2 minutes",
            "difficulty": "Easy",
            "docs_url": "https://discord.com/developers/docs/resources/webhook",
            "steps": [
                {
                    "step": 1,
                    "title": "Open Discord Server Settings",
                    "description": "Right-click your server → Server Settings → Integrations → Webhooks.",
                },
                {
                    "step": 2,
                    "title": "Create a Webhook",
                    "description": "Click 'New Webhook'. Choose the channel, customize the name and avatar.",
                },
                {
                    "step": 3,
                    "title": "Copy the Webhook URL",
                    "description": "Click 'Copy Webhook URL' and paste it into VOIA.",
                },
            ],
            "notes": [
                "Each webhook is tied to a specific channel.",
                "Webhook URLs start with https://discord.com/api/webhooks/",
                "No rate limit on webhook messages, but Discord may throttle if abused.",
                "You can customize the bot name per-message in VOIA workflows.",
            ],
        },
        "field_overrides": {
            "webhook_url": {
                "label": "Webhook URL",
                "placeholder": "https://discord.com/api/webhooks/123456/abcdef",
                "help_text": "Discord webhook URL. Found in Server Settings → Integrations → Webhooks.",
            },
            "bot_name": {
                "label": "Bot Display Name",
                "placeholder": "VOIA Bot",
                "help_text": "The name shown in Discord when VOIA sends a message.",
            },
        },
        "api_key_help": "No API key needed — the webhook URL contains authentication.",
        "agent_usage": {
            "tools": ["webhook"],
            "trigger_phrases": [
                "notify discord",
                "post to discord",
                "send to my server",
            ],
            "example_scenario": (
                "Caller: Can you alert the team about this urgent order?\n"
                "Agent: I'll post a notification to the Discord server right away.\n"
                "[Agent calls webhook tool with data={content: 'Urgent order: 2x laptops, total $2,400 — needs immediate processing'}]\n"
                "Agent: Done! The team has been notified on Discord."
            ),
            "parameters": [
                {"name": "data", "description": "JSON payload for Discord webhook", "required": True, "example": '{"content": "Urgent order received"}'},
            ],
        },
    },

    # ── Microsoft Teams ──────────────────────────────────────────
    "microsoft_teams": {
        "setup_guide": {
            "title": "Connect Microsoft Teams",
            "estimated_time": "3 minutes",
            "difficulty": "Easy",
            "docs_url": "https://learn.microsoft.com/en-us/microsoftteams/platform/webhooks-and-connectors/how-to/add-incoming-webhook",
            "steps": [
                {
                    "step": 1,
                    "title": "Open Teams Channel Settings",
                    "description": "In Microsoft Teams, go to the channel where you want notifications → click '…' → Connectors (or 'Manage channel').",
                },
                {
                    "step": 2,
                    "title": "Add Incoming Webhook",
                    "description": "Search for 'Incoming Webhook' → click Configure. Name it 'VOIA' and optionally upload an icon.",
                },
                {
                    "step": 3,
                    "title": "Copy the Webhook URL",
                    "description": "Click Create → copy the webhook URL generated. Paste it into VOIA.",
                },
            ],
            "notes": [
                "Incoming Webhooks are available on all Teams plans.",
                "Each webhook posts to one specific channel.",
                "Messages support Teams Adaptive Cards for rich formatting.",
                "Admin may need to enable connectors if they're disabled.",
            ],
        },
        "field_overrides": {
            "webhook_url": {
                "label": "Teams Webhook URL",
                "placeholder": "https://outlook.office.com/webhook/...",
                "help_text": "The Incoming Webhook URL from your Teams channel connector settings.",
            },
        },
        "api_key_help": "No API key needed — the webhook URL contains authentication.",
        "agent_usage": {
            "tools": ["webhook"],
            "trigger_phrases": [
                "notify the team",
                "post to teams",
                "send to microsoft teams",
            ],
            "example_scenario": (
                "Caller: Can you notify the operations team?\n"
                "Agent: I'll post a message to the Teams channel now.\n"
                "[Agent calls webhook tool with data={text: 'New high-priority order received from phone call. Customer: John Doe, Amount: $5,000'}]\n"
                "Agent: Done! The operations team has been notified on Teams."
            ),
            "parameters": [
                {"name": "data", "description": "JSON payload for Teams webhook", "required": True, "example": '{"text": "New high-priority order received"}'},
            ],
        },
    },

    # ── SendGrid ─────────────────────────────────────────────────
    "sendgrid": {
        "setup_guide": {
            "title": "Connect SendGrid",
            "estimated_time": "5 minutes",
            "difficulty": "Easy",
            "docs_url": "https://docs.sendgrid.com/for-developers/sending-email/quickstart-python",
            "steps": [
                {
                    "step": 1,
                    "title": "Create a SendGrid Account",
                    "description": "Sign up at sendgrid.com. The free tier allows 100 emails/day.",
                    "link": "https://signup.sendgrid.com/",
                },
                {
                    "step": 2,
                    "title": "Verify a Sender",
                    "description": "Go to Settings → Sender Authentication → Verify a Single Sender. Enter and verify an email address.",
                    "link": "https://app.sendgrid.com/settings/sender_auth",
                },
                {
                    "step": 3,
                    "title": "Create an API Key",
                    "description": "Go to Settings → API Keys → Create API Key. Choose 'Full Access' or 'Restricted Access' with Mail Send permission. Copy the key.",
                    "link": "https://app.sendgrid.com/settings/api_keys",
                },
                {
                    "step": 4,
                    "title": "Configure in VOIA",
                    "description": "Enter the verified sender email in the config and paste your API key.",
                },
            ],
            "notes": [
                "Free tier: 100 emails/day forever.",
                "Sender email must be verified before sending.",
                "API keys start with 'SG.'",
                "For high volume, verify your domain instead of individual emails.",
            ],
        },
        "field_overrides": {
            "from_email": {
                "label": "Verified Sender Email",
                "placeholder": "noreply@yourcompany.com",
                "help_text": "Must be a verified sender in SendGrid. Verify at Settings → Sender Authentication.",
            },
            "from_name": {
                "label": "Sender Display Name",
                "placeholder": "VOIA",
                "help_text": "The name recipients see in their inbox (e.g., 'Acme Support').",
            },
        },
        "api_key_help": "Your SendGrid API key. Starts with 'SG.' Found at Settings → API Keys.",
        "agent_usage": {
            "tools": ["webhook"],
            "trigger_phrases": [
                "send an email via sendgrid",
                "use sendgrid",
            ],
            "example_scenario": (
                "Caller: Can you email me the invoice?\n"
                "Agent: I'll send that via SendGrid now.\n"
                "[Agent calls webhook tool with data={to: 'john@example.com', subject: 'Invoice #456', template_id: 'd-abc123'}]\n"
                "Agent: Done! The invoice has been sent to your email."
            ),
            "parameters": [
                {"name": "data", "description": "JSON payload for SendGrid API", "required": True, "example": '{"to": "john@example.com", "subject": "Invoice", "template_id": "d-abc123"}'},
            ],
        },
    },

    # ── Notion ───────────────────────────────────────────────────
    "notion": {
        "setup_guide": {
            "title": "Connect Notion",
            "estimated_time": "5 minutes",
            "difficulty": "Easy",
            "docs_url": "https://developers.notion.com/docs/getting-started",
            "steps": [
                {
                    "step": 1,
                    "title": "Create an Integration",
                    "description": "Go to notion.so/my-integrations → New integration. Name it 'VOIA', select your workspace, and submit.",
                    "link": "https://www.notion.so/my-integrations",
                },
                {
                    "step": 2,
                    "title": "Copy the Integration Token",
                    "description": "After creation, copy the Internal Integration Token (starts with 'ntn_' or 'secret_').",
                },
                {
                    "step": 3,
                    "title": "Share Pages/Databases with Integration",
                    "description": "In Notion, open the page or database → click '…' → Connections → find your integration → Connect. The integration can only access pages shared with it.",
                },
                {
                    "step": 4,
                    "title": "Get Database ID (Optional)",
                    "description": "Open a database in full page → the ID is in the URL: notion.so/{workspace}/{DATABASE_ID}?v=... (32 hex characters).",
                },
            ],
            "notes": [
                "Integrations can ONLY access pages/databases explicitly shared with them.",
                "Database ID is 32 characters (with dashes removed from the URL).",
                "Rate limit: 3 requests/second.",
                "Free Notion accounts support integrations.",
            ],
        },
        "field_overrides": {
            "default_database_id": {
                "label": "Default Database ID",
                "placeholder": "abc123def456abc123def456abc123de",
                "help_text": "32-character ID from the database page URL. The database must be shared with your integration.",
            },
        },
        "api_key_help": "Your Notion Internal Integration Token. Found at notion.so/my-integrations → your integration → Secrets.",
        "agent_usage": {
            "tools": ["webhook"],
            "trigger_phrases": [
                "create a page",
                "add to notion",
                "log in notion",
            ],
            "example_scenario": (
                "Caller: Can you log this meeting summary?\n"
                "Agent: I'll create a page in Notion for you.\n"
                "[Agent calls webhook tool with data={parent: {database_id: 'abc123'}, properties: {Name: {title: [{text: {content: 'Meeting with John Doe'}}]}}}]\n"
                "Agent: Done! I've logged the meeting summary in your Notion database."
            ),
            "parameters": [
                {"name": "data", "description": "JSON payload for Notion API", "required": True, "example": '{"parent": {"database_id": "abc123"}, "properties": {"Name": {"title": [{"text": {"content": "Meeting Summary"}}]}}}'},
            ],
        },
    },

    # ── Airtable ─────────────────────────────────────────────────
    "airtable": {
        "setup_guide": {
            "title": "Connect Airtable",
            "estimated_time": "3 minutes",
            "difficulty": "Easy",
            "docs_url": "https://airtable.com/developers/web/api/introduction",
            "steps": [
                {
                    "step": 1,
                    "title": "Log Into Airtable",
                    "description": "Go to airtable.com and sign in.",
                    "link": "https://airtable.com/login",
                },
                {
                    "step": 2,
                    "title": "Create a Personal Access Token",
                    "description": "Go to airtable.com/create/tokens → Create New Token. Add scopes: data.records:read, data.records:write. Select the bases you want to access.",
                    "link": "https://airtable.com/create/tokens",
                },
                {
                    "step": 3,
                    "title": "Find Your Base ID",
                    "description": "Open your base → the base ID is in the URL: airtable.com/{BASE_ID}/... (starts with 'app').",
                },
            ],
            "notes": [
                "Personal access tokens start with 'pat'.",
                "Base IDs start with 'app'.",
                "Rate limit: 5 requests/second per base.",
                "Tokens can be scoped to specific bases for security.",
            ],
        },
        "field_overrides": {
            "base_id": {
                "label": "Base ID",
                "placeholder": "appXXXXXXXXXXXXXX",
                "help_text": "Your Airtable base ID. Starts with 'app'. Found in the URL when viewing your base.",
            },
            "default_table": {
                "label": "Default Table Name",
                "placeholder": "Tasks",
                "help_text": "The table name to use by default. Table names are case-sensitive.",
            },
        },
        "api_key_help": "Your Airtable Personal Access Token. Starts with 'pat'. Generate at airtable.com/create/tokens.",
        "agent_usage": {
            "tools": ["webhook"],
            "trigger_phrases": [
                "create a record",
                "add to airtable",
                "log in airtable",
            ],
            "example_scenario": (
                "Caller: Can you add me to your contacts database?\n"
                "Agent: I'll create a record in Airtable for you.\n"
                "[Agent calls webhook tool with data={fields: {Name: 'John Doe', Email: 'john@example.com', Phone: '+1234567890', Source: 'Phone Call'}}]\n"
                "Agent: Done! I've added you to the contacts database in Airtable."
            ),
            "parameters": [
                {"name": "data", "description": "JSON payload for Airtable API", "required": True, "example": '{"fields": {"Name": "John Doe", "Email": "john@example.com", "Source": "Phone Call"}}'},
            ],
        },
    },

    # ── Make (Integromat) ────────────────────────────────────────
    "make": {
        "setup_guide": {
            "title": "Connect Make (Integromat)",
            "estimated_time": "5 minutes",
            "difficulty": "Easy",
            "docs_url": "https://www.make.com/en/help/tools/webhooks",
            "steps": [
                {
                    "step": 1,
                    "title": "Create a Make Account",
                    "description": "Sign up at make.com (formerly Integromat). Free tier includes 1000 operations/month.",
                    "link": "https://www.make.com/en/register",
                },
                {
                    "step": 2,
                    "title": "Create a New Scenario",
                    "description": "Click 'Create a new scenario'. Add a 'Webhooks' module → choose 'Custom webhook'.",
                },
                {
                    "step": 3,
                    "title": "Create the Webhook",
                    "description": "Click 'Add' to create a new webhook → name it 'VOIA' → copy the generated URL.",
                },
                {
                    "step": 4,
                    "title": "Add Actions",
                    "description": "Add more modules to your scenario for what should happen when VOIA triggers it (e.g., update a Google Sheet, send Slack message).",
                },
                {
                    "step": 5,
                    "title": "Activate the Scenario",
                    "description": "Turn the scenario ON (toggle in bottom-left). It's now ready to receive data from VOIA.",
                },
            ],
            "notes": [
                "Free plan: 1000 operations/month, 2 active scenarios.",
                "Each webhook URL is unique to one scenario.",
                "Make will auto-detect the data structure from the first request VOIA sends.",
                "You can chain unlimited modules in a single scenario.",
            ],
        },
        "field_overrides": {
            "webhook_url": {
                "label": "Make Webhook URL",
                "placeholder": "https://hook.us1.make.com/xxxxxxxxxxxxx",
                "help_text": "The Custom Webhook URL from your Make scenario. Found in the Webhooks module settings.",
            },
        },
        "api_key_help": "No API key needed — the webhook URL includes authentication.",
        "agent_usage": {
            "tools": ["webhook"],
            "trigger_phrases": [
                "trigger my scenario",
                "run my make automation",
                "send to make",
            ],
            "example_scenario": (
                "Caller: Please log this to my project management system\n"
                "Agent: I'll trigger your Make scenario now.\n"
                "[Agent calls webhook tool with data={task: 'Follow up with John Doe', priority: 'high', due_date: '2026-06-20'}]\n"
                "Agent: Done! Your Make scenario has been triggered."
            ),
            "parameters": [
                {"name": "data", "description": "JSON payload for Make webhook", "required": True, "example": '{"task": "Follow up with John Doe", "priority": "high"}'},
            ],
        },
    },

    # ── Jira ─────────────────────────────────────────────────────
    "jira": {
        "setup_guide": {
            "title": "Connect Jira",
            "estimated_time": "5 minutes",
            "difficulty": "Easy",
            "docs_url": "https://developer.atlassian.com/cloud/jira/platform/rest/v3/intro/",
            "steps": [
                {
                    "step": 1,
                    "title": "Log Into Jira (Atlassian)",
                    "description": "Go to your Jira instance (yourorg.atlassian.net).",
                    "link": "https://id.atlassian.com/login",
                },
                {
                    "step": 2,
                    "title": "Create an API Token",
                    "description": "Go to id.atlassian.com → Security → API tokens → Create API token. Name it 'VOIA' and copy it.",
                    "link": "https://id.atlassian.com/manage-profile/security/api-tokens",
                },
                {
                    "step": 3,
                    "title": "Find Your Instance URL",
                    "description": "Your Jira URL looks like: https://yourorg.atlassian.net. This is your base_url.",
                },
                {
                    "step": 4,
                    "title": "Find Your Project Key",
                    "description": "Open your project → the key is shown in the sidebar (e.g., 'PROJ'). Issue IDs use this prefix (PROJ-123).",
                },
            ],
            "notes": [
                "API tokens are tied to your Atlassian account email.",
                "Auth uses: email:api_token (base64 encoded Basic auth).",
                "Just provide the API token — VOIA handles the auth encoding.",
                "Project keys are typically 2-4 uppercase letters.",
            ],
        },
        "field_overrides": {
            "base_url": {
                "label": "Jira Instance URL",
                "placeholder": "https://yourorg.atlassian.net",
                "help_text": "Your Jira Cloud URL. Found in browser when logged in. Must include https://.",
            },
            "project_key": {
                "label": "Default Project Key",
                "placeholder": "PROJ",
                "help_text": "The short code for your Jira project (e.g., PROJ, DEV, SUPPORT). Found in project settings or issue IDs.",
            },
        },
        "api_key_help": "Your Atlassian API token. Generate at id.atlassian.com → Security → API Tokens.",
        "agent_usage": {
            "tools": ["webhook"],
            "trigger_phrases": [
                "create a jira ticket",
                "file a bug",
                "open a jira issue",
            ],
            "example_scenario": (
                "Caller: I found a bug in your app\n"
                "Agent: I'll create a Jira ticket for the engineering team.\n"
                "[Agent calls webhook tool with data={project: 'PROJ', summary: 'Bug: Login fails on mobile', description: 'Customer reports login button unresponsive on iOS Safari', issuetype: 'Bug'}]\n"
                "Agent: Done! I've created ticket PROJ-456. The engineering team will investigate."
            ),
            "parameters": [
                {"name": "data", "description": "JSON payload for Jira API", "required": True, "example": '{"project": "PROJ", "summary": "Bug: Login fails", "description": "Customer report", "issuetype": "Bug"}'},
            ],
        },
    },

    # ── Linear ───────────────────────────────────────────────────
    "linear": {
        "setup_guide": {
            "title": "Connect Linear",
            "estimated_time": "3 minutes",
            "difficulty": "Easy",
            "docs_url": "https://developers.linear.app/docs/graphql/working-with-the-graphql-api",
            "steps": [
                {
                    "step": 1,
                    "title": "Log Into Linear",
                    "description": "Go to linear.app and sign in.",
                    "link": "https://linear.app/",
                },
                {
                    "step": 2,
                    "title": "Create an API Key",
                    "description": "Go to Settings → API → Personal API Keys → Create key. Name it 'VOIA' and copy the generated key.",
                    "link": "https://linear.app/settings/api",
                },
                {
                    "step": 3,
                    "title": "Find Your Team ID (Optional)",
                    "description": "Go to Settings → Teams → click a team → the ID is in the URL. Or query the API: { teams { nodes { id name } } }",
                },
            ],
            "notes": [
                "Linear API keys don't expire unless revoked.",
                "Linear uses GraphQL — VOIA handles the query construction.",
                "Rate limit: 1500 requests per hour.",
                "Team ID is only needed if you want to auto-assign issues to a specific team.",
            ],
        },
        "field_overrides": {
            "team_id": {
                "label": "Default Team ID",
                "placeholder": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
                "help_text": "UUID of the Linear team. Found in Settings → Teams → click team → ID in URL. Leave empty to select at runtime.",
            },
        },
        "api_key_help": "Your Linear Personal API Key. Generate at Settings → API → Personal API Keys.",
        "agent_usage": {
            "tools": ["webhook"],
            "trigger_phrases": [
                "create a linear issue",
                "file a bug in linear",
                "add to linear",
            ],
            "example_scenario": (
                "Caller: I have a feature request\n"
                "Agent: I'll create an issue in Linear for the product team.\n"
                "[Agent calls webhook tool with data={title: 'Feature: Dark mode support', description: 'Customer requests dark mode for mobile app', teamId: 'team_abc123'}]\n"
                "Agent: Done! I've created the issue in Linear. The product team will review it."
            ),
            "parameters": [
                {"name": "data", "description": "JSON payload for Linear API", "required": True, "example": '{"title": "Feature request", "description": "Customer feedback", "teamId": "team_abc123"}'},
            ],
        },
    },

    # ── MCP Server (Generic) ────────────────────────────────────
    "mcp": {
        "setup_guide": {
            "title": "Connect an MCP Server",
            "estimated_time": "5 minutes",
            "difficulty": "Medium",
            "docs_url": "https://modelcontextprotocol.io/introduction",
            "steps": [
                {
                    "step": 1,
                    "title": "Find or Deploy an MCP Server",
                    "description": (
                        "MCP servers expose tools over JSON-RPC 2.0 / HTTP. "
                        "You can use a public hosted MCP server, deploy one yourself, "
                        "or use Google's Workspace MCP servers (Drive, Calendar, Gmail)."
                    ),
                    "link": "https://github.com/modelcontextprotocol/servers",
                },
                {
                    "step": 2,
                    "title": "Get the Server URL",
                    "description": (
                        "The MCP server URL is the HTTP endpoint that accepts JSON-RPC POST requests. "
                        "Example: https://mcp.example.com or https://mcp.example.com/mcp. "
                        "VOIA tries /mcp first, then falls back to the root URL."
                    ),
                },
                {
                    "step": 3,
                    "title": "Get Authentication (if required)",
                    "description": (
                        "Some MCP servers require a Bearer token for authentication. "
                        "If your server needs auth, paste the token below. "
                        "For Google Workspace MCP servers, authentication is handled automatically via OAuth."
                    ),
                },
                {
                    "step": 4,
                    "title": "Test the Connection",
                    "description": (
                        "After saving, click 'Test' to verify VOIA can connect to the server "
                        "and list available tools. The test calls tools/list and reports back."
                    ),
                },
            ],
            "notes": [
                "MCP servers communicate via JSON-RPC 2.0 over HTTP (Streamable HTTP transport).",
                "VOIA automatically discovers all available tools via the tools/list RPC method.",
                "Tool responses are truncated to 4000 characters to protect the LLM context window.",
                "Internal/private URLs (localhost, 10.x, 192.168.x) are blocked for security (SSRF protection).",
                "For Google Workspace MCP servers, use the dedicated integration types (Google Drive MCP, etc.) instead.",
            ],
        },
        "field_overrides": {
            "server_url": {
                "label": "MCP Server URL",
                "placeholder": "https://mcp.example.com",
                "help_text": "The HTTP endpoint of your MCP server. VOIA will try /mcp then fall back to root.",
            },
        },
        "api_key_help": "Bearer token for MCP server authentication. Leave blank if the server doesn't require auth.",
        "agent_usage": {
            "tools": [],
            "trigger_phrases": [
                "use my custom tool",
                "call the mcp server",
            ],
            "example_scenario": (
                "Caller: Can you check my custom database?\n"
                "Agent: I'll query the MCP server for that information.\n"
                "[Agent calls dynamically discovered MCP tool]\n"
                "Agent: Here is the information from your custom database."
            ),
            "parameters": [],
        },
    },

    # ── Custom API ──────────────────────────────────────────────
    "custom_api": {
        "setup_guide": {
            "title": "Configure Custom API",
            "estimated_time": "3 minutes",
            "difficulty": "Medium",
            "docs_url": "https://developer.mozilla.org/en-US/docs/Web/HTTP/Overview",
            "steps": [
                {
                    "step": 1,
                    "title": "Identify Your API Endpoint",
                    "description": (
                        "Determine the full URL of the REST API endpoint you want to call. "
                        "This can be any HTTP API — your own backend, a SaaS API, etc."
                    ),
                },
                {
                    "step": 2,
                    "title": "Configure Authentication",
                    "description": (
                        "Set up the required authentication headers. "
                        "Common patterns: Bearer token in Authorization header, API key in a custom header, "
                        "or Basic auth. Configure these in the Custom API node in your workflow."
                    ),
                },
                {
                    "step": 3,
                    "title": "Use in Workflow",
                    "description": (
                        "Add a Custom API node in your workflow builder. "
                        "Configure the HTTP method, URL, headers, and request body. "
                        "Use template variables like {{caller_name}} for dynamic data."
                    ),
                },
            ],
            "notes": [
                "Custom API nodes support GET, POST, PUT, PATCH, and DELETE methods.",
                "Request bodies should be valid JSON.",
                "Use template variables ({{caller_name}}, {{transcript}}, etc.) for dynamic data.",
                "Response mappings use JSONPath syntax to extract data from the API response.",
                "Timeout defaults to 30 seconds.",
            ],
        },
        "field_overrides": {},
        "api_key_help": "If the API uses a static API key, paste it here. It will be stored securely. Otherwise, set auth in the workflow node.",
        "agent_usage": {
            "tools": ["webhook"],
            "trigger_phrases": [
                "call my api",
                "hit the endpoint",
                "send to my backend",
            ],
            "example_scenario": (
                "Caller: Can you check my internal system?\n"
                "Agent: I'll call your custom API endpoint now.\n"
                "[Agent calls webhook tool with data={endpoint: '/customers/lookup', method: 'GET', params: {phone: '+1234567890'}}]\n"
                "Agent: I found your record in the system. Your account is active."
            ),
            "parameters": [
                {"name": "data", "description": "JSON payload for the custom API request", "required": True, "example": '{"endpoint": "/lookup", "method": "GET", "params": {"phone": "+1234567890"}}'},
            ],
        },
    },

    # ── Google Drive MCP ─────────────────────────────────────────
    "google_drive_mcp": {
        "setup_guide": {
            "title": "Connect Google Drive (MCP)",
            "estimated_time": "10 minutes",
            "difficulty": "Medium",
            "docs_url": "https://developers.google.com/workspace/drive/api/guides/configure-mcp-server",
            "steps": [
                {
                    "step": 1,
                    "title": "Enable Google APIs",
                    "description": (
                        "In the Google Cloud Console, enable both the Google Drive API "
                        "and the Google Drive MCP API for your project. Run: "
                        "gcloud services enable drive.googleapis.com drivemcp.googleapis.com --project=YOUR_PROJECT_ID"
                    ),
                    "link": "https://console.cloud.google.com/flows/enableapi?apiid=drive.googleapis.com,drivemcp.googleapis.com",
                },
                {
                    "step": 2,
                    "title": "Connect your Google account",
                    "description": (
                        "Click 'Connect with Google' in VOIA and approve the Drive access request. "
                        "This grants VOIA read and file-scoped write access to your Google Drive."
                    ),
                },
                {
                    "step": 3,
                    "title": "Create the Integration",
                    "description": (
                        "Give it a name (e.g. 'My Drive'). The server URL is auto-filled. "
                        "Authentication is handled automatically via your connected Google account — no API key needed."
                    ),
                },
                {
                    "step": 4,
                    "title": "Use in Workflows or Agents",
                    "description": (
                        "Add an MCP Tool node in your workflow builder or attach this integration from an agent's Google Drive selector. "
                        "Tool names are discovered dynamically from the MCP server — no manual configuration needed."
                    ),
                },
            ],
            "notes": [
                "Google Drive MCP is a Google Developer Preview feature.",
                "Authentication is handled via OAuth — no manual API key or token management needed.",
                "Available scopes: drive.readonly (read files) and drive.file (create/edit files created by VOIA).",
                "VOIA cannot access files unless the user explicitly grants permission via the OAuth consent screen.",
            ],
        },
        "field_overrides": {
            "server_url": {
                "label": "MCP Server URL",
                "placeholder": "https://drivemcp.googleapis.com/mcp/v1",
                "help_text": "Google's hosted Drive MCP endpoint. This is auto-filled — do not change unless using a custom proxy.",
            },
        },
        "api_key_help": "No API key required. Google Drive MCP uses OAuth 2.0 — connect your Google account above.",
        "agent_usage": {
            "tools": ["read_drive_file", "recall_document"],
            "trigger_phrases": [
                "check my document",
                "read my file",
                "verify my contract",
                "what's in my drive",
                "find my document",
            ],
            "example_scenario": (
                "Caller: Can you verify my contract?\n"
                "Agent: Sure! Let me read it from your Google Drive.\n"
                "[Agent calls read_drive_file tool with file_id='abc123']\n"
                "Agent: I've read your contract. It is dated June 1, 2026, and signed by both parties. Everything looks in order."
            ),
            "parameters": [
                {"name": "file_id", "description": "File ID from Google Drive", "required": True, "example": "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms"},
                {"name": "file_name", "description": "Human-readable file name for reference", "required": False, "example": "Contract_John_Doe.pdf"},
            ],
        },
    },
}
