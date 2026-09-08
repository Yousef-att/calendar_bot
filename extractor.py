"""Pulls structured meeting details out of a raw chat message via an LLM."""

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
colleagues discussing scheduling, and extract the meeting it describes so it can \
be put straight onto a calendar.

You are given the message text and a reference date/time (the moment the request \
to extract this event was made, already in the correct local timezone) -- use it \
to resolve relative phrases like "tomorrow", "next Tuesday", or "in the afternoon".

Respond with ONLY valid JSON, no prose before or after, matching exactly this schema:

{
  "found": true,
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

Rules:
- Set "found": false (and every other field null) if the message does not clearly \
describe a specific meeting with at least a date and a time -- do not guess or \
invent a date/time that isn't actually implied by the text.
- "time" is 24-hour "HH:MM" in the reference timezone. If only a vague part of day \
is given (e.g. "morning"), pick a reasonable specific time (e.g. "09:00").
- "duration_minutes" is an integer. Only depart from the given default when the \
message actually states or clearly implies a different length.
- Keep each "topic_*" short (under ~12 words) and concrete -- what the meeting is \
about, not a restatement of the whole message.
- The source message may already be in English, Russian, or a mix -- always fill in \
BOTH the "_en" and "_ru" version of each field (translating whichever language \
wasn't in the original), naturally and idiomatically, not word-for-word. Localize \
names sensibly (e.g. transliterate a Cyrillic name into Latin script for "_en" \
rather than translating its meaning) rather than leaving one version untouched.
- For "with_whom_en"/"with_whom_ru" and "location_en"/"location_ru": either both \
languages are null (not mentioned), or both are filled -- never one without the \
other.
"""


def _extract_json(raw_text):
    match = re.search(r"\{.*\}", raw_text, re.DOTALL)
    if not match:
        raise ValueError(f"No JSON found in model output: {raw_text[:200]}")
    return json.loads(match.group(0))


def extract_event(message_text, reference_dt, default_duration_minutes, api_key, model_setting):
    """reference_dt is a timezone-aware datetime giving "now" for resolving
    relative dates/times, already converted to the target local timezone."""
    model = resolve_model(model_setting, api_key)

    client = OpenAI(base_url=OPENROUTER_BASE_URL, api_key=api_key)
    user_content = (
        f'Reference date/time: {reference_dt.strftime("%A, %Y-%m-%d %H:%M")} '
        f"(default meeting length if unstated: {default_duration_minutes} minutes)\n\n"
        f"Message:\n{message_text}"
    )

    response = client.chat.completions.create(
        model=model,
        max_tokens=500,
        extra_headers={"X-Title": "Calendar Bot"},
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
    )
    raw_text = response.choices[0].message.content
    event = _extract_json(raw_text)
    if event.get("found") and not event.get("duration_minutes"):
        event["duration_minutes"] = default_duration_minutes
    return event
