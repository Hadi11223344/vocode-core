# Extension guide: add a provider (LLM / STT / TTS)

VOIA is **BYOK**: providers are adapters resolved from user keys and `.env`, not hard-wired vendors.

## LLM (most common)

LLM routing is OpenAI-compatible. Start here:

1. **`voice_platform/agents/agent_factory.py`**  
   - Add to `LLM_BASE_URLS`, `LLM_DEFAULT_MODELS`, and `_PROVIDER_MODELS`  
   - Extend `_resolve_llm_api_key` / platform `.env` fallback if the service name differs  
2. **`voice_platform/config.py` + `.env.example`**  
   - Document `YOUR_PROVIDER_API_KEY`  
3. **Frontend agent settings**  
   - Expose the provider in the LLM provider dropdown / types (`frontend/src/lib/types.ts` and agent forms)  
4. **Key vault**  
   - Ensure Settings → API keys can store the service name used in resolution  

### Ollama / local

Prefer `OPENAI_API_BASE` (or the existing `ollama` provider entry) pointing at a local OpenAI-compatible server. Document Tier 0 usage in the README.

## STT / TTS

These usually extend Vocode streaming adapters under `vocode/streaming/` and are selected in the agent factory / telephony config.

1. Implement or wrap a Vocode `BaseTranscriber` / synthesizer.  
2. Wire selection in `agent_factory` (or equivalent telephony setup).  
3. Add env vars + optional user key service name.  
4. Test with a short live or playground path that actually exercises audio when possible.

## Telephony

Twilio is the supported production path today. Alternate telephony should follow Vocode’s telephony abstractions and platform webhook routes — treat as a larger RFC before coding.

## Checklist

- [ ] Key resolution order documented (user key → agent key → platform `.env`)  
- [ ] `.env.example` updated  
- [ ] No secrets in tests; use mocks  
- [ ] README tier table mentions the provider if it unlocks Tier 0/1  

## References

- `voice_platform/agents/agent_factory.py`  
- `voice_platform/api/key_routes.py`  
- `voice_platform/encryption.py`  
- [OPEN_CORE.md](../OPEN_CORE.md)
