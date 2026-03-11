#!/usr/bin/env python3
"""Post images from a directory to a Mastodon instance, one per invocation."""

import configparser
import json
import logging
import os
import sys

from mastodon import Mastodon

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


def post_image(mastodon: Mastodon, image_path: str, status_text: str) -> None:
    """Upload an image and create a status on Mastodon."""
    log.info("Uploading: %s", image_path)
    media = mastodon.media_post(image_path)

    description = status_text if status_text else os.path.splitext(os.path.basename(image_path))[0]
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
