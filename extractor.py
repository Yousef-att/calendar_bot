"""Pulls structured meeting details out of a chat message (text and/or an
attached image such as an event poster) via an LLM."""

import base64
import json
import re
import time

import requests
from openai import OpenAI

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

MODEL_FAMILIES = {"sonnet", "opus", "fable"}


def resolve_model(model_setting, api_key):
    """model_setting is either an explicit OpenRouter slug (used as-is) or one
    of "sonnet"/"opus"/"fable", in which case the highest-numbered
    anthropic/claude-<family>-<version> model currently listed on OpenRouter
    is used -- so it tracks new releases without needing code changes."""
    if model_setting not in MODEL_FAMILIES:
        return model_setting

    last_error = None
    for attempt in range(3):
        try:
            resp = requests.get(
                f"{OPENROUTER_BASE_URL}/models",
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=30,
            )
            resp.raise_for_status()
            break
        except requests.exceptions.RequestException as e:
            last_error = e
            if attempt < 2:
                time.sleep(5)
    else:
        raise RuntimeError(f"Could not reach OpenRouter to resolve model after 3 attempts: {last_error}")
    pattern = re.compile(rf"^anthropic/claude-{model_setting}-(\d+(?:\.\d+)*)$")

    best_id, best_version = None, None
    for model in resp.json()["data"]:
        match = pattern.match(model["id"])
        if not match:
            continue
        version = tuple(int(p) for p in match.group(1).split("."))
        if best_version is None or version > best_version:
            best_version, best_id = version, model["id"]

    if not best_id:
        raise RuntimeError(
            f"No anthropic/claude-{model_setting}-* model found on OpenRouter. "
            f"Set OPENROUTER_MODEL to an exact slug from https://openrouter.ai/models instead."
        )
    return best_id


SYSTEM_PROMPT = """You read a single message from a Telegram chat between two \
colleagues discussing scheduling, and extract every distinct meeting/commitment it \
describes so each can be put straight onto a calendar.

A message can describe more than one meeting -- e.g. a recurring schedule spelled \
out as several back-to-back time blocks ("11:00-12:30 X, 12:30-13:30 Y, 13:30-14:00 \
Z"), or simply several unrelated meetings mentioned together. Extract EACH one as \
its own entry -- do not collapse them into one, and do not silently pick just one.

You are given the message text and a reference date/time (the moment the request \
to extract this event was made, already in the correct local timezone) -- use it \
to resolve relative phrases like "tomorrow", "next Tuesday", or "in the afternoon". \
If a single reference date/day is given for the whole message (e.g. "for next \
Tuesday"), apply it to every meeting extracted from that message unless a specific \
entry clearly overrides it with its own date.

Respond with ONLY valid JSON, no prose before or after, matching exactly this schema:

{
  "events": [
    {
      "date": "YYYY-MM-DD",
      "time": "HH:MM",
      "duration_minutes": 120,
      "topic_en": "short description of what the meeting is about, in English",
      "topic_ru": "the same, in Russian",
      "with_whom_en": "who it's with, in English, or null if not mentioned",
      "with_whom_ru": "the same, in Russian, or null if not mentioned",
      "location_en": "where it is, in English, or null if not mentioned",
      "location_ru": "the same, in Russian, or null if not mentioned"
    }
  ]
}

Rules:
- "events" is an empty list if the message does not clearly describe any specific \
meeting with at least a date and a time -- do not guess or invent a date/time that \
isn't actually implied by the text.
- "time" is 24-hour "HH:MM" in the reference timezone. If only a vague part of day \
is given (e.g. "morning"), pick a reasonable specific time (e.g. "09:00").
- "duration_minutes" is an integer. Only depart from the given default when the \
message actually states or clearly implies a different length for that entry.
- Keep each "topic_*" short (under ~12 words) and concrete -- what that meeting is \
about, not a restatement of the whole message.
- The source message may already be in English, Russian, or a mix -- always fill in \
BOTH the "_en" and "_ru" version of each field (translating whichever language \
wasn't in the original), naturally and idiomatically, not word-for-word. Localize \
names sensibly (e.g. transliterate a Cyrillic name into Latin script for "_en" \
rather than translating its meaning) rather than leaving one version untouched.
- For "with_whom_en"/"with_whom_ru" and "location_en"/"location_ru": either both \
languages are null (not mentioned), or both are filled -- never one without the \
other.

Images:
The message may come with an image -- usually an event poster, flyer, or \
invitation, sometimes a screenshot. Treat the text printed in the image as part \
of the message and extract from it the same way. When there is also message text \
(a caption), read both together; if they conflict, the caption wins, since it is \
usually a correction or added context ("moved to Friday").
- Posters are designed, not written: the date, time, and venue are often \
scattered, stylized, or in small print. Read the whole image before deciding.
- Ignore sponsor/partner logos, slogans, social handles, QR codes, and ticket \
prices -- they are not the meeting details.
- "topic_*" is the event's name or what it is about (e.g. the headline), not the \
organizer's tagline.
- "with_whom_*" is the organizer or host if one is clearly named; otherwise null.
- If the image shows a date without a year, pick the next occurrence of that \
date on or after the reference date.
- If the image gives both a start and an end time, set "duration_minutes" from them.
- If an image has no readable event details (e.g. a photo of people, a meme), \
return an empty "events" list.
"""


def _extract_json(raw_text):
    if not raw_text:
        raise ValueError(
            "Model returned no text (likely ran out of output tokens on internal "
            "reasoning before writing the answer -- try raising max_tokens)."
        )
    match = re.search(r"\{.*\}", raw_text, re.DOTALL)
    if not match:
        raise ValueError(f"No complete JSON found in model output (likely truncated): {raw_text[:200]}")
    return json.loads(match.group(0))


def _build_user_content(message_text, reference_dt, default_duration_minutes, image_bytes, image_mime):
    header = (
        f'Reference date/time: {reference_dt.strftime("%A, %Y-%m-%d %H:%M")} '
        f"(default meeting length if unstated: {default_duration_minutes} minutes)\n\n"
    )
    if not image_bytes:
        return header + f"Message:\n{message_text}"

    caption = message_text or "(no text -- the details are in the attached image)"
    data_url = f"data:{image_mime};base64,{base64.b64encode(image_bytes).decode('ascii')}"
    return [
        {"type": "text", "text": header + f"Message text:\n{caption}\n\nAttached image:"},
        {"type": "image_url", "image_url": {"url": data_url}},
    ]


def extract_events(
    message_text,
    reference_dt,
    default_duration_minutes,
    api_key,
    model_setting,
    image_bytes=None,
    image_mime="image/jpeg",
):
    """reference_dt is a timezone-aware datetime giving "now" for resolving
    relative dates/times, already converted to the target local timezone.
    message_text may be None when image_bytes (e.g. a poster) carries the
    details. Returns a list of event dicts (possibly empty, possibly more
    than one)."""
    model = resolve_model(model_setting, api_key)

    client = OpenAI(base_url=OPENROUTER_BASE_URL, api_key=api_key)
    user_content = _build_user_content(
        message_text, reference_dt, default_duration_minutes, image_bytes, image_mime
    )

    response = client.chat.completions.create(
        model=model,
        # Generous headroom: some models spend a variable, sometimes large,
        # chunk of this on internal reasoning before writing the actual JSON
        # answer -- too tight a budget silently truncates or empties the
        # answer (this bit us once with max_tokens=500 on a long message).
        # Multi-event messages need even more room than a single event did.
        max_tokens=3000,
        extra_headers={"X-Title": "Calendar Bot"},
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
    )
    choice = response.choices[0]
    if choice.finish_reason == "length":
        raise RuntimeError("Model output was truncated (hit max_tokens) before finishing the answer.")
    parsed = _extract_json(choice.message.content)
    events = parsed.get("events") or []
    for event in events:
        if not event.get("duration_minutes"):
            event["duration_minutes"] = default_duration_minutes
    return events
