# VOIA Cloud (commercial wedge)

Self-host VOIA when you want control. Use **VOIA Cloud** when you want the same graphs without ops.

## Promise

> Same graphs. Zero ops.  
> Export/import conversational-flow JSON between OSS and Cloud — no rewrite.

## Who converts

Self-hosters who hit friction on:

- Twilio webhook URLs / ngrok / number provisioning  
- Keeping Redis, Postgres, and app updates healthy  
- SSO, audit logs, multi-tenant RBAC for a team  
- SLA and on-call for production phone lines  

## What Cloud sells (not OSS)

| Capability | Why paid |
|------------|----------|
| Managed multi-tenant hosting | Ops + upgrades |
| Managed numbers / telephony proxy | Removes Twilio/ngrok pain |
| SSO / SCIM / audit export | Enterprise buyers |
| Region / retention compliance packs | Regulated industries |
| Priority support / onboarding | Services revenue |
| (Later) private template marketplace | Ecosystem cut |

See [OPEN_CORE.md](./OPEN_CORE.md) for the hard boundary. Do **not** sell features that are already open as “Cloud exclusive.”

## Waitlist (pre-launch)

Until a public signup exists, collect interest with a simple form (Typeform / Google Form / GitHub Discussion):

**Suggested fields**

1. Email  
2. Company / project  
3. Using OSS today? (yes / planning to)  
4. Pain: telephony ops / compliance / team SSO / other  
5. Approximate monthly call minutes (optional)  

**Copy for the form**

> Running VOIA locally with your own keys? Join the VOIA Cloud waitlist for managed telephony, SSO, and SLA — same graphs, zero ops.

**In-app waitlist:** open [`/cloud`](../frontend/src/app/cloud/page.tsx) on the dashboard host (e.g. `http://localhost:3001/cloud`).  
By default it opens `mailto:sales@voia.ai` with structured fields. Optional env:

```bash
# frontend/.env.local
NEXT_PUBLIC_CLOUD_WAITLIST_URL=https://your-typeform-or-form-url
NEXT_PUBLIC_CLOUD_WAITLIST_EMAIL=sales@voia.ai
```

Also link from the README **Cloud** section. GitHub Issues labeled `cloud-waitlist` or Discussions category “Cloud” work as backups.

## Portability checklist (engineering)

Before charging money, guarantee:

- [ ] Flow graph JSON import/export (versioned)  
- [ ] Slot / contract validation identical to OSS  
- [ ] Provider keys stay customer-owned (BYOK) even on Cloud  
- [ ] Documented differences (if any) between OSS and Cloud runtimes  

## Pricing posture (draft — not public rates)

- **OSS:** free forever for self-host  
- **Cloud:** usage-based minutes + seat/workspace fee (TBD)  
- **Enterprise:** SSO, compliance, dedicated support  

Publish numbers only when metering matches `voice_platform` usage estimates.

## Related

- [COMPARE.md](./COMPARE.md)  
- [VOIA_OPEN_SOURCE_STRATEGY.md](./VOIA_OPEN_SOURCE_STRATEGY.md) Phase 4  
