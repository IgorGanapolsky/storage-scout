"""Email open tracking via 1x1 pixel.

Generates unique tracking pixel URLs per message. Requires a pixel endpoint
that returns a 1x1 transparent GIF and logs the open.

Deploy a Cloudflare Worker (free tier, 100k req/day) with this code:

    export default {
      async fetch(request) {
        const url = new URL(request.url);
        const mid = url.searchParams.get('mid') || 'unknown';
        console.log(JSON.stringify({event: 'email_open', mid, ts: Date.now()}));
        const gif = Uint8Array.from(atob(
          'R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7'
        ), c => c.charCodeAt(0));
        return new Response(gif, {
          headers: {
            'Content-Type': 'image/gif',
            'Cache-Control': 'no-store, no-cache, must-revalidate',
          },
        });
      },
    };
"""

import hashlib

# Set this to your deployed pixel endpoint URL.
# Leave empty to disable open tracking (HTML emails still sent, just without pixel).
PIXEL_ENDPOINT = ""


def generate_message_id(lead_id: str, step: int) -> str:
    """Generate a unique, opaque message ID for tracking."""
    raw = f"{lead_id}:{step}:{id(lead_id)}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def tracking_pixel_url(message_id: str) -> str:
    """Return the tracking pixel URL for a given message ID."""
    if not PIXEL_ENDPOINT:
        return ""
    return f"{PIXEL_ENDPOINT}?mid={message_id}"


def wrap_html_email(text_body: str, pixel_url: str = "") -> str:
    """Convert a plain-text email body to minimal HTML with optional tracking pixel."""
    html_body = (
        text_body
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\n", "<br>\n")
    )

    pixel_tag = ""
    if pixel_url:
        pixel_tag = f'<img src="{pixel_url}" width="1" height="1" alt="" style="display:none" />'

    return (
        '<!DOCTYPE html>\n<html>\n<head><meta charset="utf-8"></head>\n'
        '<body style="font-family: sans-serif; font-size: 14px; line-height: 1.5; color: #333;">\n'
        f'{html_body}\n'
        f'{pixel_tag}\n'
        '</body>\n</html>'
    )
