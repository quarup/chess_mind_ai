# LLM Provider Options for M3 (Scorer Generation)

**Date of research:** 2026-05-24
**Context:** M3 uses an LLM exactly once per user style prompt: send a system
prompt + the user's natural-language style description, get back Python code
implementing `action_score` / `state_score` / `trajectory_score`. One-shot text
in, text out. No streaming, no tool use, no vision.

## Decisions

1. **Build a thin provider-abstraction layer** rather than hard-pinning a single
   SDK. The call site is too simple to justify hard-coupling.
2. **Default to Google Gemini 2.5 Flash-Lite** on the free tier so the bot is
   playable without a credit card.
3. Keep **Anthropic** and **OpenAI** as drop-in alternatives behind the same
   protocol.

## Why an abstraction

- The M3 call is the simplest possible LLM use case — a 1-method protocol
  covers it. The abstraction cost is ~30 lines per adapter.
- Provider-specific message conventions differ (`system_instruction` on Gemini
  vs top-level `system=` on Anthropic vs `messages=[{role:"system",...}]` on
  OpenAI), and the protocol hides this.
- Lets users bring whatever API key they already have.
- Avoids reaching for LiteLLM / LangChain — those would be more code than the
  protocol they replace and would obscure provider-specific caching semantics
  we may want later.

## Why Gemini Flash-Lite as default

- Only provider with a real ongoing **free tier** (no card required).
- Quality is sufficient — scorer generation is a templated task with a fixed
  output shape, not a frontier-reasoning workload.
- Cost if/when the user upgrades is also the cheapest of the three.
- Caveat: free-tier inputs/outputs may be used by Google to improve their
  models. Fine for a hobby chess bot; document this in README.

## Pricing snapshot (per 1M tokens, May 2026)

|              | Flagship                | Mid                          | Cheap                          |
| ------------ | ----------------------- | ---------------------------- | ------------------------------ |
| **Anthropic** | Opus 4.7 — $5 / $25     | Sonnet 4.6 — $3 / $15        | **Haiku 4.5 — $1 / $5**        |
| **OpenAI**   | GPT-5.5 — $5 / $30      | GPT-5.4 — $2.50 / $15        | **GPT-4.1 Nano — $0.10 / $0.40** |
| **Google**   | Gemini 2.5 Pro — $1.25 / $10 | Gemini 2.5 Flash — $0.30 / $2.50 | **Gemini 2.5 Flash-Lite — $0.10 / $0.40** |

Format: `input price / output price`. Anthropic's floor is higher than the
others, but for a single scorer generation (~500 input + ~2000 output tokens)
the absolute cost is negligible (~$0.05 even on Opus).

## Free tiers

| Provider  | Free tier?                                      |
| --------- | ----------------------------------------------- |
| Anthropic | No ongoing free tier (small trial credits only) |
| OpenAI    | No ongoing free tier (trial credits only)       |
| **Google**    | **Yes**, via AI Studio, no card required        |

Gemini free-tier limits as of Dec 2025 (after Google's 50–80% rate-limit
squeeze):

- Gemini 2.5 Pro: 5 RPM, 100/day
- Gemini 2.5 Flash: 10 RPM, 250/day
- Gemini 2.5 Flash-Lite: 15 RPM, 1000/day
- Shared 250k TPM, full 1M-token context window

For ChessMind AI the scorer is generated once per style prompt, so even the
strictest of these limits is more than enough for personal use.

## Abstraction sketch

```python
class StyleScorerLLM(Protocol):
    def generate(
        self,
        system: str,
        user: str,
        *,
        max_output_tokens: int = 2048,
    ) -> str: ...
```

Concrete adapters: `GeminiProvider`, `AnthropicProvider`, `OpenAIProvider`.
Each imports its own SDK lazily so users don't pay the install cost for
providers they don't use. Provider + model are selected by config (env var or
flag); the default points at Gemini 2.5 Flash-Lite.

## Sources

- Anthropic pricing: <https://platform.claude.com/docs/en/about-claude/pricing>
- Gemini pricing: <https://ai.google.dev/pricing>
- Gemini free-tier rate limits: <https://ai.google.dev/gemini-api/docs/rate-limits>
- OpenAI pricing (third-party summary; openai.com blocked our fetch):
  <https://pecollective.com/tools/openai-api-pricing/>
