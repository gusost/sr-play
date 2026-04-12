#!/usr/bin/env python3
from __future__ import annotations

import copy
import email.utils
import html
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import xml.etree.ElementTree as ET


BASE_URL = "https://www.sverigesradio.se"
SOURCE_RSS_URL = "https://api.sr.se/api/rss/pod/23791"
PROGRAM_URL = f"{BASE_URL}/p3historia"
SHOW_MORE_URL = (
    f"{BASE_URL}/ajax/showmoreepisodelistitems"
    "?unitid=5067&page={page}&date={date_param}"
)
OUTPUT_PATH = Path("docs/feed.xml")
PUBLIC_FEED_URL = os.environ.get("FEED_URL")
CUSTOM_FEED_TITLE = "P3 Historia (Komplett arkiv)"
CUSTOM_OWNER_NAME = "P3 Historia (Komplett arkiv)"
CUSTOM_DESCRIPTION_SUFFIX = (
    "Detta är ett kompletterat RSS-flöde som inkluderar publika avsnitt"
    " som saknas i Sveriges Radios vanliga poddflöde."
)
ITUNES_NS = "http://www.itunes.com/dtds/podcast-1.0.dtd"
ATOM_NS = "http://www.w3.org/2005/Atom"
SR_NS = "http://www.sverigesradio.se/podrss"
MEDIA_NS = "http://search.yahoo.com/mrss/"
GOOGLEPLAY_NS = "http://www.google.com/schemas/play-podcasts/1.0"


ET.register_namespace("itunes", ITUNES_NS)
ET.register_namespace("atom", ATOM_NS)
ET.register_namespace("sr", SR_NS)
ET.register_namespace("media", MEDIA_NS)
ET.register_namespace("googleplay", GOOGLEPLAY_NS)


def log(message: str) -> None:
    print(message, file=sys.stderr)


def fetch_text(url: str) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "sr-play-feed-builder/1.0 (+https://github.com/)",
            "Accept": "*/*",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8")


def clean_html_text(value: str) -> str:
    text = re.sub(r"<[^>]+>", "", value)
    text = html.unescape(text)
    text = text.replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def ensure_absolute_url(value: str | None) -> str | None:
    if not value:
        return None
    if value.startswith("//"):
        return f"https:{value}"
    if value.startswith("/"):
        return f"{BASE_URL}{value}"
    return value


def parse_sr_datetime(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%SZ")


def format_rss_date(value: datetime) -> str:
    return email.utils.format_datetime(value)


def duration_seconds_to_text(total_seconds: int) -> str:
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def minutes_to_duration_text(minutes: int) -> str:
    hours, remainder = divmod(minutes, 60)
    return f"{hours:02d}:{remainder:02d}:00"


def extract_episode_id_from_rss_item(item: ET.Element) -> str | None:
    link = item.findtext("link") or ""
    match = re.search(r"/avsnitt/(\d+)$", link)
    if match:
        return match.group(1)

    guid = item.findtext("guid") or ""
    match = re.search(r"eid/(\d+)", guid)
    if match:
        return match.group(1)

    return None


@dataclass
class WebEpisode:
    episode_id: str
    title: str
    link: str
    pub_date: datetime
    description: str | None = None
    duration: str | None = None
    image_url: str | None = None
    audio_url: str | None = None
    guid: str | None = None


ITEM_PATTERN = re.compile(
    r'<div class="episode-list-item.*?data-spa-item-id="\d+".*?<div id="metadata-id[^"]*"[^>]*></div>\s*</div>',
    re.S,
)
TITLE_PATTERN = re.compile(
    r'<a\s+href="(?P<href>[^"]+)"[^>]*class="heading h4"\s*>(?P<title>.*?)</a>',
    re.S,
)
DATETIME_PATTERN = re.compile(r'<time[^>]*datetime="(?P<datetime>[^"]+)"', re.S)
DESCRIPTION_PATTERN = re.compile(
    r'<div class="episode-list-item__description is-hidden-touch">\s*<p>(?P<description>.*?)</p>',
    re.S,
)
IMAGE_PATTERN = re.compile(r'data-src="(?P<image>https://[^"]+)"', re.S)
AUDIO_PATTERN = re.compile(
    r'<a href="(?P<audio>//sverigesradio\.se/topsy/ljudfil/[^"]+\.mp3)"',
    re.S,
)
DURATION_PATTERN = re.compile(r'<abbr title="(?P<minutes>\d+)\s+minuter">', re.S)
NEXT_PAGE_PATTERN = re.compile(
    r'data-url="/ajax/showmoreepisodelistitems\?unitid=5067&amp;page=(?P<page>\d+)',
    re.S,
)


def parse_episode_card(card_html: str) -> WebEpisode | None:
    episode_id_match = re.search(r'data-spa-item-id="(?P<episode_id>\d+)"', card_html)
    title_match = TITLE_PATTERN.search(card_html)
    datetime_match = DATETIME_PATTERN.search(card_html)
    if not (episode_id_match and title_match and datetime_match):
        return None

    description_match = DESCRIPTION_PATTERN.search(card_html)
    image_match = IMAGE_PATTERN.search(card_html)
    audio_match = AUDIO_PATTERN.search(card_html)
    duration_match = DURATION_PATTERN.search(card_html)

    duration = None
    if duration_match:
        duration = minutes_to_duration_text(int(duration_match.group("minutes")))

    return WebEpisode(
        episode_id=episode_id_match.group("episode_id"),
        title=clean_html_text(title_match.group("title")),
        link=ensure_absolute_url(title_match.group("href")) or "",
        pub_date=parse_sr_datetime(datetime_match.group("datetime")),
        description=clean_html_text(description_match.group("description"))
        if description_match
        else None,
        duration=duration,
        image_url=ensure_absolute_url(image_match.group("image")) if image_match else None,
        audio_url=ensure_absolute_url(audio_match.group("audio")) if audio_match else None,
        guid=None,
    )


def extract_list_episodes(page_html: str) -> list[WebEpisode]:
    episodes: list[WebEpisode] = []
    for match in ITEM_PATTERN.finditer(page_html):
        card_html = match.group(0)
        episode = parse_episode_card(card_html)
        if episode:
            episodes.append(episode)
    return episodes


def stockholm_date_param() -> str:
    stockholm_now = datetime.now(ZoneInfo("Europe/Stockholm"))
    raw_value = stockholm_now.strftime("%Y-%m-%d 00:00:00")
    return urllib.parse.quote(raw_value, safe="")


def fetch_all_web_episodes() -> list[WebEpisode]:
    seen: dict[str, WebEpisode] = {}
    date_param = stockholm_date_param()

    first_page_html = fetch_text(PROGRAM_URL)
    for episode in extract_list_episodes(first_page_html):
        seen.setdefault(episode.episode_id, episode)

    page = 1
    while True:
        html_page = fetch_text(SHOW_MORE_URL.format(page=page, date_param=date_param))
        page_episodes = extract_list_episodes(html_page)
        if not page_episodes:
            break
        for episode in page_episodes:
            seen.setdefault(episode.episode_id, episode)
        page += 1

    return sorted(seen.values(), key=lambda episode: episode.pub_date, reverse=True)


def _decode_json_string(value: str) -> str:
    return json.loads(f'"{value}"')


def enrich_from_episode_page(episode: WebEpisode) -> WebEpisode:
    page_html = fetch_text(episode.link)
    serialized_html = page_html.replace('\\"', '"')
    episode_id = re.escape(episode.episode_id)

    details_match = re.search(
        rf'"id":{episode_id}.*?"publishUtc":"[^"]+".*?"publishState":"Published"',
        serialized_html,
        re.S,
    )
    details_block = details_match.group(0) if details_match else serialized_html

    player_match = re.search(
        rf'"playerInformation":{{"audio":{{"id":"{episode_id}".*?"title":"(?:\\.|[^"])*","channel":null}}',
        serialized_html,
        re.S,
    )
    player_block = player_match.group(0) if player_match else details_block

    if not episode.audio_url:
        audio_match = re.search(
            rf'"playerInformation":{{"audio":{{"id":"{episode_id}","src":"(?P<audio>https://www\.sverigesradio\.se/topsy/ljudfil/[^"]+)"',
            serialized_html,
        )
        if audio_match:
            episode.audio_url = ensure_absolute_url(_decode_json_string(audio_match.group("audio")))

    if not episode.duration:
        duration_match = re.search(
            rf'"playerInformation":{{"audio":{{"id":"{episode_id}".*?}},"duration":(?P<duration>\d+),"id":"{episode_id}"',
            serialized_html,
            re.S,
        )
        if duration_match:
            episode.duration = duration_seconds_to_text(int(duration_match.group("duration")))

    if not episode.image_url:
        image_match = re.search(r'"imageSrc":"(?P<image>https://[^"]+)"', player_block)
        if image_match:
            episode.image_url = _decode_json_string(image_match.group("image"))

    if not episode.description:
        description_match = re.search(
            r'"fullDescription":"(?P<description>(?:\\.|[^"])*)"',
            details_block,
        )
        if not description_match:
            description_match = re.search(
                r'"description":"(?P<description>(?:\\.|[^"])*)"',
                details_block,
            )
        if description_match:
            episode.description = clean_html_text(_decode_json_string(description_match.group("description")))

    return episode


def build_web_only_item(episode: WebEpisode) -> ET.Element:
    item = ET.Element("item")

    title = ET.SubElement(item, "title")
    title.text = episode.title

    description = ET.SubElement(item, "description")
    description.text = episode.description or episode.title

    link = ET.SubElement(item, "link")
    link.text = episode.link

    guid = ET.SubElement(item, "guid", {"isPermaLink": "false"})
    guid.text = episode.guid or f"sr-play:episode:{episode.episode_id}"

    pub_date = ET.SubElement(item, "pubDate")
    pub_date.text = format_rss_date(episode.pub_date)

    ET.SubElement(item, f"{{{SR_NS}}}programid").text = "5067"
    ET.SubElement(item, f"{{{SR_NS}}}poddid").text = "23791"
    ET.SubElement(item, f"{{{ITUNES_NS}}}author").text = "Sveriges Radio"

    if episode.description:
        ET.SubElement(item, f"{{{ITUNES_NS}}}summary").text = episode.description
        ET.SubElement(item, f"{{{ITUNES_NS}}}subtitle").text = episode.description

    if episode.image_url:
        ET.SubElement(item, f"{{{ITUNES_NS}}}image", {"href": episode.image_url})

    if episode.duration:
        ET.SubElement(item, f"{{{ITUNES_NS}}}duration").text = episode.duration

    if episode.audio_url:
        ET.SubElement(
            item,
            "enclosure",
            {
                "url": episode.audio_url,
                "length": "0",
                "type": "audio/mpeg",
            },
        )

    return item


def load_source_feed() -> tuple[ET.ElementTree, ET.Element, list[tuple[datetime, str, ET.Element]]]:
    rss_text = fetch_text(SOURCE_RSS_URL)
    tree = ET.ElementTree(ET.fromstring(rss_text))
    channel = tree.getroot().find("channel")
    if channel is None:
        raise RuntimeError("Source RSS feed is missing <channel>.")

    items: list[tuple[datetime, str, ET.Element]] = []
    for item in channel.findall("item"):
        episode_id = extract_episode_id_from_rss_item(item)
        if not episode_id:
            continue
        pub_date_text = item.findtext("pubDate")
        if not pub_date_text:
            continue
        pub_date = email.utils.parsedate_to_datetime(pub_date_text)
        items.append((pub_date.replace(tzinfo=None), episode_id, copy.deepcopy(item)))

    return tree, channel, items


def make_output_root(source_channel: ET.Element) -> tuple[ET.Element, ET.Element]:
    root = ET.Element("rss", {"version": "2.0"})
    channel = ET.SubElement(root, "channel")
    for child in source_channel:
        if child.tag == "item":
            continue
        if child.tag == "title":
            updated_child = copy.deepcopy(child)
            updated_child.text = CUSTOM_FEED_TITLE
            channel.append(updated_child)
            continue
        if child.tag == "description":
            updated_child = copy.deepcopy(child)
            base_text = updated_child.text or ""
            updated_child.text = f"{base_text}\n{CUSTOM_DESCRIPTION_SUFFIX}".strip()
            channel.append(updated_child)
            continue
        if child.tag == "image":
            updated_child = copy.deepcopy(child)
            image_title = updated_child.find("title")
            if image_title is not None:
                image_title.text = CUSTOM_FEED_TITLE
            channel.append(updated_child)
            continue
        if child.tag == f"{{{ITUNES_NS}}}summary":
            updated_child = copy.deepcopy(child)
            base_text = updated_child.text or ""
            updated_child.text = f"{base_text} {CUSTOM_DESCRIPTION_SUFFIX}".strip()
            channel.append(updated_child)
            continue
        if child.tag == f"{{{ITUNES_NS}}}owner":
            updated_child = copy.deepcopy(child)
            owner_name = updated_child.find(f"{{{ITUNES_NS}}}name")
            if owner_name is not None:
                owner_name.text = CUSTOM_OWNER_NAME
            channel.append(updated_child)
            continue
        if PUBLIC_FEED_URL and child.tag == f"{{{ITUNES_NS}}}new-feed-url":
            updated_child = copy.deepcopy(child)
            updated_child.text = PUBLIC_FEED_URL
            channel.append(updated_child)
            continue
        if PUBLIC_FEED_URL and child.tag == f"{{{ATOM_NS}}}link":
            updated_child = copy.deepcopy(child)
            updated_child.set("href", PUBLIC_FEED_URL)
            channel.append(updated_child)
            continue
        channel.append(copy.deepcopy(child))
    return root, channel


def write_xml(root: ET.Element, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    tree.write(output_path, encoding="utf-8", xml_declaration=True)


def main() -> int:
    log("Fetching source RSS feed...")
    _, source_channel, rss_items = load_source_feed()
    rss_episode_ids = {episode_id for _, episode_id, _ in rss_items}
    log(f"Source RSS episodes: {len(rss_episode_ids)}")

    log("Fetching public web episode archive...")
    web_episodes = fetch_all_web_episodes()
    log(f"Public web episodes: {len(web_episodes)}")

    missing_web_episodes = [
        episode for episode in web_episodes if episode.episode_id not in rss_episode_ids
    ]
    log(f"Web-only episodes to add: {len(missing_web_episodes)}")

    enriched_missing_episodes: list[WebEpisode] = []
    for episode in missing_web_episodes:
        if not (episode.audio_url and episode.description and episode.image_url and episode.duration):
            episode = enrich_from_episode_page(episode)
        if not episode.audio_url:
            raise RuntimeError(
                f"Missing audio URL for episode {episode.episode_id} ({episode.title})."
            )
        enriched_missing_episodes.append(episode)

    combined_items: list[tuple[datetime, str, ET.Element]] = list(rss_items)
    for episode in enriched_missing_episodes:
        combined_items.append(
            (episode.pub_date, episode.episode_id, build_web_only_item(episode))
        )

    combined_items.sort(key=lambda item: item[0], reverse=True)
    root, output_channel = make_output_root(source_channel)
    for _, _, item in combined_items:
        output_channel.append(item)

    write_xml(root, OUTPUT_PATH)

    log(f"Wrote {len(combined_items)} total items to {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except urllib.error.URLError as error:
        log(f"Network error: {error}")
        raise SystemExit(1)
    except Exception as error:  # noqa: BLE001
        log(f"Build failed: {error}")
        raise SystemExit(1)
