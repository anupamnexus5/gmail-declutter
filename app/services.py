"""Read only Gmail discovery. Never follows unsubscribe links."""
import asyncio
import re
from email.header import decode_header, make_header
from email.utils import parseaddr
from typing import Any

import httpx
from pydantic import BaseModel

GMAIL_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages"
HEADERS = ("From", "Subject", "List-Id", "List-Unsubscribe", "List-Unsubscribe-Post")


class Subscription(BaseModel):
    key: str
    sender: str
    address: str
    list_id: str | None
    count: int
    latest_subject: str
    latest_timestamp: int
    unsubscribe_method: str


def decoded(value: str) -> str:
    try:
        return str(make_header(decode_header(value)))
    except (LookupError, UnicodeError):
        return value


def group_messages(messages: list[dict[str, Any]]) -> list[Subscription]:
    groups: dict[str, Subscription] = {}
    for message in sorted(messages, key=lambda m: int(m.get("internalDate", 0)), reverse=True):
        headers = {h["name"].lower(): h["value"] for h in message.get("payload", {}).get("headers", [])}
        name, address = parseaddr(decoded(headers.get("from", "")))
        address = address.lower()
        list_header = headers.get("list-id", "")
        match = re.search(r"<([^>]+)>", list_header)
        list_id = (match.group(1) if match else list_header).strip().lower() or None
        key = f"list:{list_id}" if list_id else f"sender:{address}"
        if not address and not list_id:
            continue
        if key in groups:
            groups[key].count += 1
            continue
        unsubscribe = headers.get("list-unsubscribe", "").lower()
        one_click = headers.get("list-unsubscribe-post", "").strip().lower() == "list-unsubscribe=one-click"
        method = "One-click advertised" if one_click and "<https://" in unsubscribe else (
            "Manual review" if unsubscribe else "No unsubscribe header"
        )
        groups[key] = Subscription(
            key=key, sender=name or address or list_id or "Unknown", address=address,
            list_id=list_id, count=1, latest_subject=decoded(headers.get("subject", "(No subject)")),
            latest_timestamp=int(message.get("internalDate", 0)), unsubscribe_method=method,
        )
    return sorted(groups.values(), key=lambda item: (-item.count, item.sender.lower()))


async def scan_promotions(client: httpx.AsyncClient, token: str, limit: int = 100) -> dict[str, Any]:
    """Bounded scan with pagination and at most five concurrent metadata fetches."""
    auth = {"Authorization": f"Bearer {token}"}
    ids: list[str] = []
    page: str | None = None
    while len(ids) < limit:
        params: dict[str, str | int] = {"q": "category:promotions newer_than:90d", "maxResults": min(100, limit - len(ids))}
        if page:
            params["pageToken"] = page
        response = await client.get(GMAIL_URL, params=params, headers=auth)
        response.raise_for_status()
        data = response.json()
        ids.extend(item["id"] for item in data.get("messages", []))
        page = data.get("nextPageToken")
        if not page:
            break
    semaphore = asyncio.Semaphore(5)

    async def fetch(message_id: str) -> dict[str, Any] | None:
        async with semaphore:
            response = await client.get(
                f"{GMAIL_URL}/{message_id}", headers=auth,
                params=[("format", "metadata"), *[("metadataHeaders", name) for name in HEADERS]],
            )
            if response.status_code == 404:
                return None  # The message may have been deleted since listing.
            response.raise_for_status()
            return response.json()

    results = await asyncio.gather(*(fetch(message_id) for message_id in ids[:limit]))
    messages = [message for message in results if message is not None]
    return {"subscriptions": [s.model_dump() for s in group_messages(messages)],
            "scanned": len(messages), "limited": bool(page), "demo": False}


def demo_scan() -> dict[str, Any]:
    messages = []
    for name, address, count, subject, method in [
        ("The Daily Edit", "hello@daily.example", 24, "Your weekly reading list", True),
        ("Trail Supply", "news@trail.example", 16, "A little fresh air awaits", True),
        ("Studio Notes", "letters@studio.example", 8, "Ideas for a slower Sunday", False),
        ("Weekend Kitchen", "recipes@kitchen.example", 5, "Something good is cooking", False),
    ]:
        for index in range(count):
            headers = [{"name": "From", "value": f"{name} <{address}>"},
                       {"name": "Subject", "value": subject},
                       {"name": "List-Id", "value": f"<{address}>"},
                       {"name": "List-Unsubscribe", "value": "<https://example.com/unsubscribe>"}]
            if method:
                headers.append({"name": "List-Unsubscribe-Post", "value": "List-Unsubscribe=One-Click"})
            messages.append({"internalDate": str(1804800000000 - index * 86400000), "payload": {"headers": headers}})
    return {"subscriptions": [s.model_dump() for s in group_messages(messages)], "scanned": len(messages), "limited": False, "demo": True}
