# dc-dlp
discord bot for yt-dlp

## features
- play music from youtube links, playlists
- supports bandcamp, soundcloud, etc.
- multiple language selection
- cleanup of downloaded files

## installation
- install python (recommended 3.11.*)
- run those commands:
```bash
git clone https://github.com/jabirito/dc-dlp.git
cd dc-dlp
python -m pip install -r requirements.txt
```
- create a .env file with the following variables:
```bash
BOT_TOKEN=your_token_here
AUTOSTART_LANG=en  # optional, skips language selection
```
- run the bot
```bash
python bot.py
```