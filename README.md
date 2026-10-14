# dc-dlp
discord bot for yt-dlp

## features
- play music from youtube links, playlists
- supports bandcamp, soundcloud, etc.
- multiple languages with permanent configuration via Discord (`!j lang`)
- cleanup of downloaded files

## installation
- install python (recommended 3.11.*)
- run those commands:
```bash
git clone https://github.com/zuirx/dc-dlp.git
cd dc-dlp
python -m pip install -r requirements.txt
```
- create a .env file with the following variables:
```bash
BOT_TOKEN=your_token_here
AUTOSTART_LANG=pt  # optional fallback (pt, en, fr, es, ru, cn, ar)
```
- run the bot:
```bash
python bot.py
```

## language configuration
Admins or moderators can set the bot's permanent language directly in Discord:
- `!j lang` — views the current language and available languages
- `!j lang <code or number>` — sets the bot's permanent language (e.g., `!j lang pt`, `!j lang en`, `!j lang 2`)
- *(Only administrators and moderators can change the language)*

