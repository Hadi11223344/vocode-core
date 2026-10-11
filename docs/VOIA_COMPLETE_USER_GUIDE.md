# VOIA — Complete User & Developer Guide

> **For Everyone**: Whether you're a developer building on VOIA or a business owner setting up your first AI receptionist, this guide walks you through every feature with real-world examples.
>
> **Last updated**: March 2026

---

## Table of Contents

1. [What is VOIA?](#1-what-is-voia)
2. [Quick Start — Your First AI Agent in 5 Minutes](#2-quick-start--your-first-ai-agent-in-5-minutes)
3. [Understanding Workflows (The Brain of VOIA)](#3-understanding-workflows-the-brain-of-voia)
4. [Node Types Explained (With Examples)](#4-node-types-explained-with-examples)
5. [Integrations — Connecting Your Business Tools](#5-integrations--connecting-your-business-tools)
6. [Pre-Built Templates — Ready-to-Use Workflows](#6-pre-built-templates--ready-to-use-workflows)
7. [Real-World Use Cases (Step-by-Step)](#7-real-world-use-cases-step-by-step)
8. [Template Variables — Dynamic Data in Your Workflows](#8-template-variables--dynamic-data-in-your-workflows)
9. [Integration Setup Guides](#9-integration-setup-guides)
10. [Advanced Workflow Patterns](#10-advanced-workflow-patterns)
11. [Troubleshooting & FAQ](#11-troubleshooting--faq)
12. [Developer Reference](#12-developer-reference)

---

## 1. What is VOIA?

VOIA is an **AI voice agent platform** that answers your business phone calls, has natural conversations with callers, and takes real actions — like booking appointments, looking up orders, creating support tickets, and sending follow-up emails.

### Think of it like this:

> **Without VOIA**: A customer calls your business at 10 PM. Nobody answers. They hang up and call your competitor.
>
> **With VOIA**: Your AI agent answers immediately, asks the right questions, books an appointment in Google Calendar, sends a confirmation SMS, and logs the lead in Salesforce — all while sounding natural and friendly.

### What VOIA Can Do

| Capability | What It Means |
|-----------|---------------|
| **Answer Calls 24/7** | Your AI never sleeps, takes breaks, or calls in sick |
| **Natural Conversations** | Powered by advanced LLMs (GPT, Groq, etc.) — not robotic IVR menus |
| **Take Real Actions** | Book appointments, send emails, create tickets, process orders |
| **28+ Integrations** | Connect to Salesforce, Stripe, Zendesk, Shopify, Slack, and more |
| **Visual Workflow Builder** | Drag-and-drop editor to design call flows — no coding needed |
| **21 Ready-Made Templates** | Pre-built workflows for healthcare, real estate, e-commerce, and more |
| **Smart Routing** | Route different callers to different agents based on phone number |

---

## 2. Quick Start — Your First AI Agent in 5 Minutes

### Step 1: Create an Agent

1. Open your VOIA dashboard at `http://localhost:3001`
2. Click **Agents** in the sidebar
3. Click **+ Create Agent**
4. Fill in:
   - **Name**: `Reception Bot` (this is just for your reference)
   - **System Prompt**: This is the personality and instructions for your AI. Example:

   ```
   You are a friendly receptionist for Sunrise Dental Clinic.
   Your name is Sarah. Be warm, professional, and helpful.
   
   Key information:
   - Business hours: Mon-Fri 9am-5pm, Sat 9am-1pm
   - Address: 123 Main Street, Suite 200
   - We accept most insurance plans
   
   Your job is to:
   1. Greet callers warmly
   2. Ask how you can help them
   3. If they want an appointment, collect their name, phone, and preferred date
   4. If they have a question, answer it or offer to transfer to staff
   ```

5. Choose your **Voice** (e.g., `aura-asteria-en` for a natural female voice)
6. Click **Save**

### Step 2: Connect Your Phone Number

1. Go to **Settings** → **Phone Numbers**
2. Enter your Twilio phone number (e.g., `+14155551234`)
3. Assign it to your `Reception Bot` agent
4. Save

### Step 3: Test It

1. Go to **Agents** → click your agent → **Test Call**
2. Or simply call your Twilio number from any phone!

**That's it!** Your AI receptionist is live. But to make it truly powerful, you'll want to add **workflows**.

---

## 3. Understanding Workflows (The Brain of VOIA)

A **workflow** is a set of instructions that tells your AI agent what to *do* based on what the caller says. Without workflows, your agent can only talk. With workflows, your agent can **take action**.

### How Workflows Work (Simple Explanation)

```
Caller says something → AI recognizes a trigger → Workflow executes step by step
```

### Visual Example

Imagine this phone call:

> **Caller**: "Hi, I'd like to book an appointment for next Tuesday."
>
> **AI Agent**: "Of course! What's your name?"
>
> **Caller**: "It's John Smith."
>
> **AI Agent**: "And your email?"
>
> **Caller**: "john@email.com"
>
> **AI Agent**: "Perfect! I've booked you for Tuesday at 10 AM and sent a confirmation to your email. Is there anything else?"

Behind the scenes, this workflow happened:

```
┌─────────────────┐
│   Call Trigger   │ ← Caller says "book", "appointment", "schedule"
│ "book, schedule" │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Conversation   │ ← AI collects name, email, preferred date
│ "Collect info"  │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Google Calendar  │ ← Checks availability, creates event
│ "Create Event"  │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Condition Check  │ ← Was the booking successful?
│ "result.success" │
├──── Yes ────┬── No ──┐
│             ▼        ▼
│      ┌──────────┐ ┌──────────┐
│      │ Send SMS │ │ Transfer │
│      │ Confirm  │ │ to Staff │
│      └──────────┘ └──────────┘
```

### Creating a Workflow

1. Go to **Workflows** in the sidebar
2. Click **+ New Workflow**
3. The visual editor opens — you'll see a **trigger node** already placed
4. Click **+ Add Node** to add steps or use a **template** (recommended for beginners!)

---

## 4. Node Types Explained (With Examples)

Nodes are the building blocks of your workflows. Each node does one specific thing. Here's every node type available in VOIA:

### Flow Control Nodes

| Node | What It Does | When to Use |
|------|-------------|-------------|
| **Call Trigger** | Starts the workflow when specific phrases are detected | Every workflow needs one — it's the entry point |
| **Conversation** | AI asks questions and collects information from the caller | When you need to gather data (name, email, issue, etc.) |
| **Condition** | Routes the flow based on a true/false check | Branching logic — "if billing issue, go left; if sales inquiry, go right" |
| **End Call** | Speaks a closing message and hangs up | When the call is complete |

#### Example — Conversation Node Setup

**Prompt:**
```
Ask the caller for their name, phone number, and what type of appointment 
they'd like. Be friendly and confirm each piece of information.
```

**Variables to Extract:** `caller_name, caller_phone, appointment_type`

**Max Turns:** `5` (the conversation will move on after 5 back-and-forths)

#### Example — Condition Node Setup

**Expression:** `result.available == true`

This checks if the previous step (like a calendar availability check) returned a successful result. The flow branches into **Yes** (available) and **No** (not available) paths.

### Telephony Nodes

| Node | What It Does | When to Use |
|------|-------------|-------------|
| **Transfer Call** | Forwards the call to a human | When AI can't resolve the issue, VIP callers, emergencies |
| **Voicemail Detect** | Detects if a voicemail machine answered (for outbound calls) | Outbound calling campaigns |

#### Example — Transfer Call Setup

- **Transfer Number:** `+14155559999`
- **Transfer Message:** "Let me connect you with our billing specialist. One moment please."
- **Whisper Message:** "Incoming call from {{caller_name}} about {{issue_type}}" *(this is spoken to the human agent, not the caller)*
- **Transfer Type:** `Warm` (AI stays on the line during handoff) or `Cold` (AI disconnects)

### Communication Nodes

| Node | What It Does | When to Use |
|------|-------------|-------------|
| **Send SMS** | Sends a text message via Twilio | Appointment confirmations, follow-ups |
| **Send Email** | Sends an email | Detailed follow-ups, order confirmations |
| **Notification** | Sends an alert to Slack, email, or webhook | Internal team notifications |
| **WhatsApp** | Sends a WhatsApp message | International customers, richer media |
| **Discord** | Posts to a Discord channel | Team notifications, dev alerts |
| **MS Teams** | Posts to a Microsoft Teams channel | Enterprise team notifications |
| **SendGrid** | Sends transactional or marketing emails | Professional email sending |

#### Example — Send SMS Setup

- **To Number:** `{{caller_phone}}`
- **Message Body:**
  ```
  Hi {{caller_name}}! Your appointment is confirmed for {{preferred_date}} 
  at Sunrise Dental. Reply CANCEL to reschedule. Questions? Call us at (415) 555-1234.
  ```

### Integration Nodes — Scheduling

| Node | What It Does | Actions Available |
|------|-------------|-------------------|
| **Google Calendar** | Manage Google Calendar events | Create Event, List Events, Check Availability, Update, Delete |
| **Cal.com** | Open-source scheduling | Get Availability, Create Booking, Cancel Booking |
| **Calendly** | Enterprise scheduling | Get Availability, Schedule Meeting, Cancel Event, List Events |

#### Example — Google Calendar "Create Event"

- **Integration:** Select your connected Google Calendar
- **Action:** `Create Event`
- **Event Summary:** `Appointment with {{caller_name}}`
- **Date:** `{{preferred_date}}`

### Integration Nodes — CRM (Customer Relationship Management)

| Node | What It Does | Actions Available |
|------|-------------|-------------------|
| **Salesforce** | #1 enterprise CRM | Create Lead, Update Lead, Create Contact, Create Opportunity, Search Records, Log Activity |
| **Pipedrive** | Sales-focused CRM | Create Person, Create Deal, Update Deal, Add Note, Search Contacts |
| **GoHighLevel** | All-in-one CRM | Create Contact, Update Contact, Create Opportunity, Add Note, Add Tag |
| **HubSpot** | Marketing + CRM | Via webhook (custom API calls) |

#### Example — Salesforce "Create Lead"

After the AI collects caller info in a Conversation node:

- **Integration:** Select your Salesforce integration
- **Action:** `Create Lead`
- **Name:** `{{caller_name}}`
- **Phone:** `{{caller_phone}}`
- **Email:** `{{caller_email}}`
- **Source:** `VOIA AI Inbound Call`

What happens: A new Lead appears in your Salesforce dashboard automatically.

### Integration Nodes — Customer Support

| Node | What It Does | Actions Available |
|------|-------------|-------------------|
| **Zendesk** | Support ticketing | Create Ticket, Update Ticket, Add Comment, Search Tickets, Get Status |
| **Intercom** | Customer messaging | Create Contact, Send Message, Create Conversation, Add Tag, Search |
| **Freshdesk** | Helpdesk | Create Ticket, Update Ticket, Add Note, List Tickets, Search |

#### Example — Zendesk "Create Ticket"

- **Integration:** Select your Zendesk integration
- **Action:** `Create Ticket`
- **Subject:** `Call from {{caller_name}} — {{issue_type}}`
- **Description:** `Phone: {{caller_phone}}\nSummary: {{transcript}}`
- **Priority:** `Medium` (or `High` / `Urgent` based on conditions)

### Integration Nodes — E-Commerce & Payments

| Node | What It Does | Actions Available |
|------|-------------|-------------------|
| **Stripe** | Payment processing | Create Payment Link, Create Invoice, Lookup Customer, Create Customer, Check Status |
| **Shopify** | E-commerce platform | Get Order Status, Search Orders, Get Product Info, Lookup Customer, Create Draft Order |

#### Example — Shopify "Get Order Status"

When a customer calls asking "Where's my order?":

- **Action:** `Get Order Status`  
- **Order ID:** `{{order_number}}` (extracted from the conversation)

The AI retrieves the order details and tells the caller: *"Your order #1042 shipped on Tuesday and is expected to arrive by Friday."*

#### Example — Stripe "Create Payment Link"

For collecting payments over the phone:

- **Action:** `Create Payment Link`
- **Amount:** `5000` (= $50.00, in cents)
- **Product Name:** `Initial Consultation Fee`

The generated payment link is sent via SMS to the caller.

### Integration Nodes — Productivity

| Node | What It Does | Actions Available |
|------|-------------|-------------------|
| **Notion** | Knowledge management | Create Page, Add to Database, Search Pages, Append Block |
| **Airtable** | Flexible databases | Create Record, Update Record, Search Records, List Records |

#### Example — Airtable "Create Record"

Log every call automatically:

- **Action:** `Create Record`
- **Title:** `Call — {{caller_name}}`
- **Content (JSON):**
  ```json
  {
    "Name": "{{caller_name}}",
    "Phone": "{{caller_phone}}",
    "Date": "{{call_date}}",
    "Summary": "{{transcript}}"
  }
  ```

### Integration Nodes — Project Management

| Node | What It Does | Actions Available |
|------|-------------|-------------------|
| **Jira** | Atlassian issue tracking | Create Issue, Update Issue, Add Comment, Transition Issue, Search |
| **Linear** | Modern issue tracking | Create Issue, Update Issue, Add Comment, Search Issues |

#### Example — Jira "Create Issue"

When a caller reports a bug or IT issue:

- **Action:** `Create Issue`
- **Title:** `[CALL] {{issue_type}} — reported by {{caller_name}}`
- **Description:** `{{transcript}}`
- **Priority:** `High`

### Integration Nodes — Automation

| Node | What It Does | Actions Available |
|------|-------------|-------------------|
| **Make (Integromat)** | Workflow automation | Trigger Scenario, Send Data |
| **Zapier** | App connector | Via webhook trigger |
| **Webhook** | Custom HTTP calls | Any API endpoint |

### AI & Knowledge Nodes

| Node | What It Does | When to Use |
|------|-------------|-------------|
| **Knowledge Base** | Search your company's documents for answers | FAQ, policy lookups, product info |
| **AI Process** | Run custom LLM processing on data | Summarize transcripts, classify intents, generate responses |

#### Example — Knowledge Base Setup

Upload your company FAQ, pricing sheet, or policy documents. Then:

- **Search Query:** `{{issue_description}}`
- **Max Results:** `3`

When a caller asks "What's your return policy?", the AI searches your knowledge base and answers with the actual policy text.

### Utility Nodes

| Node | What It Does | When to Use |
|------|-------------|-------------|
| **Delay** | Pauses the workflow for X seconds | Wait for API responses, pacing |
| **API Request** | Make any HTTP request | Custom APIs, internal services |

---

## 5. Integrations — Connecting Your Business Tools

### What Are Integrations?

Integrations are the connections between VOIA and your other business tools. Once connected, your AI agent can read and write data to those tools during phone calls.

### Available Integrations (28 Total)

| Category | Integrations | Use Case |
|----------|-------------|----------|
| **Scheduling** | Google Calendar, Cal.com, Calendly | Book appointments, check availability |
| **CRM** | Salesforce, Pipedrive, GoHighLevel, HubSpot | Create leads, track deals, manage contacts |
| **Support** | Zendesk, Intercom, Freshdesk | Create tickets, update cases, send messages |
| **Payments** | Stripe | Create invoices, payment links, check status |
| **E-Commerce** | Shopify | Look up orders, products, customers |
| **Communication** | SMS, Email, Slack, Discord, MS Teams, WhatsApp, SendGrid | Send messages and notifications |
| **Productivity** | Google Sheets, Notion, Airtable | Log data, create records, search databases |
| **Automation** | Webhook, Zapier, Make | Connect to any API or automation platform |
| **AI** | Knowledge Base | Search company documents for answers |
| **Project Mgmt** | Jira, Linear | Create issues, track bugs, manage projects |

### How to Add an Integration

1. Go to **Integrations** in the sidebar
2. Click **+ Add Integration**
3. Select the **type** (e.g., "Salesforce")
4. Enter a **name** (e.g., "My Salesforce")
5. Enter your **credentials** as JSON:

   ```json
   {
     "api_key": "your-api-key-here",
     "instance_url": "https://yourcompany.salesforce.com"
   }
   ```

6. Click **Save**
7. Click **Test** to verify the connection

### Credential Format by Integration

#### Scheduling

**Google Calendar:**
```json
{
  "calendar_id": "primary",
  "service_account_key": "{ ... your service account JSON ... }"
}
```

**Calendly:**
```json
{
  "api_key": "your-calendly-api-token",
  "organization_uri": "https://api.calendly.com/organizations/YOUR_ORG_ID",
  "event_type_uri": "https://api.calendly.com/event_types/YOUR_TYPE_ID"
}
```

**Cal.com:**
```json
{
  "api_key": "your-calcom-api-key",
  "event_type_id": 12345
}
```

#### CRM

**Salesforce:**
```json
{
  "api_key": "your-access-token",
  "instance_url": "https://yourcompany.salesforce.com",
  "api_version": "v59.0"
}
```

**Pipedrive:**
```json
{
  "api_key": "your-pipedrive-api-token",
  "base_url": "https://api.pipedrive.com/v1"
}
```

**GoHighLevel:**
```json
{
  "api_key": "your-ghl-api-key",
  "base_url": "https://rest.gohighlevel.com/v1",
  "location_id": "your-location-id"
}
```

#### Support

**Zendesk:**
```json
{
  "api_key": "your-zendesk-api-token",
  "subdomain": "https://yourcompany.zendesk.com",
  "default_priority": "normal"
}
```

**Freshdesk:**
```json
{
  "api_key": "your-freshdesk-api-key",
  "domain": "https://yourcompany.freshdesk.com"
}
```

**Intercom:**
```json
{
  "api_key": "your-intercom-access-token",
  "base_url": "https://api.intercom.io"
}
```

#### Payments

**Stripe:**
```json
{
  "api_key": "sk_live_your-stripe-secret-key",
  "currency": "usd"
}
```

#### E-Commerce

**Shopify:**
```json
{
  "api_key": "your-shopify-admin-api-access-token",
  "shop_domain": "yourstore.myshopify.com",
  "api_version": "2024-01"
}
```

#### Communication

**SendGrid:**
```json
{
  "api_key": "SG.your-sendgrid-api-key",
  "from_email": "noreply@yourcompany.com",
  "from_name": "Your Company"
}
```

**Discord:**
```json
{
  "webhook_url": "https://discord.com/api/webhooks/YOUR_WEBHOOK_URL",
  "bot_name": "VOIA Bot"
}
```

**WhatsApp:**
```json
{
  "api_key": "your-whatsapp-business-token",
  "phone_number_id": "your-phone-number-id"
}
```

**Microsoft Teams:**
```json
{
  "webhook_url": "https://your-teams-incoming-webhook-url"
}
```

#### Productivity

**Notion:**
```json
{
  "api_key": "secret_your-notion-integration-token",
  "default_database_id": "your-database-id"
}
```

**Airtable:**
```json
{
  "api_key": "pat.your-airtable-personal-access-token",
  "base_id": "appXXXXXXXX",
  "default_table": "Calls"
}
```

#### Project Management

**Jira:**
```json
{
  "api_key": "your-jira-api-token",
  "email": "you@company.com",
  "base_url": "https://yourcompany.atlassian.net",
  "project_key": "PROJ"
}
```

**Linear:**
```json
{
  "api_key": "lin_api_your-token",
  "team_id": "your-team-id"
}
```

#### Automation

**Make (Integromat):**
```json
{
  "webhook_url": "https://hook.us1.make.com/your-webhook-id"
}
```

**Zapier:**
```json
{
  "webhook_url": "https://hooks.zapier.com/hooks/catch/YOUR_HOOK"
}
```

---

## 6. Pre-Built Templates — Ready-to-Use Workflows

VOIA includes **21 ready-to-use workflow templates** across multiple industries. Templates give you a working workflow in seconds — just import, connect your integrations, and go.

### How to Use a Template

1. Go to **Workflows** → click **+ New Workflow**
2. Click the **Templates** button (📄 icon)
3. Browse templates by category
4. Click a template to preview it
5. Click **Import** — the workflow is loaded into the visual editor
6. **Customize** the nodes as needed (update phone numbers, prompts, etc.)
7. Click **Save**

### All Templates

#### 📋 Scheduling

| Template | Description | Best For |
|----------|-------------|----------|
| **Appointment Booking** | Collects caller info, checks availability, books appointment, sends SMS confirmation | Medical offices, salons, consultants |
| **Interview Scheduling** | Screens candidates, collects info, schedules interviews | Recruitment, HR departments |
| **Event Registration** | Registers callers for events/webinars, sends confirmations, adds to calendar | Event organizers, marketing teams |
| **Product Demo Scheduling** | Qualifies prospects and schedules demos with the right sales rep | SaaS companies, B2B sales |

#### 🏥 Healthcare

| Template | Description | Best For |
|----------|-------------|----------|
| **Healthcare Reminder** | Calls patients about upcoming appointments, offers rescheduling or cancellation | Hospitals, clinics, medical practices |
| **Dental Receptionist** | Full AI receptionist for dental offices — appointments, insurance verification, emergency triage | Dental offices |

#### 🏠 Real Estate & Hospitality

| Template | Description | Best For |
|----------|-------------|----------|
| **Real Estate Inquiry** | Handles property listing calls, collects buyer preferences, schedules viewings | Real estate agencies |
| **Restaurant Reservation** | Books tables, handles dietary requirements, confirms via SMS | Restaurants, bistros |
| **Hotel Concierge** | Room inquiries, availability, booking processing, confirmation | Hotels, resorts |

#### 🛒 E-Commerce & Retail

| Template | Description | Best For |
|----------|-------------|----------|
| **Order Status** | Looks up order status via API and provides real-time updates | Online stores, fulfillment |
| **E-Commerce Returns** | Handles returns — order lookup, eligibility check, return label generation | E-commerce, retail |

#### 💰 Finance & Payments

| Template | Description | Best For |
|----------|-------------|----------|
| **Payment Collection** | Outbound calls for outstanding payments with payment link generation | Collections, billing |
| **Loan Pre-Qualification** | Collects financial info, runs eligibility checks, connects with loan officers | Banks, lenders, fintechs |
| **Subscription Management** | Handles subscription inquiries — upgrades, downgrades, cancellations with retention offers | SaaS, subscription services |

#### 🎧 Support & IT

| Template | Description | Best For |
|----------|-------------|----------|
| **Customer Support Triage** | Greets caller, searches knowledge base, routes to department or resolves with AI | Call centers, customer service |
| **IT Helpdesk** | Categorizes IT issues, checks knowledge base, creates tickets in Jira/Zendesk, escalates | IT departments, MSPs |
| **After-Hours Handler** | Handles calls outside business hours with voicemail and callback scheduling | Any business |

#### 📊 Sales

| Template | Description | Best For |
|----------|-------------|----------|
| **Lead Qualification** | Qualifies leads by collecting info, scoring, routing to CRM and notifying sales team | B2B sales, marketing |

#### 🗳️ General

| Template | Description | Best For |
|----------|-------------|----------|
| **Survey & Feedback** | Post-interaction surveys with NPS scoring and follow-up for detractors | Customer experience teams |

#### 🚨 Emergency

| Template | Description | Best For |
|----------|-------------|----------|
| **Emergency Dispatch** | Triages emergency calls, collects location, routes to appropriate responders | Emergency services, security |

#### 🛡️ Insurance

| Template | Description | Best For |
|----------|-------------|----------|
| **Insurance Claims** | Collects claim information, creates tickets, routes to adjusters | Insurance companies |

---

## 7. Real-World Use Cases (Step-by-Step)

### Use Case 1: Dental Office AI Receptionist

**Scenario**: You run a dental practice and want an AI to handle appointment calls 24/7, freeing up your front desk staff.

**Step-by-step setup:**

1. **Create an Agent:**
   - Name: `Dental Receptionist`
   - System Prompt:
     ```
     You are a warm, professional receptionist for Bright Smiles Dental.
     Your name is Emma. 
     
     Office Info:
     - Hours: Mon-Fri 8am-6pm, Saturday 9am-2pm
     - Address: 456 Oak Avenue, Suite 100
     - We accept Delta Dental, Cigna, Aetna, and most PPO plans
     - Emergency line: (555) 999-0000
     
     Services: General checkups, cleanings, fillings, crowns, 
     whitening, invisalign, root canals, emergency dental care
     
     Always be empathetic if the caller is in pain. For dental 
     emergencies, offer to connect to the emergency line immediately.
     ```

2. **Add Integrations:**
   - **Google Calendar** — to check and book appointments
   - **SendGrid** — for confirmation emails
   
3. **Import the "Dental Receptionist" Template:**
   - Go to Workflows → New → Templates → select "Dental Receptionist"
   
4. **Customize the workflow:**
   - Update the **Conversation** nodes with your specific services and insurance questions
   - Connect the **Google Calendar** node to your integration
   - Set the **Transfer Call** number to your emergency line
   - Update **SMS** templates with your clinic details

5. **Connect phone number:**
   - Assign your Twilio number to the agent

6. **Test:** Call the number yourself and walk through a booking scenario.

**Result:** Your AI handles ~80% of appointment calls automatically. Emergencies are transferred to the emergency line. After-hours callers get voicemail with callback scheduling.

---

### Use Case 2: E-Commerce Order Support with Shopify + Zendesk

**Scenario**: Your online store gets 200+ calls a day asking "Where's my order?" — you want AI to handle these automatically.

**Step-by-step setup:**

1. **Create an Agent:**
   - Name: `Order Support Bot`
   - System Prompt:
     ```
     You are a friendly customer support agent for TechGear Pro, 
     an online electronics store. Your name is Alex.
     
     Be empathetic and efficient. Always start by asking for the 
     customer's order number or email address.
     
     For returns, check if the order is within our 30-day return window.
     For damaged items, escalate to a human agent immediately.
     ```

2. **Add Integrations:**
   - **Shopify** — to look up orders
   - **Zendesk** — to create support tickets for complex issues

3. **Build the Workflow:**

   ```
   Trigger: "order", "shipping", "delivery", "tracking", "return", "refund"
   
   → Conversation: "Ask for order number or email"
     (Extract: order_number, customer_email)
   
   → Shopify: Get Order Status (order_id: {{order_number}})
   
   → Condition: result.fulfillment_status == "shipped"
     ├── Yes → Conversation: "Your order shipped on {date}, tracking: {number}"
     │         → End Call: "Anything else I can help with?"
     │
     └── No → Condition: Is this a return request?
              ├── Yes → Zendesk: Create Ticket (subject: "Return Request #{{order_number}}")
              │         → Send SMS: "We've started your return process. Check email for details."
              │         → End Call
              │
              └── No → Transfer Call to human agent
   ```

4. **Test with a real order number.**

**Result:** 70-80% of order status calls are fully automated. Returns create tickets automatically. Complex issues get transferred with full context.

---

### Use Case 3: B2B Lead Qualification with Salesforce + Slack

**Scenario**: Your sales team gets inbound calls. You want AI to qualify leads and only transfer hot leads to sales reps.

**Step-by-step setup:**

1. **Create an Agent:**
   - Name: `Sales Qualifier`
   - System Prompt:
     ```
     You are a professional sales development representative for 
     CloudSync Solutions, a B2B SaaS company. Your name is Michael.
     
     Your job is to qualify inbound leads by asking about:
     1. Their company name and size (how many employees?)
     2. Their current solution/pain points
     3. Their timeline (when do they need a solution?)
     4. Their budget range
     5. Who is the decision maker?
     
     Be consultative, not pushy. If they have fewer than 10 employees,
     direct them to our self-service plan at cloudsyncsolutions.com/pricing.
     ```

2. **Add Integrations:**
   - **Salesforce** — to create leads
   - **Slack** — to notify the sales team
   - **Google Calendar** — to book demo meetings

3. **Build the Workflow:**

   ```
   Trigger: "pricing", "demo", "interested", "buy", "sales"
   
   → Conversation: Qualify the lead
     (Extract: company_name, company_size, pain_points, timeline, budget, decision_maker)
   
   → Condition: company_size > 10
     ├── Yes (Qualified Lead):
     │   → Salesforce: Create Lead
     │     (name: {{caller_name}}, company: {{company_name}}, phone: {{caller_phone}})
     │   → Slack Notification: "🔥 Hot lead: {{caller_name}} from {{company_name}} 
     │     ({{company_size}} employees, budget: {{budget}}, timeline: {{timeline}})"
     │   → Google Calendar: Create Event
     │     (Summary: "Demo call with {{company_name}}")
     │   → End Call: "Great news! I've scheduled a demo for you..."
     │
     └── No (Small Company):
         → Send Email: Self-service plan info
         → End Call: "I've sent you our pricing details..."
   ```

**Result:** Sales reps only get calls from qualified leads. Small businesses get automated help. Every lead is logged in Salesforce with full context.

---

### Use Case 4: IT Helpdesk with Jira + Knowledge Base

**Scenario**: Your internal IT team gets flooded with "my password is locked" and "VPN isn't working" calls.

1. **Create an Agent** with IT support persona
2. **Add Integrations:** Jira (for tickets), Knowledge Base (for self-service answers)
3. **Import "IT Helpdesk" template**
4. **Upload your IT docs** to the Knowledge Base:
   - Password reset procedures
   - VPN troubleshooting guide
   - Software request forms

5. **The workflow:**
   ```
   Trigger: "password", "VPN", "computer", "email not working", "IT help"
   
   → Conversation: "What's the issue?"
   → Knowledge Base: Search for solution
   → Condition: Found a KB article?
     ├── Yes → AI Process: Summarize the solution in simple terms
     │         → Conversation: Walk them through it
     │         → End Call
     └── No  → Jira: Create Issue (priority based on urgency)
              → Notification: Slack alert to IT team
              → Transfer: Connect to IT support
   ```

**Result:** Common issues (password resets, VPN) are resolved automatically. Unique issues get Jira tickets with full context.

---

## 8. Template Variables — Dynamic Data in Your Workflows

Template variables let you insert real-time data into your messages, API calls, and prompts. Use them anywhere by wrapping the variable name in double curly braces: `{{variable_name}}`.

### Built-In Variables

| Variable | Description | Example Output |
|----------|-------------|----------------|
| `{{caller_name}}` | Caller's name (extracted from conversation) | "John Smith" |
| `{{caller_phone}}` | Caller's phone number | "+14155551234" |
| `{{caller_email}}` | Caller's email (if collected) | "john@email.com" |
| `{{agent_name}}` | Name of the AI agent | "Reception Bot" |
| `{{transcript}}` | Full call transcript so far | "Caller: Hi, I'd like to book..." |
| `{{call_duration}}` | How long the call has been | "3m 45s" |
| `{{current_date}}` | Today's date | "2026-03-12" |
| `{{current_time}}` | Current time | "14:30" |
| `{{next_business_day}}` | Next weekday date | "2026-03-13" |
| `{{issue_type}}` | Detected issue category | "billing" |

### Custom Variables (from Conversation Nodes)

Any variable you list in a Conversation node's **"Variables to Extract"** becomes available in subsequent nodes.

**Example:**
- Conversation node extracts: `preferred_date, appointment_type, insurance_provider`
- In a subsequent Send SMS node, use: `Your {{appointment_type}} appointment is confirmed for {{preferred_date}}.`

### Step Results

Results from previous workflow steps are available via `{{step_N_result}}`:

- `{{step_1_result}}` — Result from the first workflow step
- `{{step_2_result}}` — Result from the second step

This is useful for passing API response data between nodes.

### Using Variables — Examples

**SMS Confirmation:**
```
Hi {{caller_name}}! Your {{appointment_type}} is confirmed for 
{{preferred_date}}. Reply STOP to unsubscribe.
```

**Jira Ticket Description:**
```
Caller: {{caller_name}} ({{caller_phone}})
Date: {{current_date}} at {{current_time}}
Issue: {{issue_type}}
Transcript: {{transcript}}
```

**Slack Notification:**
```
📞 New call from {{caller_name}} ({{caller_phone}})
Duration: {{call_duration}}
Type: {{issue_type}}
Summary: {{transcript}}
```

---

## 9. Integration Setup Guides

### Google Calendar — Full Setup

1. **Google Cloud Console:**
   - Create a project at [console.cloud.google.com](https://console.cloud.google.com)
   - Enable the **Google Calendar API**
   - Create a **Service Account** → download the JSON key file

2. **Share your calendar:**
   - Open Google Calendar → Settings → your calendar
   - Under "Share with specific people" → add the service account email
   - Give it **"Make changes to events"** permission

3. **Add to VOIA:**
   - Go to Integrations → + Add → Google Calendar
   - Paste the service account JSON as credentials
   - Set `calendar_id` to `primary` (or your specific calendar ID)

4. **Test:** Click the Test button — you should see "Connection successful"

### Salesforce — Full Setup

1. **Salesforce Setup:**
   - Go to Setup → Apps → App Manager → New Connected App
   - Enable OAuth → select "Full access" scope
   - Note your Consumer Key and Consumer Secret

2. **Get an Access Token:**
   - Use Salesforce's OAuth flow to get an access token
   - Or use username-password flow for server-to-server

3. **Add to VOIA:**
   - Integration type: Salesforce
   - Credentials:
     ```json
     {
       "api_key": "your-access-token",
       "instance_url": "https://yourcompany.salesforce.com"
     }
     ```

4. **Test:** Creates a test lead in your Salesforce dev org

### Stripe — Full Setup

1. **Stripe Dashboard:**
   - Go to [dashboard.stripe.com](https://dashboard.stripe.com)
   - Developers → API Keys → copy your **Secret Key** (starts with `sk_`)

2. **Add to VOIA:**
   - Integration type: Stripe
   - Credentials:
     ```json
     {
       "api_key": "sk_live_your_secret_key",
       "currency": "usd"
     }
     ```

3. **Use in workflows:**
   - **Create Payment Link** → sends a pay link to the caller via SMS
   - **Create Invoice** → generates and sends a Stripe invoice
   - **Check Payment Status** → look up if a payment was completed

### Shopify — Full Setup

1. **Shopify Admin:**
   - Go to Settings → Apps and sales channels → Develop apps
   - Create app → configure Admin API scopes:
     - `read_orders`, `read_products`, `read_customers`
   - Install app → copy the **Admin API access token**

2. **Add to VOIA:**
   ```json
   {
     "api_key": "shpat_your_access_token",
     "shop_domain": "your-store.myshopify.com",
     "api_version": "2024-01"
   }
   ```

3. **Common workflow:** Caller asks "Where's my order?" → Shopify lookup → AI reads status to caller

---

## 10. Advanced Workflow Patterns

### Pattern 1: Multi-Branch Routing

Route callers to different paths based on what they need:

```
Trigger: Any call
→ Conversation: "How can I help you today?"
  (Extract: intent)
→ Condition: intent == "billing"
  ├── Yes → Transfer to billing team
  └── No → Condition: intent == "support" 
           ├── Yes → Knowledge Base lookup → AI resolves
           └── No → Condition: intent == "sales"
                    ├── Yes → Lead qualification workflow
                    └── No → General info → End Call
```

### Pattern 2: Escalation with Context

Pass full context when transferring to a human:

```
Trigger → Conversation (collect info) → Knowledge Base (try to resolve)
→ Condition: resolved?
  ├── Yes → End Call
  └── No → Zendesk: Create Ticket
        → Transfer Call
            Whisper: "Caller {{caller_name}} has a {{issue_type}} issue. 
            AI tried KB article but couldn't resolve. Ticket #{{ticket_id}} created."
```

### Pattern 3: Outbound Campaign Follow-Up

For outbound calling with follow-up actions:

```
Trigger: Outbound call starts
→ Voicemail Detect
  ├── Machine → Leave voicemail message → End
  └── Human → Conversation: deliver message
              → Condition: interested?
                ├── Yes → Google Calendar: Book meeting
                │         → Salesforce: Update lead status
                │         → Send Email: calendar invite
                └── No → Salesforce: Mark as "Not Interested"
                         → End Call
```

### Pattern 4: Data Pipeline

Chain multiple integrations in sequence:

```
Trigger → Conversation (collect data)
→ Airtable: Create Record (log the call)
→ Salesforce: Create Lead (CRM entry)  
→ Slack: Notify team
→ SendGrid: Send welcome email to caller
→ Google Calendar: Book follow-up meeting
→ End Call
```

### Pattern 5: Error Handling with Conditions

Build robust workflows with fallbacks:

```
→ Shopify: Get Order Status
→ Condition: result.success == true
  ├── Yes → Tell caller their order status
  └── No → Conversation: "I'm having trouble finding that order. 
           Can you double-check the order number?"
           → Shopify: Get Order Status (retry)
           → Condition: result.success == true
             ├── Yes → Share status
             └── No → Transfer to human agent
```

---

## 11. Troubleshooting & FAQ

### General

**Q: My AI sounds robotic / unnatural.**
> A: Improve your system prompt. Give the AI a name, personality, and specific guidelines about tone. Use your agent's voice settings to pick a more natural-sounding voice like `aura-asteria-en`.

**Q: My agent doesn't trigger the workflow.**
> A: Check your **Trigger Phrases** in the workflow. The phrases must match what the caller naturally says. Use multiple variations: "book", "appointment", "schedule", "reserve".

**Q: The AI collects wrong information.**
> A: Refine your Conversation node prompt. Be specific: "Ask for their FULL name (first and last)" instead of just "Ask for their name". Add examples of what you expect.

### Integrations

**Q: My integration test shows "configured" but not "connected".**
> A: Most integrations only validate credentials format, not live connectivity. Try the integration in an actual workflow to verify it works end-to-end.

**Q: Salesforce integration returns 401 errors.**
> A: Your access token may have expired. Salesforce tokens expire after ~2 hours. Use a refresh token flow, or generate a new token.

**Q: Stripe payments aren't going through.**
> A: Make sure you're using your **live** API key (starts with `sk_live_`), not your test key (`sk_test_`). Also verify amounts are in **cents** (5000 = $50.00).

**Q: WhatsApp messages aren't sending.**
> A: Meta requires approved message templates for business-initiated messages. Verify your WhatsApp Business API template is approved.

### Workflows

**Q: My workflow runs but nothing happens.**
> A: Check the **Call Logs** page for the call. Each step's result is logged. Common issue: the integration is configured but the API key is wrong.

**Q: Condition nodes always go to "No".**
> A: Check your expression syntax. Use `result.success == true` (with `==`), not `=`. Make sure the variable name matches exactly what the previous step returns.

**Q: Template variables show as `{{caller_name}}` literally.**
> A: The variable wasn't extracted. Ensure your Conversation node lists the variable in **"Variables to Extract"** and the AI prompt asks for that specific information.

---

## 12. Developer Reference

### API Endpoints

All endpoints require authentication (JWT token in `Authorization: Bearer <token>` header).

#### Workflows

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/workflows/templates` | List all workflow templates |
| `GET` | `/api/workflows` | List user's workflows |
| `POST` | `/api/workflows` | Create a workflow |
| `GET` | `/api/workflows/{id}` | Get workflow details |
| `PUT` | `/api/workflows/{id}` | Update a workflow |
| `DELETE` | `/api/workflows/{id}` | Delete a workflow |
| `POST` | `/api/workflows/{id}/execute` | Execute a workflow |

#### Integrations

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/integrations/types` | List all integration types with config schemas |
| `GET` | `/api/integrations` | List user's integrations |
| `POST` | `/api/integrations` | Create an integration |
| `GET` | `/api/integrations/{id}` | Get integration details |
| `PUT` | `/api/integrations/{id}` | Update an integration |
| `DELETE` | `/api/integrations/{id}` | Delete an integration |
| `POST` | `/api/integrations/{id}/test` | Test integration connection |

### Creating a Workflow via API

```bash
curl -X POST http://localhost:3000/api/workflows \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Appointment Booking",
    "description": "Book appointments from inbound calls",
    "trigger_phrases": ["book", "appointment", "schedule"],
    "agent_id": 1,
    "steps": [
      {
        "step_number": 1,
        "integration_id": 0,
        "action": "conversation",
        "params": {
          "prompt": "Ask for name, date, and type of appointment",
          "variables_to_extract": ["caller_name", "preferred_date", "appointment_type"]
        }
      },
      {
        "step_number": 2,
        "integration_id": 5,
        "action": "create_event",
        "params": {
          "summary": "{{appointment_type}} — {{caller_name}}",
          "date": "{{preferred_date}}"
        }
      },
      {
        "step_number": 3,
        "integration_id": 0,
        "action": "send_sms",
        "params": {
          "to": "{{caller_phone}}",
          "body": "Your {{appointment_type}} is confirmed for {{preferred_date}}."
        }
      }
    ]
  }'
```

### Creating an Integration via API

```bash
curl -X POST http://localhost:3000/api/integrations \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "service_type": "salesforce",
    "name": "My Salesforce CRM",
    "credentials": {
      "api_key": "your-sf-access-token",
      "instance_url": "https://yourcompany.salesforce.com",
      "api_version": "v59.0"
    }
  }'
```

### Adding Custom Node Types (Developer Guide)

To add a new integration node type to VOIA:

1. **Backend — database.py**: Add the type to `VALID_INTEGRATION_TYPES`
2. **Backend — integration_routes.py**: Add type definition in `/types` endpoint with `config_schema` and `capabilities`
3. **Backend — integration_routes.py**: Add test handler in `/test` endpoint
4. **Backend — executor.py**: Add execution handler in `_execute_action()` dispatcher and implement the handler method
5. **Frontend — WorkflowNodes.tsx**: Add entry to `NODE_TYPES_CONFIG` with icon, colors, and category
6. **Frontend — NodeConfigPanel.tsx**: Add actions to `INTEGRATION_ACTIONS` and add the nodeType to the integration panel condition
7. **Frontend — workflows/[id]/page.tsx**: Add to `addableTypes` array and `guessNodeType` function
8. **Frontend — integrations/page.tsx**: Add icon and color mappings

### Architecture Overview

```
┌──────────────────────┐     ┌──────────────────────┐
│   Next.js Frontend   │────▶│   FastAPI Backend     │
│   (Port 3001)        │     │   (Port 3000)         │
│                      │     │                       │
│  • Dashboard         │     │  • Auth (Google OAuth) │
│  • Agent Editor      │     │  • Agent CRUD         │
│  • Workflow Editor   │     │  • Workflow Engine     │
│  • Integrations      │     │  • Integration Exec   │
│  • Call Logs         │     │  • Call Management    │
└──────────────────────┘     └────────┬──────────────┘
                                      │
                    ┌─────────────────┼─────────────────┐
                    │                 │                  │
              ┌─────▼─────┐   ┌──────▼──────┐   ┌──────▼──────┐
              │  Twilio    │   │  Deepgram   │   │   Groq      │
              │ (Phone)    │   │ (STT + TTS) │   │   (LLM)     │
              │            │   │             │   │             │
              │ Inbound &  │   │ Nova-2 STT  │   │ Llama 3.3  │
              │ Outbound   │   │ Aura TTS    │   │ 70b         │
              └────────────┘   └─────────────┘   └─────────────┘
```

---

> **Need help?** Check the [FRONTEND_INTEGRATION_GUIDE.md](FRONTEND_INTEGRATION_GUIDE.md) for detailed API documentation, or the [VOIA_DEVELOPER_GUIDE.md](VOIA_DEVELOPER_GUIDE.md) for architecture deep-dives.
