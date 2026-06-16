import discord, yt_dlp, os, asyncio, hashlib, json
from datetime import datetime, timedelta
from discord.ext import commands, tasks
from dotenv import load_dotenv

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!j ", intents=intents)

PP_PATH = os.path.dirname(os.path.abspath(__file__))

YTDL_OPTS = {}

queue = []              # display strings
queue_to_play = []      # video IDs in play order
finished_at = {}        # vid_id -> datetime when it stopped playing (for cleanup)
txts = {}               # language strings


async def download_music(vid_id):
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

    loop = asyncio.get_event_loop()

    def run_dl():
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([f"https://youtube.com/watch?v={vid_id}"])

    await loop.run_in_executor(None, run_dl)


async def download_music_url(file_id, url):
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

    loop = asyncio.get_event_loop()

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

    def after_playing(error):
        if error:
            print(f"{txts['error']}: {error}")
        finished_vid = queue_to_play.pop(0) if queue_to_play else None
        if finished_vid:
            finished_at[finished_vid] = datetime.now()  # mark for cleanup
        if queue_to_play:
            asyncio.run_coroutine_threadsafe(play_next(vc), bot.loop)

    vc.play(discord.FFmpegPCMAudio(music_path), after=after_playing)


@bot.command()
async def howto(ctx):
    await ctx.send(
        f"**{txts['commands']}:**\n"
        f"`!j yt <{txts['searching']}>` — {txts['slash_yt']}\n"
        f"`!j ytlink <url>` — {txts['slash_ytlink']}\n"
        f"`!j link <url>` — {txts['slash_link']}\n"
        f"`!j playlist <url>` — {txts['slash_playlist']}\n"
        f"`!j play` — {txts['slash_play']}\n"
        f"`!j pause` — {txts['slash_pause']}\n"
        f"`!j skip` — {txts['slash_skip']}\n"
        f"`!j stop` — {txts['slash_stop']}\n"
        f"`!j list` — {txts['slash_list']}\n"
        f"`!j remove <n>` — {txts['slash_remove']}\n"
        f"`!j clean` — {txts['slash_clean']}\n"
        f"`!j howto` — {txts['slash_howto']}"
    )


@bot.command()
async def playlist(ctx, url: str):
    await ctx.send(txts['extracting_playlist'])

    ydl_opts = {**YTDL_OPTS, "quiet": True}
    loop = asyncio.get_event_loop()

    def fetch():
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            return ydl.extract_info(url, download=False)

    try:
        info = await loop.run_in_executor(None, fetch)
    except Exception as e:
        await ctx.send(f"{txts['error_extracting_playlist']}: {e}")
        return

    entries = info.get("entries") or []
    if not entries:
        await ctx.send(txts['empty_null_playlist'])
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
        await ctx.send(txts['null_music_found'])
        return

    await ctx.send(f"{len(playlist_ids)} {txts['num_music_added']}")

    vc = ctx.voice_client
    if not vc and ctx.author.voice:
        vc = await ctx.author.voice.channel.connect()

    asyncio.create_task(_download_playlist(vc, playlist_ids))


@bot.command()
async def ytlink(ctx, url: str):
    await ctx.send(txts['extract_link_info'])

    loop = asyncio.get_event_loop()

    def fetch():
        with yt_dlp.YoutubeDL({**YTDL_OPTS,"quiet": True}) as ydl:
            return ydl.extract_info(url, download=False)

    try:
        info = await loop.run_in_executor(None, fetch)
    except Exception as e:
        await ctx.send(f"{txts['extract_link_info_error']}: {e}")
        return

    vid_id   = info.get("id")
    title    = info.get("title", "???")
    uploader = info.get("uploader", "???")

    if not vid_id:
        await ctx.send(txts['cant_get_vid_id'])
        return

    display = (
        f"{str(title).replace('[','').replace(']','')} - "
        f"({str(uploader).replace('[','').replace(']','')}) [{vid_id}]"
    )
    queue.append(display)
    queue_to_play.append(vid_id)

    await ctx.send(f"{txts['added']}: '{display}'\n{txts['downloading']}...")
    await download_music(vid_id)
    await ctx.send(txts['download_finished'])

    vc = ctx.voice_client
    if not vc and ctx.author.voice:
        vc = await ctx.author.voice.channel.connect()
    if vc and not vc.is_playing():
        await play_next(vc)


@bot.command()
async def link(ctx, url: str):
    await ctx.send(txts['extract_link_info'])

    loop = asyncio.get_event_loop()

    def fetch():
        with yt_dlp.YoutubeDL({"quiet": True}) as ydl:
            return ydl.extract_info(url, download=False)

    try:
        info = await loop.run_in_executor(None, fetch)
    except Exception as e:
        await ctx.send(f"{txts['error']}: {e}")
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

    await ctx.send(f"{txts['added']}: '{display}'\n{txts['downloading']}...")
    await download_music_url(file_id, url)
    await ctx.send(txts['download_finished'])

    vc = ctx.voice_client
    if not vc and ctx.author.voice:
        vc = await ctx.author.voice.channel.connect()
    if vc and not vc.is_playing():
        await play_next(vc)


@bot.command()
async def remove(ctx, pos: int):
    if not queue_to_play:
        await ctx.send(txts['empty_queue'])
        return

    if pos < 1 or pos > len(queue_to_play):
        await ctx.send(f"{txts['invalid_num_mus_sel_1']} {len(queue_to_play)} {txts['invalid_num_mus_sel_2']}")
        return

    idx = pos - 1
    vid_id = queue_to_play[idx]

    queue_to_play.pop(idx)
    if idx < len(queue):
        queue.pop(idx)

    finished_at[vid_id] = datetime.now()  # schedule file for cleanup
    await ctx.send(f"{txts['removed_from_pos']} {pos}")

    # if was currently playing, stop it (after_playing will chain next)
    if idx == 0:
        vc = ctx.voice_client
        if vc and (vc.is_playing() or vc.is_paused()):
            vc.stop()


@bot.command()
async def clean(ctx):
    vc = ctx.voice_client
    if vc and (vc.is_playing() or vc.is_paused()):
        vc.stop()

    for vid_id in queue_to_play:
        finished_at[vid_id] = datetime.now()  # schedule all files for cleanup

    queue.clear()
    queue_to_play.clear()
    await ctx.send(txts['clear_queue'])


@bot.command()
async def play(ctx):
    vc = ctx.voice_client
    if not vc:
        if ctx.author.voice:
            vc = await ctx.author.voice.channel.connect()
        else:
            await ctx.send(txts['not_in_vc'])
            return

    if vc.is_playing():
        await ctx.send(txts['something_playing'])
        return

    if not queue_to_play:
        await ctx.send(txts['nothing_to_play'])
        return

    await play_next(vc)


@bot.command()
async def skip(ctx):
    vc = ctx.voice_client
    if not vc or (not vc.is_playing() and not vc.is_paused()):
        await ctx.send(txts['nothing_playing'])
        return
    vc.stop()  # triggers after_playing, which chains next song
    await ctx.send(txts['skipping'])


@bot.command()
async def pause(ctx):
    vc = ctx.voice_client
    if not vc:
        await ctx.send(txts['nothing_playing'])
        return
    if vc.is_playing():
        vc.pause()
        await ctx.send(txts['paused'])
    elif vc.is_paused():
        vc.resume()
        await ctx.send(txts['resume'])
    else:
        await ctx.send(txts['nothing_playing'])


@bot.command()
async def stop(ctx):
    if ctx.voice_client:
        await ctx.voice_client.disconnect()


@bot.command()
async def list(ctx):
    if queue_to_play:
        linhas = [f"({i}) - {entry}" for i, entry in enumerate(queue, 1)]
        await ctx.send(f"{txts['list']}:\n" + "\n".join(linhas))
    else:
        await ctx.send(txts['empty_queue'])


@bot.command()
async def yt(ctx, *, arg):
    await ctx.send(f'{txts["searching"]}: "{arg}" ...')

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
    
    await ctx.send(f"{txts['search_result']}:\n" + "\n".join(lista_pesq) + f"\n{txts['type_num_add']}")

    def check(message):
        return message.author == ctx.author and message.channel == ctx.channel

    try:
        msg = await bot.wait_for("message", check=check, timeout=30)
    except:
        await ctx.send(txts['ignored_call_me_later'])
        return

    argi = msg.content.strip()

    if argi in ['1', '2', '3', '4', '5']:
        nsel   = int(argi) - 1
        vsel   = lista_pesq[nsel]
        vid_id = vsel.split("[")[1].rstrip("]")

        queue.append(vsel)
        queue_to_play.append(vid_id)
        await ctx.send(f"{txts['downloading']}: '{vsel}'...")

        await download_music(vid_id)
        await ctx.send(txts['download_finished'])

        # auto-play if in a voice channel and nothing is playing
        vc = ctx.voice_client
        if not vc and ctx.author.voice:
            vc = await ctx.author.voice.channel.connect()
        if vc and not vc.is_playing():
            await play_next(vc)

    elif argi.lower() in txts['skip_commands']:
        await ctx.send(txts['skipping'])
    else:
        await ctx.send(txts['wrong_command'])


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
                    await channel.send(txts['disconnect_inactive'])
                await vc.disconnect()


@tasks.loop(minutes=1)
async def cleanup_old_music():
    cutoff = datetime.now() - timedelta(minutes=30)
    to_delete = [vid_id for vid_id, t in finished_at.items() if t < cutoff]
    for vid_id in to_delete:
        music_path = os.path.join(PP_PATH, f"music{vid_id}.mp3")
        if os.path.exists(music_path):
            os.remove(music_path)
            print(f"{txts['removed']}: music{vid_id}.mp3")
        finished_at.pop(vid_id, None)


@bot.event
async def on_ready():
    cleanup_old_music.start()
    check_afk.start()
    print(f"{txts['bot_online']}: {bot.user}")


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        await ctx.send(txts['command_unknown'])


if __name__ == '__main__':

    load_dotenv()
    
    bot_token = os.getenv("BOT_TOKEN") or None
    autostart_lang = os.getenv("AUTOSTART_LANG") or 0
    jsrun = os.getenv("JSRUNTIME") or ''
    cookies = os.getenv("COOKIES") or 0
    verbose = os.getenv("VERBOSE") or 0

    lang_map = {
        '1': 'en', '2': 'pt', '3': 'fr', '4': 'es', '5': 'ru', '6': 'cn', '7': 'ar'
    }

    if not bot_token:
        raise ValueError("BOT_TOKEN is not set. \nCreate a .env file, and paste your bot token like 'BOT_TOKEN = \"123456...\"'.")

    with open('lang.json', 'r', encoding='utf-8') as f:
        all_langs = json.load(f)

    if autostart_lang:
        lang_code = lang_map.get(autostart_lang, 'en')
        txts.update(all_langs[lang_code])
    else:
        print("Select language:")
        print("1 - English (en)\n2 - Português (pt)\n3 - Français (fr)\n4 - Español (es)\n5 - Русский (ru)\n6 - 中文 (cn)\n7 - العربية (ar)")
        choice = input("> ")
        lang_code = lang_map.get(choice, 'en')
        txts.update(all_langs[lang_code])

    if verbose:
        YTDL_OPTS["verbose"] = True

    if jsrun:
        YTDL_OPTS["js_runtimes"] = {"node": {"path": jsrun}}
        YTDL_OPTS["extractor_args"] = {"youtube": {"player_client": ["web"]}}
        YTDL_OPTS["remote_components"] = {'ejs:github'}

    if cookies:
        YTDL_OPTS["cookiesfrombrowser"] = (cookies,)
    
    print(YTDL_OPTS)
    bot.run(bot_token)
