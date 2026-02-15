#!/usr/bin/env python3
"""Collect unread Telegram channel messages, summarize, export HTML, and post digest."""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import html
import json
import logging
import os
import re
from collections import defaultdict
from pathlib import Path
from typing import Iterable

import requests
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
from telethon.tl.types import Channel, Message, PeerChannel

LOGGER = logging.getLogger("telegram_digest")


@dataclasses.dataclass
class DigestItem:
    channel_title: str
    channel_id: int
    message_id: int
    date: str
    text: str
    summary: str
    message_link: str


class Summarizer:
    """Wrap OpenAI-compatible summarization with a fallback local summarizer."""

    def __init__(self, model: str | None = None) -> None:
        self.api_key = os.getenv("OPENAI_API_KEY")
        self.base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
        self.model = model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    def summarize(self, text: str) -> str:
        cleaned = normalize_text(text)
        if not cleaned:
            return "(텍스트 없음)"

        if self.api_key:
            try:
                return self._summarize_remote(cleaned)
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning("Remote summary failed (%s), fallback summarizer used", exc)

        return summarize_locally(cleaned)

    def _summarize_remote(self, text: str) -> str:
        prompt = (
            "아래 텔레그램 메시지를 2~3개 핵심 bullet로 한국어 요약하세요. "
            "중요한 수치/일정/행동요청을 우선 반영하고 400자 이내로 작성하세요.\n\n"
            f"메시지:\n{text}"
        )
        response = requests.post(
            f"{self.base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": "너는 텔레그램 뉴스레터 에디터다."},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.2,
            },
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        return payload["choices"][0]["message"]["content"].strip()


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def summarize_locally(text: str, max_sentences: int = 3) -> str:
    chunks = re.split(r"(?<=[.!?。！？])\s+|\n+", text)
    filtered = [chunk.strip(" -•") for chunk in chunks if len(chunk.strip()) > 15]
    if not filtered:
        filtered = [text[:240]]
    selected = filtered[:max_sentences]
    return "\n".join(f"• {s[:220]}" for s in selected)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", default=os.getenv("TG_SESSION", "tg_digest"), help="Telethon session name")
    parser.add_argument("--output-dir", default="output", help="Folder to save html/json files")
    parser.add_argument("--limit", type=int, default=50, help="Max unread messages per channel")
    parser.add_argument("--post", action="store_true", help="Post digest to Telegram via bot")
    parser.add_argument("--log-level", default="INFO")
    return parser.parse_args()


def build_message_link(channel: Channel, message_id: int) -> str:
    if channel.username:
        return f"https://t.me/{channel.username}/{message_id}"

    # Private/supergroup fallback: https://t.me/c/<id_without_-100>/<msg_id>
    channel_id = abs(channel.id)
    channel_id_str = str(channel_id)
    if channel_id_str.startswith("100"):
        internal_id = channel_id_str[3:]
    else:
        internal_id = channel_id_str
    return f"https://t.me/c/{internal_id}/{message_id}"


async def fetch_unread_messages(client: TelegramClient, limit: int) -> list[DigestItem]:
    summarizer = Summarizer()
    result: list[DigestItem] = []

    async for dialog in client.iter_dialogs():
        entity = dialog.entity
        if not isinstance(entity, Channel):
            continue
        if dialog.unread_count <= 0:
            continue

        LOGGER.info("%s unread=%s", dialog.title, dialog.unread_count)
        count = min(dialog.unread_count, limit)
        messages: list[Message] = []
        async for msg in client.iter_messages(entity, limit=count):
            if not msg.unread:
                continue
            if not msg.message and not msg.raw_text:
                continue
            messages.append(msg)

        messages.reverse()
        for msg in messages:
            text = msg.raw_text or msg.message or ""
            summary = summarizer.summarize(text)
            result.append(
                DigestItem(
                    channel_title=dialog.title,
                    channel_id=entity.id,
                    message_id=msg.id,
                    date=msg.date.astimezone().strftime("%Y-%m-%d %H:%M"),
                    text=text,
                    summary=summary,
                    message_link=build_message_link(entity, msg.id),
                )
            )

    return result


def render_html(items: Iterable[DigestItem]) -> str:
    cards = []
    for item in items:
        cards.append(
            f"""
            <article class=\"card\"> 
              <header>
                <h3>{html.escape(item.channel_title)}</h3>
                <p>{item.date}</p>
              </header>
              <p><strong>요약</strong><br>{html.escape(item.summary).replace(chr(10), '<br>')}</p>
              <details>
                <summary>원문 보기</summary>
                <pre>{html.escape(item.text)}</pre>
              </details>
              <a href=\"{item.message_link}\" target=\"_blank\">원본 링크 열기</a>
            </article>
            """.strip()
        )

    body = "\n".join(cards) or "<p>안 읽은 채널 메시지가 없습니다.</p>"
    generated = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    return f"""
<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Telegram Unread Digest</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; margin: 2rem; background:#f5f7fb; }}
    .grid {{ display:grid; gap:1rem; }}
    .card {{ background:#fff; border-radius:12px; padding:1rem 1.2rem; box-shadow:0 2px 6px rgba(0,0,0,0.08); }}
    h1 {{ margin-top:0; }}
    pre {{ white-space: pre-wrap; word-wrap: break-word; background:#fafafa; padding:0.7rem; border-radius:8px; }}
    a {{ color:#0b6bcb; text-decoration:none; }}
  </style>
</head>
<body>
  <h1>안 읽은 텔레그램 채널 요약</h1>
  <p>생성 시각: {generated}</p>
  <section class="grid">{body}</section>
</body>
</html>
""".strip()


def build_digest_message(items: list[DigestItem], max_items: int = 20) -> str:
    if not items:
        return "📭 안 읽은 채널 메시지가 없습니다."

    grouped: dict[str, list[DigestItem]] = defaultdict(list)
    for item in items[:max_items]:
        grouped[item.channel_title].append(item)

    lines = ["🧾 <b>안 읽은 채널 요약</b>"]
    for channel, channel_items in grouped.items():
        lines.append(f"\n📌 <b>{html.escape(channel)}</b>")
        for idx, item in enumerate(channel_items, start=1):
            lines.append(f"{idx}) {html.escape(item.summary)}")
            lines.append(f"🔗 <a href=\"{item.message_link}\">원문 링크</a>")

    if len(items) > max_items:
        lines.append(f"\n…외 {len(items)-max_items}건은 HTML/JSON 파일을 확인하세요.")

    return "\n".join(lines)


def post_via_bot(message: str) -> None:
    token = os.getenv("TG_BOT_TOKEN")
    chat_id = os.getenv("TG_TARGET_CHAT_ID")
    if not token or not chat_id:
        raise ValueError("TG_BOT_TOKEN and TG_TARGET_CHAT_ID are required for --post")

    resp = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": message, "parse_mode": "HTML", "disable_web_page_preview": True},
        timeout=20,
    )
    resp.raise_for_status()


def write_outputs(output_dir: Path, items: list[DigestItem]) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    html_path = output_dir / f"digest_{timestamp}.html"
    json_path = output_dir / f"digest_{timestamp}.json"

    html_path.write_text(render_html(items), encoding="utf-8")
    json_path.write_text(json.dumps([dataclasses.asdict(i) for i in items], ensure_ascii=False, indent=2), encoding="utf-8")
    return html_path, json_path


async def main() -> None:
    args = parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO))

    api_id = os.getenv("TG_API_ID")
    api_hash = os.getenv("TG_API_HASH")
    if not api_id or not api_hash:
        raise ValueError("TG_API_ID and TG_API_HASH are required")

    client = TelegramClient(args.session, int(api_id), api_hash)
    await client.connect()

    if not await client.is_user_authorized():
        phone = os.getenv("TG_PHONE")
        if not phone:
            raise ValueError("TG_PHONE is required on first login")
        await client.send_code_request(phone)
        code = input("Telegram login code: ").strip()
        try:
            await client.sign_in(phone, code)
        except SessionPasswordNeededError:
            pwd = os.getenv("TG_2FA_PASSWORD") or input("2FA password: ").strip()
            await client.sign_in(password=pwd)

    items = await fetch_unread_messages(client, args.limit)
    html_path, json_path = write_outputs(Path(args.output_dir), items)
    LOGGER.info("Saved HTML: %s", html_path)
    LOGGER.info("Saved JSON: %s", json_path)

    if args.post:
        message = build_digest_message(items)
        post_via_bot(message)
        LOGGER.info("Posted digest to Telegram")

    await client.disconnect()


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
