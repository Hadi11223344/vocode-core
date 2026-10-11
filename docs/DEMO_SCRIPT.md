# VOIA MVP Showcase Demo Script

> For the **open-source launch** (Tier 0 playground, 3–5 min), use [LAUNCH_VIDEO_SCRIPT.md](./LAUNCH_VIDEO_SCRIPT.md) and [LAUNCH_CHECKLIST.md](./LAUNCH_CHECKLIST.md) instead.

## Purpose
Use this script to walk through the two showcase flows end to end:

1. Document Verification & Onboarding
2. Dynamic Sales with Live Proposal Generation

## Pre-Demo Checklist

Run through this checklist **30 minutes before** the demo to catch any issues.

### Infrastructure
- [ ] **Backend running** — `curl http://localhost:3000/health` returns 200
- [ ] **Frontend running** — `http://localhost:3001` loads the dashboard
- [ ] **Redis running** — `docker compose exec redis redis-cli ping` returns PONG
- [ ] **Database healthy** — `docker compose exec app alembic current` shows latest migration

### API Keys & Telephony
- [ ] **Twilio keys configured** — `TWILIO_ACCOUNT_SID` and `TWILIO_AUTH_TOKEN` set in `.env`
- [ ] **Twilio phone number** — `TWILIO_PHONE_NUMBER` set and webhook URL points to `https://your-url/inbound_call`
- [ ] **Deepgram key** — `DEEPGRAM_API_KEY` set (required for speech-to-text)
- [ ] **LLM key** — `GROQ_API_KEY` or `OPENAI_API_KEY` set
- [ ] **TTS key** — at least one TTS provider configured (ElevenLabs, Azure, or Cartesia)

### Auth & Integrations
- [ ] **Google OAuth** — `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` set; login works
- [ ] **Google Drive MCP** — integration connected and tested (for Demo 1)
- [ ] **Google Calendar** — integration connected (if showing scheduling features)

### Agent & Content Setup
- [ ] **Demo agent created** — Document Verification agent from template (Demo 1)
- [ ] **Demo agent created** — Sales Proposal agent from template (Demo 2)
- [ ] **Agents tested** — run a playground session for each agent to verify responses
- [ ] **Knowledge base uploaded** — at least one KB document uploaded and indexed
- [ ] **Test call completed** — place one inbound or outbound test call to verify full pipeline

### Demo Data
- [ ] **Seed data loaded** — `python scripts/seed_demo_data.py` run (if available)
- [ ] **Campaign contact list** — at least 3 test contacts loaded for campaign demo
- [ ] **Sample files in Drive** — passport and proof of address samples uploaded (Demo 1)
- [ ] **Workflow created** — a sample workflow is open in the editor tab

### Browser Prep
- [ ] **Dashboard tab open** — live calls view ready
- [ ] **Workflow editor tab open** — on a sample workflow
- [ ] **Agent builder tab open** — ready to show template selection
- [ ] **Clear browser cache** — no stale state from previous sessions
- [ ] **Close unnecessary tabs** — reduce memory/CPU load for smooth 3D rendering

### Fallback Plan
- [ ] **Backup LLM key** — secondary provider configured in case primary is rate-limited
- [ ] **Sample files ready** — local copies in case Drive integration fails
- [ ] **Recorded call** — have a previous call recording ready to show if live call fails

## Demo 1: Document Verification & Onboarding
Time: 4-5 minutes

1. Open the agent wizard.
2. Select the Document Verification template.
3. Point out the recommended tools and the Drive integration option.
4. Create the agent from the template.
5. Start a test call or playground session.
6. Say: "I need to verify my passport and proof of address."
7. Let the agent ask for the document details, search Drive, read the file, and summarize the result.
8. Switch to the live dashboard and point out the action feed.
9. End by confirming the onboarding step and the next follow-up action.

What to emphasize:
- The agent starts from a single prompt/template.
- Drive is only used when the caller actually needs documents.
- Read files are cached so the next turn stays grounded in the same context.

## Demo 2: Dynamic Sales with Live Proposal Generation
Time: 4-5 minutes

1. Open the Sales Proposal template.
2. Show the workflow builder and the node config panel.
3. Use the new Test Node button and a parameter template to quickly validate the node setup.
4. Start a sales call.
5. Say: "I need a proposal for a 12-seat renewal with onboarding included."
6. Let the agent gather requirements and generate the proposal flow.
7. Switch to the live dashboard and point out the tool/action events.
8. If a workflow step is involved, show the node executing and returning results.
9. Close by summarizing the proposal and the next step for the customer.

What to emphasize:
- The workflow path is visible and testable.
- Live monitoring shows tool usage as it happens.
- The sales flow can move from discovery to proposal without leaving the call.

## Suggested Closing Line
"VOIA combines fast agent creation, Drive-aware in-call behavior, workflow automation, and live observability in one system."

## Fallbacks
- If Drive is disconnected, use a prepared sample file so the demo still shows the read path.
- If the live feed is noisy, keep the action panel collapsed until the key moment.
- If the workflow step needs a clean reset, reload the editor and re-run the Test Node action.
