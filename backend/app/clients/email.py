"""Email delivery client — one adapter module per external service, same
pattern the provider clients (Spotify, YouTube, MusicBrainz, ...) will follow.

Stub for development: logs the link instead of sending real email. Swap
this function's body for a Resend/SMTP call before real testers use the
system — the call site (services/auth.py) doesn't need to change.
"""

import logging

logger = logging.getLogger("orchestra.email")


async def send_magic_link_email(to_email: str, magic_link_url: str) -> None:
    logger.info("Magic link for %s: %s", to_email, magic_link_url)
    print(f"[stub email] Magic link for {to_email}: {magic_link_url}")
