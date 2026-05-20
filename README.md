# mastodon-image-poster

Daily automatic image posting to a Mastodon instance from a local directory.

## How it works

A systemd timer triggers the service once a day. Each run picks the next
image from the configured directory (sorted by name, size or creation time),
uploads it to the Mastodon instance and records which file was last posted.
After all images are posted it wraps around to the first one.

EXIF metadata is read from every image. When available, the date the photo was
taken and the GPS location (reverse-geocoded to a street address) are appended
to each post. If the image has no EXIF data, the file's modification date is
used as a fallback.

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
* **Status text** — optional text prepended to each post (filename used if empty)

## System-wide configuration

Config file: `/etc/mastodon-image-poster/config.ini`

```ini
[mastodon]
instance_url = https://mastodon.social
access_token = YOUR_ACCESS_TOKEN_HERE

[images]
directory = /srv/images
; Sorting order: name, size, time
sort_order = name
; Optional text prepended to every post.
; EXIF date and GPS location are appended automatically when available.
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

---

## Per-user setup (multiple accounts / multiple directories)

Any user on the same server can run their own instance posting to a different
Mastodon account from a different photo folder, without touching the system
service.

### 1 — Create a user config

```bash
mkdir -p ~/.config/mastodon-image-poster
cp /usr/share/doc/mastodon-image-poster/example.ini \
   ~/.config/mastodon-image-poster/config.ini
$EDITOR ~/.config/mastodon-image-poster/config.ini
```

The script detects `~/.config/mastodon-image-poster/config.ini` automatically
(XDG convention). When that file is present, state is stored in
`~/.local/share/mastodon-image-poster/state.json` — no root access required.

Both paths can be overridden with environment variables:

```bash
MASTODON_IMAGE_POSTER_CONFIG=/path/to/config.ini \
MASTODON_IMAGE_POSTER_STATE=/path/to/state.json \
mastodon_image_poster.py
```

### 2 — Create user systemd units

```bash
mkdir -p ~/.config/systemd/user
```

**`~/.config/systemd/user/mastodon-image-poster.service`**

```ini
[Unit]
Description=Post an image to Mastodon
After=network-online.target
Wants=network-online.target mastodon-image-poster.timer

[Service]
Type=oneshot
ExecStart=/usr/bin/mastodon_image_poster.py

[Install]
WantedBy=default.target
```

**`~/.config/systemd/user/mastodon-image-poster.timer`**

```ini
[Unit]
Description=Post an image to Mastodon daily

[Timer]
OnCalendar=daily
Persistent=true

[Install]
WantedBy=timers.target
```

### 3 — Enable and start

```bash
systemctl --user daemon-reload
systemctl --user enable --now mastodon-image-poster.timer
systemctl --user list-timers mastodon-image-poster.timer
```

### 4 — Run without an active login session (lingering)

By default, user services stop when the user logs out. To keep the timer
running even without an active session:

```bash
sudo loginctl enable-linger $USER
```

### Checking status and logs

```bash
systemctl --user status mastodon-image-poster.timer
journalctl --user -u mastodon-image-poster.service -f
```

---

## License

MIT — Vítězslav Dvořák <info@vitexsoftware.cz>
