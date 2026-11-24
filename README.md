# 浮き辞典 · Ukijiten

A floating dictionary and reading tracker for Linux.

- Import Yomitan dictionary ZIPs, including frequency, pitch accent, and kanji dictionaries.
- Look up words in independent, resizable search panes and nested popups.
- Customize fonts, colors, backgrounds, and an optional avatar pane.
- Track reading through texthooker WebSockets, Mokuro Browser, and history imports.
- Import Anki review time through AnkiConnect or local collections.
- Translate text using a running local model server or a configured API.

## Run

Requires Python 3.11 or newer and a graphical Linux session.

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python ukijiten.py
```

Open Dictionaries → Add dictionaries to import Yomitan ZIP files.
Open Statistics → Settings to configure reading sources and Anki decks.

Click the search icon to open a scrollable history column on the left. Sort by newest or oldest, then
choose a headword to load it in the same search pane.

Mokuro Browser imports update automatically. Its live indicator appears only
while the matching browser server is running. Cloud imports use Refresh.

Reading history shows daily character counts and time. Japanese totals exclude
punctuation and digits. Time from live scans is estimated from gaps of up to
90 seconds. Sources with their own recorded time retain it.

## Optional integrations

- AnkiConnect: Anki running with the AnkiConnect add-on.
- Cloud storage: `rclone` installed for Google Drive, OneDrive, or MEGA.
- Local translation: an existing Ollama or LM Studio server.
- ChatGPT account translation: the Codex CLI installed and signed in.
- KDE global shortcuts: `dbus-python` and PyGObject, then run `shortcut_daemon.py`.

KDE Plasma Wayland is the main tested desktop. Window behavior may differ on
other desktops.

## Development

```sh
QT_QPA_PLATFORM=offscreen python -m unittest discover -s tests -p 'test_*.py'
```

Bundled fonts and libraries include their licenses. Kanji reference sources are
listed in [assets/KANJI-SOURCES.md](assets/KANJI-SOURCES.md).
