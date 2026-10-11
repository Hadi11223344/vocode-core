# 🚀 VOIA Crash Course 2: Advanced Dynamic Features

If you've read `VOIA_ARCHITECTURE_AND_QUICKSTART.md`, you understand how a basic phone call flows from Twilio -> Database -> Agent Factory -> WebSocket.

But VOIA isn't just a basic answering machine. It has **State**. It remembers callers, and it can take actions during a call. Let's look at exactly how we implemented these advanced features.

---

## 🧠 1. Cross-Call Memory (FR-07)

How does the AI remember that the caller called yesterday and asked about their order?

**The Concept:**
Large Language Models (LLMs) like GPT-4 are stateless. They don't magically remember past API requests. To give the AI "memory", we have to spoon-feed it previous transcripts *before* the call starts.

**The Code (`voice_platform/memory.py`):**

1.  Before the WebSocket connects, the `inbound_call` route in `main.py` looks at the caller's phone number (`From`).
2.  It calls `memory_summary = await get_caller_history_summary(From)`.
3.  Inside `memory.py`, we query the `CallLog` table for past calls matching that phone number, ordered by date.
4.  For the last 3 calls, we grab the `Transcript` rows (what the human said, and what the bot said).
5.  We format this into a string:
    ```text
    === PREVIOUS INTERACTION HISTORY ===
    Call 1 (2024-03-01):
      Human: Where is my order 12345?
      Bot: It shipped yesterday!
    ===================================
    ```
6.  Finally, we take the Agent's base system prompt ("You are a helpful assistant") and literally **append** the memory string to the bottom of it.

When the LLM boots up for the new call, it thinks: *"Ah, I see this person asked about order 12345 yesterday."* 

---

## ⚡ 2. Workflow Injection (FR-08)

Users can define "Workflows" in the dashboard. For example, "If the caller says '*schedule appointment*', trigger the calendar action."

How does the AI know to listen for these specific phrases?

**The Concept:**
Similar to memory, we have to inject these rules into the AI's system prompt before the call starts.

**The Code (`voice_platform/main.py` -> `_get_workflow_context`):**

When the `/inbound_call` route fires, it doesn't just load memory, it also loads workflows:

```python
async def _get_workflow_context(agent_id: int) -> str:
    async with async_session() as session:
        # 1. Fetch all workflows for this specific agent
        result = await session.execute(
            select(Workflow).where(Workflow.agent_id == agent_id)
        )
        workflows = result.scalars().all()

        if not workflows:
            return ""

        # 2. Extract trigger phrases (stored as JSON arrays in DB)
        triggers = []
        for wf in workflows:
            if wf.trigger_phrases:
                triggers.extend(wf.trigger_phrases)

        # 3. Format exact instructions for the LLM
        if triggers:
            return (
                f"\n\n=== STRICT WORKFLOW RULES ===\n"
                f"If the user says anything matching these phrases: {triggers},\n"
                f"you MUST IMMEDIATELY trigger the corresponding action tool.\n"
                f"=================================\n"
            )
        return ""
```

This string is then appended to `agent_config.prompt_preamble`. The key here is **prompt engineering** — by using strong words like `MUST IMMEDIATELY` and `STRICT RULES`, we force the LLM to abandon its standard conversation flow and execute the requested Tool Call instead when it hears those phrases.

---

## 🤖 3. Action Execution (FR-06)

When the AI decides it *does* need to schedule an appointment, how does it actually talk to an external system?

**The Concept:**
We use OpenAI's native "Function Calling" (also known as Tools). We define a JSON schema describing a tool, and if the AI decides to use it, vocode halts the conversation, fires a webhook, and reads the webhook's response back to the AI.

**The Code (`voice_platform/events/call_events.py`):**

Vocode runs an event loop during the call. When the LLM fires a function call, vocode emits an `ActionEvent`. We catch this in our `PersistentEventsManager`:

```python
async def handle_event(self, event: Event):
    # ... other events ...
    
    elif isinstance(event, ActionEvent):
        # The LLM decided to trigger a tool!
        action_input = event.actionInput
        
        # 1. Log it to the database for the user dashboard
        action_log = ActionLog(
            call_log_id=call_record.id,
            action_type=action_input.action_config.type,
            parameters=action_input.params,
            status="pending"
        )
        session.add(action_log)
        
        # 2. Execute the webhook
        # action_executor.py makes the HTTP POST request to the user's external API
        result = await execute_action(action_input)
        
        # 3. Update the DB and let the LLM know the result
        action_log.status = "completed"
        action_log.result = result
        
        # Vocode will automatically read this result back to the LLM
        # so the AI can say "I have successfully booked your appointment!"
```

This makes VOIA incredibly powerful. The user provides a Webhook URL in the dashboard, we wrap it in an OpenAI Function schema, and the STT/LLM/TTS pipeline handles the rest perfectly.

---

## 🛡️ 4. Security & JWT Auth (`middleware/auth_middleware.py`)

The frontend React app talks to our REST API. How do we know who is making the request?

**The Concept:**
Stateless JSON Web Tokens (JWTs).

1.  When a user signs in with Google on the frontend, Google gives them an `id_token`.
2.  The frontend sends that token to our `POST /api/auth/google` route (`auth.py`).
3.  We verify the token with Google to prove the user owns that email.
4.  If valid, we create an entry in the `User` database table.
5.  We then generate **our own** JWT token containing the user's database `id` and `role` ("admin" or "user").
6.  The frontend saves this token and attaches it to every future API request:
    `Authorization: Bearer <token>`

**The Code (`voice_platform/middleware/auth_middleware.py`):**

To protect an API route, we use FastAPI's dependency injection system:

```python
# auth_middleware.py
async def get_current_user(token: str = Depends(oauth2_scheme), session=Depends(get_session)):
    try:
        # 1. Decode the token using our secret key
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        user_id = payload.get("sub")
        
        # 2. Fetch the user from the database
        user = await session.get(User, int(user_id))
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
            
        return user
        
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

# In any route file (e.g. api/agent_routes.py)
@router.get("/my_agents")
async def get_agents(current_user: User = Depends(get_current_user)):
    # This route will 401 Unauthorized if the token is missing/invalid.
    # If successful, `current_user` is instantly available as a Python object!
    return await db.query(Agent).filter(Agent.user_id == current_user.id)
```

By ensuring that `api_routes` only return data matching `current_user.id`, we guarantee that users can never see or modify each other's Voice Agents, even though they share the exact same FastAPI endpoints.

## 🐞 5. Troubleshooting Advanced Features (FAQ)

If things aren't working as expected, check these common issues:

### "My Agent doesn't seem to remember anything!"
**Check 1:** Is the `CallLog` status being updated to `completed`? The memory module searches for past calls by phone number. If previous calls crashed and didn't save transcripts properly, there is nothing to remember.
**Check 2:** Are you calling from the same phone number? Memory strictly filters by the Twilio `From` parameter.

### "The AI ignores my Workflow trigger phrases!"
**Check 1:** Check the length of the system prompt. If the prompt is too long, the LLM might suffer from "lost in the middle" syndrome and ignore the workflow instructions at the bottom.
**Check 2:** Look at `_get_workflow_context` in `main.py`. Are the trigger phrases actually being returned from the DB?

### "My Action Webhook never fires!"
**Check 1:** Does the LLM you selected support Function Calling? OpenAI (`gpt-4o`, `gpt-4o-mini`) handles this flawlessly. Open-source models via Groq *sometimes* struggle to output the correct JSON schema required to trigger the vocode `ActionEvent`.
**Check 2:** Look at your vocode server logs. Do you see `ActionEvent` being emitted? If yes, the issue is your external Webhook URL (maybe it requires auth or is returning a 500 error).

---

You now understand the advanced mechanics of the VOIA platform. Between the Quickstart guide and this document, there should be no black boxes left in the architecture!
