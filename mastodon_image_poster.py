#!/usr/bin/env python3
"""Post images from a directory to a Mastodon instance, one per invocation."""

import configparser
import json
import logging
import os
import sys
import time
from datetime import datetime

from geopy.geocoders import Nominatim
from mastodon import Mastodon
from PIL import Image
from PIL.ExifTags import TAGS, GPSTAGS

CONFIG_PATH = "/etc/mastodon-image-poster/config.ini"
STATE_PATH = "/var/lib/mastodon-image-poster/state.json"
SUPPORTED_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".webp")

logging.basicConfig(
    level=logging.INFO,
    format="mastodon-image-poster: %(levelname)s: %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger("mastodon-image-poster")


def load_config(path: str) -> configparser.ConfigParser:
    """Load and validate the INI configuration file."""
    if not os.path.isfile(path):
        log.error("Config file not found: %s", path)
        sys.exit(1)

    config = configparser.ConfigParser()
    config.read(path)

    for section, keys in (
        ("mastodon", ("instance_url", "access_token")),
        ("images", ("directory", "sort_order")),
    ):
        if section not in config:
            log.error("Missing config section: [%s]", section)
            sys.exit(1)
        for key in keys:
            if not config[section].get(key):
                log.error("Missing config key: [%s] %s", section, key)
                sys.exit(1)

    return config


def load_state(path: str) -> dict:
    """Load persisted state (last posted file)."""
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("Could not read state file, starting fresh: %s", exc)
    return {}


def save_state(path: str, state: dict) -> None:
    """Persist state to disk."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2)


def list_images(directory: str, sort_order: str) -> list[str]:
    """Return a sorted list of image file paths from the directory."""
    if not os.path.isdir(directory):
        log.error("Image directory does not exist: %s", directory)
        sys.exit(1)

    files = [
        os.path.join(directory, f)
        for f in os.listdir(directory)
        if os.path.isfile(os.path.join(directory, f))
        and f.lower().endswith(SUPPORTED_EXTENSIONS)
    ]

    if sort_order == "size":
        files.sort(key=lambda f: os.path.getsize(f))
    elif sort_order == "time":
        files.sort(key=lambda f: os.path.getmtime(f))
    else:  # name (default)
        files.sort(key=lambda f: os.path.basename(f).lower())

    return files


def find_next_image(images: list[str], last_posted: str | None) -> str | None:
    """Find the next image to post after the last posted one."""
    if not images:
        return None

    if last_posted is None:
        return images[0]

    # Find the position of the last posted file
    for i, img in enumerate(images):
        if os.path.basename(img) == last_posted:
            if i + 1 < len(images):
                return images[i + 1]
            else:
                log.info("All images have been posted. Wrapping around.")
                return images[0]

    # Last posted file no longer exists — start from the beginning
    log.warning("Last posted file '%s' not found in directory, starting from first.", last_posted)
    return images[0]


def wait_for_media(mastodon: Mastodon, media_id: int, max_wait: int = 60) -> None:
    """Wait until media attachment is processed on the server."""
    for attempt in range(max_wait // 2):
        media_info = mastodon.media(media_id)
        if media_info.get("url") is not None:
            return
        log.info("Media %s still processing, waiting... (%d)", media_id, attempt + 1)
        time.sleep(2)
    log.warning("Media %s may not be fully processed after %ds, posting anyway.", media_id, max_wait)


def _get_exif_data(image_path: str) -> dict:
    """Extract EXIF data from an image file."""
    try:
        img = Image.open(image_path)
        exif_raw = img._getexif()
        if exif_raw is None:
            return {}
        return {TAGS.get(tag, tag): value for tag, value in exif_raw.items()}
    except Exception as exc:
        log.debug("Could not read EXIF data from %s: %s", image_path, exc)
        return {}


def _get_date_taken(exif_data: dict) -> str | None:
    """Return the date the photo was taken, formatted nicely."""
    for field in ("DateTimeOriginal", "DateTimeDigitized", "DateTime"):
        raw = exif_data.get(field)
        if raw:
            try:
                dt = datetime.strptime(str(raw), "%Y:%m:%d %H:%M:%S")
                return dt.strftime("%Y-%m-%d")
            except (ValueError, TypeError):
                continue
    return None


def _gps_dms_to_decimal(dms, ref: str) -> float:
    """Convert GPS coordinates from degrees/minutes/seconds to decimal."""
    degrees = float(dms[0])
    minutes = float(dms[1])
    seconds = float(dms[2])
    decimal = degrees + minutes / 60.0 + seconds / 3600.0
    if ref in ("S", "W"):
        decimal = -decimal
    return decimal


def _get_gps_coordinates(exif_data: dict) -> tuple[float, float] | None:
    """Extract GPS latitude and longitude from EXIF data."""
    gps_info = exif_data.get("GPSInfo")
    if not gps_info:
        return None

    # Resolve GPSInfo tag IDs to human-readable names
    gps_data = {}
    for tag_id, value in gps_info.items():
        tag_name = GPSTAGS.get(tag_id, tag_id)
        gps_data[tag_name] = value

    try:
        lat = _gps_dms_to_decimal(gps_data["GPSLatitude"], gps_data["GPSLatitudeRef"])
        lon = _gps_dms_to_decimal(gps_data["GPSLongitude"], gps_data["GPSLongitudeRef"])
        return (lat, lon)
    except (KeyError, TypeError, IndexError) as exc:
        log.debug("Incomplete GPS data: %s", exc)
        return None


def _reverse_geocode(lat: float, lon: float) -> str | None:
    """Reverse-geocode GPS coordinates to a human-readable address."""
    try:
        geolocator = Nominatim(user_agent="mastodon-image-poster")
        location = geolocator.reverse(f"{lat}, {lon}", language="en", addressdetails=True)
        if location is None:
            return None

        addr = location.raw.get("address", {})
        parts: list[str] = []

        # Street and house number
        street = addr.get("road") or addr.get("pedestrian") or addr.get("footway", "")
        house_number = addr.get("house_number", "")
        if street:
            parts.append(f"{street} {house_number}".strip())

        # City
        city = (
            addr.get("city")
            or addr.get("town")
            or addr.get("village")
            or addr.get("municipality", "")
        )
        if city:
            parts.append(city)

        return ", ".join(parts) if parts else None
    except Exception as exc:
        log.warning("Reverse geocoding failed: %s", exc)
        return None


def build_status_text(image_path: str, base_text: str) -> str:
    """Build status text enriched with EXIF date and location."""
    exif_data = _get_exif_data(image_path)
    if not exif_data:
        return base_text or os.path.splitext(os.path.basename(image_path))[0]

    extra_parts: list[str] = []

    date_taken = _get_date_taken(exif_data)
    if date_taken:
        extra_parts.append(f"\U0001F4C5 {date_taken}")

    coords = _get_gps_coordinates(exif_data)
    if coords:
        address = _reverse_geocode(*coords)
        if address:
            extra_parts.append(f"\U0001F4CD {address}")

    extra_parts.append("\U0001F517 Posted by https://github.com/VitexSoftware/mastodon-image-poster")

    status = base_text if base_text else os.path.splitext(os.path.basename(image_path))[0]
    return f"{status}\n\n" + "\n".join(extra_parts)


def post_image(mastodon: Mastodon, image_path: str, status_text: str) -> None:
    """Upload an image and create a status on Mastodon."""
    log.info("Uploading: %s", image_path)
    media = mastodon.media_post(image_path)

    log.info("Waiting for media %s to be processed...", media["id"])
    wait_for_media(mastodon, media["id"])

    description = build_status_text(image_path, status_text)
    log.info("Posting status with media id %s", media["id"])
    mastodon.status_post(description, media_ids=[media["id"]])


def main() -> None:
    config = load_config(CONFIG_PATH)

    instance_url = config["mastodon"]["instance_url"]
    access_token = config["mastodon"]["access_token"]
    directory = config["images"]["directory"]
    sort_order = config["images"].get("sort_order", "name")
    status_text = config["images"].get("status_text", "")

    images = list_images(directory, sort_order)
    if not images:
        log.info("No images found in %s", directory)
        return

    state = load_state(STATE_PATH)
    last_posted = state.get("last_posted")

    next_image = find_next_image(images, last_posted)
    if next_image is None:
        log.info("No image to post.")
        return

    mastodon_client = Mastodon(
        access_token=access_token,
        api_base_url=instance_url,
    )

    post_image(mastodon_client, next_image, status_text)

    state["last_posted"] = os.path.basename(next_image)
    save_state(STATE_PATH, state)
    log.info("Done. Posted: %s", os.path.basename(next_image))


if __name__ == "__main__":
    main()
