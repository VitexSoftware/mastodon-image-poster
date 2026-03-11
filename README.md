# mastodon-image-poster

Daily automatic image posting to a Mastodon instance from a local directory.

## How it works

A systemd timer triggers the service once a day. Each run picks the next
image from the configured directory (sorted by name, size or creation time),
uploads it to the Mastodon instance and records which file was last posted
in `/var/lib/mastodon-image-poster/state.json`. After all images are posted
it wraps around to the first one.

Supported formats: **jpg, jpeg, png, gif, webp**

## Installation

```bash
sudo apt install mastodon-image-poster
```

During installation debconf will ask for:

* **Image directory** — path to the folder with images
* **Sort order** — `name`, `size` or `time`
* **Mastodon instance URL** — e.g. `https://mastodon.social`
* **Access token** — Mastodon API access token
* **Status text** — optional text for each post (filename used if empty)

## Configuration

Config file: `/etc/mastodon-image-poster/config.ini`

```ini
[mastodon]
instance_url = https://mastodon.social
access_token = YOUR_ACCESS_TOKEN_HERE

[images]
directory = /srv/images
sort_order = name
status_text =
```

To change the posting interval edit the systemd timer override:

```bash
sudo systemctl edit mastodon-image-poster.timer
```

and set a custom `OnCalendar=` value.

## Reconfigure

```bash
sudo dpkg-reconfigure mastodon-image-poster
```

## License

MIT — Vítězslav Dvořák <info@vitexsoftware.cz>
