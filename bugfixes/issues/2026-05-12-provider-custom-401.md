SYMPTOMS: provider=custom HTTP 401 Invalid API Key
CAUSE: api_key: ${GROQ_API_KEY} in model section was a literal string, not substituted
STATUS: fixed
FIX: Removed api_key from model section, switched primary provider to openrouter
DATE: 2026-05-12
