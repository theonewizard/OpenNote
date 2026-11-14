"""Optional AI (ADR-0016): off unless OPENNOTE_AI_PROVIDER names a provider *and* the vault
has AI enabled; a provider outside the local network also needs the vault's
allow_external opt-in. Nothing outside app.ai imports it, so the core runs without it."""
