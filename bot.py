import discord, yt_dlp, os, asyncio, hashlib, json, time
from datetime import datetime, timedelta
from discord.ext import commands, tasks
from dotenv import load_dotenv

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!j ", intents=intents)

PP_PATH = os.path.dirname(os.path.abspath(__file__))


def _extract_chrome_cookies(cookie_file=None):
    """
    Extract YouTube cookies from Google Chrome and write a Netscape-format file.
    Returns the path to the cookies file, or None on failure.
    """
    if cookie_file is None:
        cookie_file = os.path.join(PP_PATH, "cookies.txt")

    try:
        import browser_cookie3
    except ImportError:
        print("[cookies] browser_cookie3 not installed. Run: pip install browser-cookie3")
        return None

    # Try multiple Chrome variants
    browsers = []
    for name in ("chrome", "chromium", "chrome-beta", "chrome-dev", "brave"):
        try:
            getattr(browser_cookie3, name)(cookie_file=cookie_file)
            browsers.append(name)
            break
        except Exception:
            continue

    if not browsers:
        print("[cookies] Could not access any Chrome-based browser cookies.")
        print("[cookies] On Linux, make sure gnome-keyring is unlocked, or export cookies.txt manually.")
        return None

    # browser_cookie3 already wrote the file — verify it has youtube cookies
    if not os.path.exists(cookie_file) or os.path.getsize(cookie_file) < 100:
        print("[cookies] Extracted cookies file is empty or too small.")
        return None

    with open(cookie_file, "r", encoding="utf-8") as f:
        content = f.read()

    if ".youtube.com" not in content:
        print("[cookies] WARNING: No YouTube cookies found in Chrome. Are you logged into YouTube?")
        # still return the file — it may have other useful cookies

    print(f"[cookies] Extracted Chrome cookies → {cookie_file}  ({len(content)} bytes)")
    return cookie_file

YTDL_OPTS = {
    "http_headers": {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
    },
    "extractor_args": {
        "youtube": {
            # android/ios first — they bypass SABR streaming that breaks the web client
            "player_client": ["android", "ios", "web"],
        }
    },
}

queue = []              # display strings
queue_to_play = []      # video IDs in play order
finished_at = {}        # vid_id -> datetime when it stopped playing (for cleanup)
txts = {}               # language strings

SETTINGS_FILE = os.path.join(PP_PATH, "settings.json")
LANG_FILE = os.path.join(PP_PATH, "lang.json")

LANG_MAP = {
    '1': 'en', '2': 'pt', '3': 'fr', '4': 'es', '5': 'ru', '6': 'cn', '7': 'ar',
    'en': 'en', 'pt': 'pt', 'fr': 'fr', 'es': 'es', 'ru': 'ru', 'cn': 'cn', 'ar': 'ar',
    'english': 'en', 'ingles': 'en', 'inglês': 'en',
    'portugues': 'pt', 'português': 'pt', 'pt-br': 'pt', 'pt_br': 'pt',
    'francais': 'fr', 'français': 'fr', 'frances': 'fr', 'francês': 'fr',
    'espanol': 'es', 'español': 'es',
    'russian': 'ru', 'russo': 'ru',
    'chinese': 'cn', 'chines': 'cn', 'chinês': 'cn', 'zh': 'cn',
    'arabic': 'ar', 'arabe': 'ar', 'árabe': 'ar'
}

LANG_NAMES = {
    'en': 'English',
    'pt': 'Português',
    'fr': 'Français',
    'es': 'Español',
    'ru': 'Русский',
    'cn': '中文',
    'ar': 'العربية'
}

try:
    with open(LANG_FILE, 'r', encoding='utf-8') as f:
        all_langs = json.load(f)
except Exception:
    all_langs = {}


def load_settings():
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, dict):
                    if "guilds" not in data or not isinstance(data["guilds"], dict):
                        data["guilds"] = {}
                    return data
        except Exception as e:
            print(f"[settings] Erro ao carregar settings.json: {e}")
    return {"default_lang": "pt", "guilds": {}}


def save_settings(data):
    try:
        with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[settings] Erro ao salvar settings.json: {e}")


bot_settings = load_settings()


def get_lang_code(guild_or_ctx=None):
    guild = None
    if isinstance(guild_or_ctx, commands.Context):
        guild = guild_or_ctx.guild
    elif isinstance(guild_or_ctx, discord.Guild):
        guild = guild_or_ctx
    elif isinstance(guild_or_ctx, discord.Message):
        guild = guild_or_ctx.guild

    if guild and str(guild.id) in bot_settings.get("guilds", {}):
        return bot_settings["guilds"][str(guild.id)]

    default = bot_settings.get("default_lang")
    if default and default in all_langs:
        return default

    autostart = os.getenv("AUTOSTART_LANG")
    if autostart:
        return LANG_MAP.get(str(autostart).lower(), 'en')

    return 'pt'


def get_txts(guild_or_ctx=None):
    code = get_lang_code(guild_or_ctx)
    base = dict(all_langs.get('en', {}))
    base.update(all_langs.get(code, {}))
    return base


def set_permanent_lang(lang_code, guild=None):
    if "guilds" not in bot_settings or not isinstance(bot_settings["guilds"], dict):
        bot_settings["guilds"] = {}
    if guild:
        bot_settings["guilds"][str(guild.id)] = lang_code
    bot_settings["default_lang"] = lang_code
    save_settings(bot_settings)
    txts.clear()
    txts.update(get_txts())


async def check_admin_or_mod(ctx):
    # Bot owner always has permission
    try:
        if await ctx.bot.is_owner(ctx.author):
            return True
    except Exception:
        pass

    if not ctx.guild:
        return False

    # Server owner
    if ctx.author == ctx.guild.owner:
        return True

    # Guild permissions check
    perms = ctx.author.guild_permissions
    if (
        perms.administrator
        or perms.manage_guild
        or perms.moderate_members
        or perms.manage_messages
        or perms.manage_roles
        or perms.kick_members
        or perms.ban_members
    ):
        return True

    # Mod/Admin roles check
    mod_keywords = {"admin", "administrador", "administrator", "mod", "moderador", "moderator"}
    for role in getattr(ctx.author, "roles", []):
        r_name = role.name.lower().strip()
        if r_name in mod_keywords or any(k in r_name for k in mod_keywords):
            return True

    return False


def _make_progress_hook(status_msg, loop):
    """Return a yt-dlp progress hook that edits *status_msg* with a progress bar."""
    last_update = [0]  # mutable closure for throttle

    def hook(d):
        nonlocal last_update
        status = d.get('status')

        if status == 'finished':
            t = get_txts(status_msg.guild if status_msg else None)
            # show 100% briefly before the function returns
            asyncio.run_coroutine_threadsafe(
                status_msg.edit(content=f"`[{'█' * 20}]` 100% · {t.get('download_finished', 'download finished')}"),
                loop,
            )
            return

        if status != 'downloading':
            return

        now = time.time()
        if now - last_update[0] < 1.2:  # throttle edits to avoid rate limits
            return
        last_update[0] = now

        total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
        downloaded = d.get('downloaded_bytes', 0)

        if total > 0:
            pct = downloaded / total
            bar_len = 20
            filled = int(bar_len * pct)
            bar = '█' * filled + '░' * (bar_len - filled)
            pct_str = f"{pct * 100:.0f}%"
        else:
            bar = '░' * 20
            pct_str = "?%"

        speed = d.get('speed') or 0
        if speed:
            if speed >= 1024 * 1024:
                speed_str = f"{speed / 1024 / 1024:.1f} MB/s"
            else:
                speed_str = f"{speed / 1024:.0f} KB/s"
        else:
            speed_str = "? KB/s"

        eta = d.get('eta') or 0
        eta_str = f"{eta // 60}:{eta % 60:02d}" if eta else "?:??"

        text = f"`[{bar}]` {pct_str}  ·  {speed_str}  ·  ETA {eta_str}"
        asyncio.run_coroutine_threadsafe(status_msg.edit(content=text), loop)

    return hook


async def download_music(vid_id, status_msg=None):
    music_path = os.path.join(PP_PATH, f"music{vid_id}.mp3")
    if os.path.exists(music_path):
        os.remove(music_path)

    ydl_opts = {
        **YTDL_OPTS,
        'format': 'bestaudio/best',
        'outtmpl': os.path.join(PP_PATH, f"music{vid_id}.%(ext)s"),
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '0',
        }],
        'quiet': True,
    }
    # Use ios/tv/mweb clients to bypass SABR with cookies (android doesn't support cookies)
    ydl_opts['extractor_args'] = {'youtube': {'player_client': ['ios', 'tv', 'mweb', 'web']}}

    loop = asyncio.get_event_loop()

    if status_msg:
        ydl_opts['progress_hooks'] = [_make_progress_hook(status_msg, loop)]

    def run_dl():
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([f"https://youtube.com/watch?v={vid_id}"])

    await loop.run_in_executor(None, run_dl)


async def download_music_url(file_id, url, status_msg=None):
    music_path = os.path.join(PP_PATH, f"music{file_id}.mp3")
    if os.path.exists(music_path):
        os.remove(music_path)

    ydl_opts = {
        **YTDL_OPTS,
        'format': 'bestaudio/best',
        'outtmpl': os.path.join(PP_PATH, f"music{file_id}.%(ext)s"),
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '0',
        }],
        'quiet': True,
    }
    # Use ios/tv/mweb clients to bypass SABR with cookies (android doesn't support cookies)
    ydl_opts['extractor_args'] = {'youtube': {'player_client': ['ios', 'tv', 'mweb', 'web']}}

    loop = asyncio.get_event_loop()

    if status_msg:
        ydl_opts['progress_hooks'] = [_make_progress_hook(status_msg, loop)]

    def run_dl():
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

    await loop.run_in_executor(None, run_dl)


async def _download_playlist(vc, vid_ids):
    for i, vid_id in enumerate(vid_ids):
        if vid_id not in queue_to_play:
            continue  # was removed from queue, skip
        await download_music(vid_id)
        # after first song is ready, kick off playback if nothing is playing
        if i == 0 and vc and not vc.is_playing():
            await play_next(vc)


async def play_next(vc):
    if not queue_to_play:
        return

    vid_id     = queue_to_play[0]
    music_path = os.path.join(PP_PATH, f"music{vid_id}.mp3")

    waited = 0
    while not os.path.exists(music_path) and waited < 120:
        await asyncio.sleep(2)
        waited += 2

    if not os.path.exists(music_path):
        await download_music(vid_id)

    print(f"[play_next] file={music_path}  size={os.path.getsize(music_path)}  vc_connected={vc.is_connected()}")

    def after_playing(error):
        if error:
            print(f"[after_playing] ERROR: {error}")
        else:
            print(f"[after_playing] finished normally: {vid_id}")
        finished_vid = queue_to_play.pop(0) if queue_to_play else None
        if finished_vid:
            finished_at[finished_vid] = datetime.now()
        if queue_to_play:
            asyncio.run_coroutine_threadsafe(play_next(vc), bot.loop)

    # -nostdin: prevent ffmpeg from reading stdin (can hang otherwise)
    # -vn:      skip embedded album art / video streams in the mp3
    vc.play(discord.FFmpegOpusAudio(music_path, before_options="-nostdin -vn"), after=after_playing)


@bot.command()
async def test(ctx):
    """Play a 3-second 440 Hz test tone — verifies the audio pipeline."""
    t = get_txts(ctx)
    vc = ctx.voice_client
    if not vc:
        if ctx.author.voice:
            vc = await ctx.author.voice.channel.connect()
        else:
            await ctx.send(t.get('not_in_vc', "Join a voice channel first."))
            return

    if vc.is_playing():
        vc.stop()
        await asyncio.sleep(0.3)

    # generate a pure sine wave via ffmpeg's lavfi filter — no file needed
    vc.play(
        discord.FFmpegPCMAudio(
            "sine=frequency=440:duration=3",
            before_options="-f lavfi -nostdin",
        ),
        after=lambda e: print(f"[test] done, error={e}"),
    )
    await ctx.send("Playing test tone (440 Hz, 3 sec) — can you hear it?")


@bot.command()
async def howto(ctx):
    t = get_txts(ctx)
    await ctx.send(
        f"**{t['commands']}:**\n"
        f"`!j yt <{t['searching']}>` — {t['slash_yt']}\n"
        f"`!j ytlink <url>` — {t['slash_ytlink']}\n"
        f"`!j link <url>` — {t['slash_link']}\n"
        f"`!j playlist <url>` — {t['slash_playlist']}\n"
        f"`!j play` — {t['slash_play']}\n"
        f"`!j pause` — {t['slash_pause']}\n"
        f"`!j skip` — {t['slash_skip']}\n"
        f"`!j stop` — {t['slash_stop']}\n"
        f"`!j list` — {t['slash_list']}\n"
        f"`!j remove <n>` — {t['slash_remove']}\n"
        f"`!j clean` — {t['slash_clean']}\n"
        f"`!j lang [código]` — {t.get('slash_lang', 'define ou exibe o idioma permanente do bot')}\n"
        f"`!j howto` — {t['slash_howto']}"
    )


@bot.command(name="lang", aliases=["language", "setlang", "idioma", "setidioma"])
async def lang(ctx, *, arg: str = None):
    t = get_txts(ctx)

    if not arg:
        current_code = get_lang_code(ctx)
        current_display = f"{LANG_NAMES.get(current_code, current_code)} (`{current_code}`)"
        langs_list = "\n".join([
            f"`{num}` - {LANG_NAMES[code]} (`{code}`)"
            for num, code in [
                ("1", "en"), ("2", "pt"), ("3", "fr"), ("4", "es"), ("5", "ru"), ("6", "cn"), ("7", "ar")
            ]
        ])
        msg = (
            f"🌐 **{t.get('current_lang', 'Idioma atual')}**: {current_display}\n\n"
            f"📋 **{t.get('available_langs', 'Idiomas disponíveis')}**:\n{langs_list}\n\n"
            f"{t.get('lang_usage', 'Use `!j lang <código ou número>` para alterar.')}"
        )
        await ctx.send(msg)
        return

    # Check permission: Only admins or mods can change the language
    if not await check_admin_or_mod(ctx):
        await ctx.send(f"❌ {t.get('no_permission', 'Apenas administradores ou moderadores podem alterar o idioma do bot.')}")
        return

    arg_clean = arg.strip().lower()
    target_code = LANG_MAP.get(arg_clean)

    if not target_code or target_code not in all_langs:
        valid_codes = ", ".join([f"`{code}`" for code in LANG_NAMES.keys()])
        await ctx.send(f"❌ {t.get('invalid_lang', 'Idioma inválido.')} ({valid_codes} / 1-7)")
        return

    set_permanent_lang(target_code, ctx.guild)
    new_t = get_txts(ctx)
    lang_display = f"{LANG_NAMES.get(target_code, target_code)} (`{target_code}`)"

    msg_template = new_t.get('lang_changed', 'Idioma alterado com sucesso para {lang}! Salvo permanentemente.')
    await ctx.send(f"✅ {msg_template.format(lang=lang_display)}")



@bot.command()
async def playlist(ctx, url: str):
    t = get_txts(ctx)
    await ctx.send(t['extracting_playlist'])

    ydl_opts = {**YTDL_OPTS, "quiet": True}
    loop = asyncio.get_event_loop()

    def fetch():
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            return ydl.extract_info(url, download=False)

    try:
        info = await loop.run_in_executor(None, fetch)
    except Exception as e:
        await ctx.send(f"{t['error_extracting_playlist']}: {e}")
        return

    entries = info.get("entries") or []
    if not entries:
        await ctx.send(t['empty_null_playlist'])
        return

    playlist_ids = []
    for entry in entries:
        vid_id   = entry.get("id")
        title    = entry.get("title", "???")
        uploader = entry.get("uploader", "???")
        if not vid_id:
            continue
        display = (
            f"{str(title).replace('[','').replace(']','')} - "
            f"({str(uploader).replace('[','').replace(']','')}) [{vid_id}]"
        )
        queue.append(display)
        queue_to_play.append(vid_id)
        playlist_ids.append(vid_id)

    if not playlist_ids:
        await ctx.send(t['null_music_found'])
        return

    await ctx.send(f"{len(playlist_ids)} {t['num_music_added']}")

    vc = ctx.voice_client
    if not vc and ctx.author.voice:
        vc = await ctx.author.voice.channel.connect()

    asyncio.create_task(_download_playlist(vc, playlist_ids))


@bot.command()
async def ytlink(ctx, url: str):
    t = get_txts(ctx)
    await ctx.send(t['extract_link_info'])

    loop = asyncio.get_event_loop()

    def fetch():
        with yt_dlp.YoutubeDL({**YTDL_OPTS,"quiet": True}) as ydl:
            return ydl.extract_info(url, download=False)

    try:
        info = await loop.run_in_executor(None, fetch)
    except Exception as e:
        await ctx.send(f"{t['extract_link_info_error']}: {e}")
        return

    vid_id   = info.get("id")
    title    = info.get("title", "???")
    uploader = info.get("uploader", "???")

    if not vid_id:
        await ctx.send(t['cant_get_vid_id'])
        return

    display = (
        f"{str(title).replace('[','').replace(']','')} - "
        f"({str(uploader).replace('[','').replace(']','')}) [{vid_id}]"
    )
    queue.append(display)
    queue_to_play.append(vid_id)

    status_msg = await ctx.send(f"{t['added']}: '{display}'\n{t['downloading']}...")
    await download_music(vid_id, status_msg=status_msg)

    vc = ctx.voice_client
    if not vc and ctx.author.voice:
        vc = await ctx.author.voice.channel.connect()
    if vc and not vc.is_playing():
        await play_next(vc)


@bot.command()
async def link(ctx, url: str):
    t = get_txts(ctx)
    await ctx.send(t['extract_link_info'])

    loop = asyncio.get_event_loop()

    def fetch():
        with yt_dlp.YoutubeDL({"quiet": True}) as ydl:
            return ydl.extract_info(url, download=False)

    try:
        info = await loop.run_in_executor(None, fetch)
    except Exception as e:
        await ctx.send(f"{t['error']}: {e}")
        return

    title    = info.get("title", "???")
    uploader = info.get("uploader", "???")
    file_id  = hashlib.md5(url.encode()).hexdigest()[:12]

    display = (
        f"{str(title).replace('[','').replace(']','')} - "
        f"({str(uploader).replace('[','').replace(']','')}) [{file_id}]"
    )
    queue.append(display)
    queue_to_play.append(file_id)

    status_msg = await ctx.send(f"{t['added']}: '{display}'\n{t['downloading']}...")
    await download_music_url(file_id, url, status_msg=status_msg)

    vc = ctx.voice_client
    if not vc and ctx.author.voice:
        vc = await ctx.author.voice.channel.connect()
    if vc and not vc.is_playing():
        await play_next(vc)


@bot.command()
async def remove(ctx, pos: int):
    t = get_txts(ctx)
    if not queue_to_play:
        await ctx.send(t['empty_queue'])
        return

    if pos < 1 or pos > len(queue_to_play):
        await ctx.send(f"{t['invalid_num_mus_sel_1']} {len(queue_to_play)} {t['invalid_num_mus_sel_2']}")
        return

    idx = pos - 1
    vid_id = queue_to_play[idx]

    queue_to_play.pop(idx)
    if idx < len(queue):
        queue.pop(idx)

    finished_at[vid_id] = datetime.now()  # schedule file for cleanup
    await ctx.send(f"{t['removed_from_pos']} {pos}")

    # if was currently playing, stop it (after_playing will chain next)
    if idx == 0:
        vc = ctx.voice_client
        if vc and (vc.is_playing() or vc.is_paused()):
            vc.stop()


@bot.command()
async def clean(ctx):
    t = get_txts(ctx)
    vc = ctx.voice_client
    if vc and (vc.is_playing() or vc.is_paused()):
        vc.stop()

    for vid_id in queue_to_play:
        finished_at[vid_id] = datetime.now()  # schedule all files for cleanup

    queue.clear()
    queue_to_play.clear()
    await ctx.send(t['clear_queue'])


@bot.command()
async def play(ctx):
    t = get_txts(ctx)
    vc = ctx.voice_client
    if not vc:
        if ctx.author.voice:
            vc = await ctx.author.voice.channel.connect()
        else:
            await ctx.send(t['not_in_vc'])
            return

    if vc.is_playing():
        await ctx.send(t['something_playing'])
        return

    if not queue_to_play:
        await ctx.send(t['nothing_to_play'])
        return

    await play_next(vc)


@bot.command()
async def skip(ctx):
    t = get_txts(ctx)
    vc = ctx.voice_client
    if not vc or (not vc.is_playing() and not vc.is_paused()):
        await ctx.send(t['nothing_playing'])
        return
    vc.stop()  # triggers after_playing, which chains next song
    await ctx.send(t['skipping'])


@bot.command()
async def pause(ctx):
    t = get_txts(ctx)
    vc = ctx.voice_client
    if not vc:
        await ctx.send(t['nothing_playing'])
        return
    if vc.is_playing():
        vc.pause()
        await ctx.send(t['paused'])
    elif vc.is_paused():
        vc.resume()
        await ctx.send(t['resume'])
    else:
        await ctx.send(t['nothing_playing'])


@bot.command()
async def stop(ctx):
    if ctx.voice_client:
        await ctx.voice_client.disconnect()


@bot.command()
async def list(ctx):
    t = get_txts(ctx)
    if queue_to_play:
        linhas = [f"({i}) - {entry}" for i, entry in enumerate(queue, 1)]
        await ctx.send(f"{t['list']}:\n" + "\n".join(linhas))
    else:
        await ctx.send(t['empty_queue'])


@bot.command()
async def yt(ctx, *, arg):
    t = get_txts(ctx)
    await ctx.send(f'{t["searching"]}: "{arg}" ...')

    ydl_opts = {**YTDL_OPTS, "quiet": True, "extract_flat": True}
    lista_pesq = []

    loop = asyncio.get_event_loop()

    def search():
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            return ydl.extract_info(f"ytsearch5:{arg}", download=False)

    info = await loop.run_in_executor(None, search)

    for i, entry in enumerate(info["entries"], 1):
        title    = entry.get("title")
        uploader = entry.get("uploader")
        vid_id   = entry.get("id")
        lista_pesq.append(
            f"({str(i).replace('[','').replace(']','')}) - "
            f"{str(title).replace('[','').replace(']','')} - "
            f"({str(uploader).replace('[','').replace(']','')}) [{vid_id}]"
        )
    
    await ctx.send(f"{t['search_result']}:\n" + "\n".join(lista_pesq) + f"\n{t['type_num_add']}")

    def check(message):
        return message.author == ctx.author and message.channel == ctx.channel

    try:
        msg = await bot.wait_for("message", check=check, timeout=30)
    except:
        await ctx.send(t['ignored_call_me_later'])
        return

    argi = msg.content.strip()

    if argi in ['1', '2', '3', '4', '5']:
        nsel   = int(argi) - 1
        vsel   = lista_pesq[nsel]
        vid_id = vsel.split("[")[1].rstrip("]")

        queue.append(vsel)
        queue_to_play.append(vid_id)
        status_msg = await ctx.send(f"{t['downloading']}: '{vsel}'...")

        await download_music(vid_id, status_msg=status_msg)

        # auto-play if in a voice channel and nothing is playing
        vc = ctx.voice_client
        if not vc and ctx.author.voice:
            vc = await ctx.author.voice.channel.connect()
        if vc and not vc.is_playing():
            await play_next(vc)

    elif argi.lower() in t['skip_commands']:
        await ctx.send(t['skipping'])
    else:
        await ctx.send(t['wrong_command'])


@tasks.loop(minutes=1)
async def check_afk():
    for guild in bot.guilds:
        vc = guild.voice_client

        if vc:
            if not vc.is_playing():
                vc.afk_time = getattr(vc, "afk_time", 0) + 1
            else:
                vc.afk_time = 0

            if vc.afk_time >= 10:
                channel = guild.system_channel
                if channel:
                    t = get_txts(guild)
                    await channel.send(t['disconnect_inactive'])
                await vc.disconnect()


@tasks.loop(minutes=1)
async def cleanup_old_music():
    cutoff = datetime.now() - timedelta(minutes=30)
    to_delete = [vid_id for vid_id, t in finished_at.items() if t < cutoff]
    for vid_id in to_delete:
        music_path = os.path.join(PP_PATH, f"music{vid_id}.mp3")
        if os.path.exists(music_path):
            os.remove(music_path)
            print(f"{txts.get('removed', 'removed')}: music{vid_id}.mp3")
        finished_at.pop(vid_id, None)


@bot.event
async def on_ready():
    cleanup_old_music.start()
    check_afk.start()
    print(f"{txts.get('bot_online', 'bot online')}: {bot.user}")


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        t = get_txts(ctx)
        await ctx.send(t.get('command_unknown', 'command does not exist'))


if __name__ == '__main__':

    load_dotenv()
    
    bot_token = os.getenv("BOT_TOKEN") or None
    autostart_lang = os.getenv("AUTOSTART_LANG") or 0
    jsrun = os.getenv("JSRUNTIME") or ''
    cookies = os.getenv("COOKIES") or 0
    verbose = os.getenv("VERBOSE") or 0

    if not bot_token:
        raise ValueError("BOT_TOKEN is not set. \nCreate a .env file, and paste your bot token like 'BOT_TOKEN = \"123456...\"'.")

    # Determine default language:
    # 1. Saved settings (settings.json)
    # 2. AUTOSTART_LANG in .env (if set)
    # 3. Fallback to 'pt' without blocking so the bot starts and admins/mods can change via Discord command (!j lang)
    saved_lang = bot_settings.get("default_lang")
    if saved_lang and saved_lang in all_langs:
        lang_code = saved_lang
        print(f"[lang] Idioma permanente carregado: {lang_code} ({LANG_NAMES.get(lang_code, lang_code)})")
    elif autostart_lang:
        lang_code = LANG_MAP.get(str(autostart_lang).lower(), 'pt')
        set_permanent_lang(lang_code)
        print(f"[lang] Idioma inicializado via AUTOSTART_LANG: {lang_code} ({LANG_NAMES.get(lang_code, lang_code)})")
    else:
        lang_code = 'pt'
        set_permanent_lang(lang_code)
        print(f"[lang] Nenhum idioma permanente configurado. Padrão inicial: {lang_code} ({LANG_NAMES.get(lang_code, lang_code)})")
        print("[lang] Admins/mods podem alterar o idioma permanentemente no Discord via '!j lang <idioma>'.")

    txts.clear()
    txts.update(get_txts())

    if verbose:
        YTDL_OPTS["verbose"] = True

    if jsrun:
        YTDL_OPTS["js_runtimes"] = {"node": {"path": jsrun}}
        YTDL_OPTS["remote_components"] = {'ejs:github'}

    if cookies:
        # If it looks like a file path (contains separator or .txt), use cookiefile
        if os.path.sep in cookies or cookies.endswith('.txt'):
            YTDL_OPTS["cookiefile"] = cookies
            print(f"[cookies] using cookiefile: {cookies}")
        else:
            # Browser name given (e.g. "chrome") — extract cookies to a file first.
            # This is more reliable than cookiesfrombrowser, especially on Linux.
            print(f"[cookies] extracting from browser: {cookies} ...")
            extracted = _extract_chrome_cookies()
            if extracted:
                YTDL_OPTS["cookiefile"] = extracted
            else:
                # fallback: let yt-dlp try cookiesfrombrowser directly
                print(f"[cookies] extraction failed, falling back to cookiesfrombrowser")
                YTDL_OPTS["cookiesfrombrowser"] = (cookies,)
    else:
        # fallback: look for cookies.txt in the bot directory
        default_cookies = os.path.join(PP_PATH, "cookies.txt")
        if os.path.exists(default_cookies):
            YTDL_OPTS["cookiefile"] = default_cookies
            print(f"[cookies] using default cookiefile: {default_cookies}")
        else:
            # try to extract from Chrome automatically
            print("[cookies] no COOKIES set — trying Chrome extraction ...")
            extracted = _extract_chrome_cookies()
            if extracted:
                YTDL_OPTS["cookiefile"] = extracted
            else:
                print("[cookies] NONE — YouTube will likely block audio downloads. "
                      "Log into YouTube in Chrome and restart the bot, or place cookies.txt next to bot.py.")
    
    print(YTDL_OPTS)
    bot.run(bot_token)
