import os, json, asyncio, requests, subprocess, time
from pathlib import Path
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# ─── CONFIG ───────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN  = os.getenv("TELEGRAM_TOKEN")
CHAT_ID         = int(os.getenv("CHAT_ID", "5432761536"))
GROK_API_KEY    = os.getenv("GROK_API_KEY")
IDEOGRAM_KEY    = os.getenv("IDEOGRAM_KEY")
STABILITY_KEY   = os.getenv("STABILITY_KEY")
FLUX_KEY        = os.getenv("FLUX_KEY")

IMAGES_FOLDER = "saved_images"
CLIPS_FOLDER  = "saved_clips"
STATE_FILE    = "state.json"
AUDIO_FILE    = "user_audio.mp3"
LIMITS_FILE   = "daily_limits.json"

os.makedirs(IMAGES_FOLDER, exist_ok=True)
os.makedirs(CLIPS_FOLDER, exist_ok=True)

# ─── DAILY LIMITS TRACKER ─────────────────────────────────────────────────────
def load_limits():
    today = time.strftime("%Y-%m-%d")
    if os.path.exists(LIMITS_FILE):
        with open(LIMITS_FILE) as f:
            data = json.load(f)
        if data.get("date") == today:
            return data
    # Reset for new day
    data = {
        "date": today,
        "grok": 0,       # limit: 50
        "ideogram": 0,   # limit: 10
        "stability": 0,  # limit: 25
        "flux": 0        # limit: 10
    }
    save_limits(data)
    return data

def save_limits(data):
    with open(LIMITS_FILE, "w") as f:
        json.dump(data, f)

DAILY_MAX = {"grok": 50, "ideogram": 10, "stability": 25, "flux": 10}

# ─── STATE ────────────────────────────────────────────────────────────────────
def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"current_title": "", "script": "", "image_prompts": [], "waiting_for_audio": False}

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

# ─── GROK SCRIPT ──────────────────────────────────────────────────────────────
def grok_script(title):
    prompt = f"""Tu ek expert Hindi YouTube scriptwriter hai finance niche ke liye.
Topic: {title}

8 minute ka script likh:
- Pehli line mein shocking money fact ya bold question — viewer ruk jaye
- Simple conversational Hindi, bilkul natural baat jaisi
- Real numbers aur Indian examples — actual rupee amounts, real companies
- 6 strong points, har ek valuable aur interesting
- Beech beech mein curiosity — viewer skip na kare
- Last mein strong CTA — subscribe, comment karo
- Total 950-1050 words, sirf script, koi explanation nahi"""

    r = requests.post(
        "https://api.x.ai/v1/chat/completions",
        headers={"Authorization": f"Bearer {GROK_API_KEY}", "Content-Type": "application/json"},
        json={"model": "grok-3", "messages": [{"role": "user", "content": prompt}], "max_tokens": 2000}
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]

# ─── GROK SEO ─────────────────────────────────────────────────────────────────
def grok_seo(title, script):
    prompt = f"""YouTube Finance channel SEO pack bana.
Title: {title}
Script start: {script[:300]}

Format exactly aisa:

OPTIMIZED TITLE:
[60 chars max, Hindi, number use karo, curiosity create karo]

DESCRIPTION:
[800 words, Hindi+English mix, pehle 150 chars mein keyword, timestamps, about channel]

TAGS:
[30 tags, comma separated, Hindi aur English dono]

HASHTAGS:
[15 hashtags]

THUMBNAIL TEXT:
[5 words max bold text]"""

    r = requests.post(
        "https://api.x.ai/v1/chat/completions",
        headers={"Authorization": f"Bearer {GROK_API_KEY}", "Content-Type": "application/json"},
        json={"model": "grok-3", "messages": [{"role": "user", "content": prompt}], "max_tokens": 1500}
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]

# ─── IMAGE GENERATION — AUTO SWITCH ───────────────────────────────────────────
def generate_image(prompt, filepath):
    limits = load_limits()

    # 1. Try Grok first
    if limits["grok"] < DAILY_MAX["grok"]:
        try:
            r = requests.post(
                "https://api.x.ai/v1/images/generations",
                headers={"Authorization": f"Bearer {GROK_API_KEY}", "Content-Type": "application/json"},
                json={"model": "grok-2-image", "prompt": prompt, "n": 1},
                timeout=60
            )
            r.raise_for_status()
            url = r.json()["data"][0]["url"]
            img = requests.get(url).content
            with open(filepath, "wb") as f:
                f.write(img)
            limits["grok"] += 1
            save_limits(limits)
            return "grok"
        except:
            pass

    # 2. Try Ideogram
    if limits["ideogram"] < DAILY_MAX["ideogram"]:
        try:
            r = requests.post(
                "https://api.ideogram.ai/generate",
                headers={"Api-Key": IDEOGRAM_KEY, "Content-Type": "application/json"},
                json={
                    "image_request": {
                        "prompt": prompt,
                        "aspect_ratio": "ASPECT_16_9",
                        "model": "V_2",
                        "magic_prompt_option": "ON"
                    }
                },
                timeout=60
            )
            r.raise_for_status()
            url = r.json()["data"][0]["url"]
            img = requests.get(url).content
            with open(filepath, "wb") as f:
                f.write(img)
            limits["ideogram"] += 1
            save_limits(limits)
            return "ideogram"
        except:
            pass

    # 3. Try Stability AI
    if limits["stability"] < DAILY_MAX["stability"]:
        try:
            r = requests.post(
                "https://api.stability.ai/v2beta/stable-image/generate/core",
                headers={"Authorization": f"Bearer {STABILITY_KEY}", "Accept": "image/*"},
                files={"none": ""},
                data={"prompt": prompt, "aspect_ratio": "16:9", "output_format": "jpeg"},
                timeout=60
            )
            r.raise_for_status()
            with open(filepath, "wb") as f:
                f.write(r.content)
            limits["stability"] += 1
            save_limits(limits)
            return "stability"
        except:
            pass

    # 4. Try Flux
    if FLUX_KEY and limits["flux"] < DAILY_MAX["flux"]:
        try:
            r = requests.post(
                "https://api.bfl.ml/v1/flux-pro-1.1",
                headers={"x-key": FLUX_KEY, "Content-Type": "application/json"},
                json={"prompt": prompt, "width": 1280, "height": 720},
                timeout=30
            )
            r.raise_for_status()
            task_id = r.json()["id"]
            # Poll for result
            for _ in range(30):
                time.sleep(3)
                poll = requests.get(
                    f"https://api.bfl.ml/v1/get_result?id={task_id}",
                    headers={"x-key": FLUX_KEY}
                )
                result = poll.json()
                if result.get("status") == "Ready":
                    url = result["result"]["sample"]
                    img = requests.get(url).content
                    with open(filepath, "wb") as f:
                        f.write(img)
                    limits["flux"] += 1
                    save_limits(limits)
                    return "flux"
        except:
            pass

    return None  # Sab limits khatam

# ─── GROK VIDEO CLIPS ─────────────────────────────────────────────────────────
def generate_clip(prompt, filepath):
    try:
        r = requests.post(
            "https://api.x.ai/v1/videos/generations",
            headers={"Authorization": f"Bearer {GROK_API_KEY}", "Content-Type": "application/json"},
            json={"model": "grok-2-video", "prompt": prompt, "n": 1},
            timeout=120
        )
        r.raise_for_status()
        url = r.json()["data"][0]["url"]
        video = requests.get(url).content
        with open(filepath, "wb") as f:
            f.write(video)
        return True
    except:
        return False

# ─── IMAGE PROMPTS FOR FINANCE ─────────────────────────────────────────────────
def make_prompts(title, count=95):
    base = [
        "Stack of Indian rupee notes with dramatic golden light, dark background, cinematic, no text",
        "Person watching stock market graphs on laptop at night, dramatic lighting, finance aesthetic",
        "Gold coins and bars on black surface, luxury finance, ultra HD, no text",
        "Wealthy mansion with luxury car at night, aspirational lifestyle, cinematic shot",
        "Indian stock exchange BSE building, dramatic sky, professional photography",
        "Piggy bank overflowing with coins, savings concept, dramatic lighting",
        "Person celebrating financial success, city skyline background, golden hour",
        "Close up of mutual fund app on phone showing profits, green numbers",
        "Bar chart showing wealth growth, glowing lines, dark background, data visualization",
        "Businessman walking in financial district Mumbai, confident, cinematic",
        "Safe vault opening with golden light inside, wealth concept, dramatic",
        "Exponential growth graph glowing on dark screen, finance data",
        "Two paths diverging - one showing wealth one showing struggle, symbolic",
        "Clock with money coins around it, time value of money concept",
        "Person reading financial newspaper morning coffee, lifestyle",
        "Bank building grand pillars golden hour, trust and stability",
        "Investment portfolio tablet screen close up, numbers and charts",
        "Money rain falling, abundance concept, artistic dramatic",
        "Calculator financial documents premium desk setup, professional",
        "Rupee symbol made of gold on black background, luxury finance",
    ]
    result = []
    for i in range(count):
        scene = base[i % len(base)]
        result.append(f"{scene}, related to {title}, finance YouTube video visual")
    return result

def make_clip_prompts(title):
    return [
        f"Dramatic cinematic shot of Indian rupee notes flying, related to {title}, 4K gold dark theme",
        f"Stock market graphs moving up dramatically, green numbers, cinematic finance, {title}",
        f"Luxury lifestyle montage, mansion car wealth, aspirational, dark gold aesthetic, {title}",
        f"Person opening laptop seeing investment profits, smiling, realistic cinematic, {title}",
        f"Gold bars stacked dramatically with spotlight, wealth concept cinematic, {title}",
        f"Time lapse of city financial district at night lights, Mumbai skyline, {title}",
        f"Coins falling into piggy bank slow motion, savings investment, dramatic, {title}",
        f"Person signing important financial document at premium desk, success, {title}",
        f"Stock ticker numbers flowing, financial data stream, cinematic dark theme, {title}",
        f"Sunrise over financial district, new opportunity concept, cinematic, {title}",
    ]

# ─── VIDEO ASSEMBLY ───────────────────────────────────────────────────────────
def assemble_video(audio_path, output="final_video.mp4"):
    clips = sorted(Path(CLIPS_FOLDER).glob("clip_*.mp4"))
    images = sorted(Path(IMAGES_FOLDER).glob("img_*.jpg"))

    concat_file = "concat_list.txt"
    with open(concat_file, "w") as f:
        for clip in clips:
            f.write(f"file '{clip.absolute()}'\n")
        for img in images:
            f.write(f"file '{img.absolute()}'\n")
            f.write("duration 3\n")
        if images:
            f.write(f"file '{images[-1].absolute()}'\n")

    # With zoom pan effect
    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0", "-i", concat_file,
        "-i", audio_path,
        "-vf", (
            "scale=1920:1080:force_original_aspect_ratio=decrease,"
            "pad=1920:1080:(ow-iw)/2:(oh-ih)/2:black,"
            "zoompan=z='if(lte(zoom,1.0),1.04,max(1.001,zoom-0.0004))':d=90:s=1920x1080,"
            "format=yuv420p"
        ),
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest", output
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        # Simple fallback
        cmd2 = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0", "-i", concat_file,
            "-i", audio_path,
            "-vf", "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:black,format=yuv420p",
            "-c:v", "libx264", "-preset", "fast", "-crf", "20",
            "-c:a", "aac", "-b:a", "192k",
            "-shortest", output
        ]
        subprocess.run(cmd2, check=True)

    return output

# ─── TELEGRAM HANDLERS ────────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != CHAT_ID:
        return
    await update.message.reply_text(
        "🎬 Finance YT Bot Ready!\n\n"
        "Commands:\n"
        "/video [title] — Script lao aur generation shuru karo\n"
        "/status — Kitni images ban gayi check karo\n"
        "/makevideo — Jab audio bhejo tab manually video banao\n\n"
        "Flow:\n"
        "1️⃣ /video title bhejo → Script aayegi\n"
        "2️⃣ Voiceover record karke audio bhejo\n"
        "3️⃣ Bot 95 images ek din mein banayega\n"
        "4️⃣ Video + SEO pack automatically Telegram pe aayega"
    )

async def video_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != CHAT_ID:
        return

    title = " ".join(context.args)
    if not title:
        await update.message.reply_text(
            "❌ Title do!\nExample:\n/video Har Mahine 50000 Kaise Bachayein 2025"
        )
        return

    await update.message.reply_text(f"✍️ Script likh raha hoon...\n📌 {title}")

    try:
        script = grok_script(title)

        # Clear old data
        for f in Path(IMAGES_FOLDER).glob("*"):
            f.unlink()
        for f in Path(CLIPS_FOLDER).glob("*"):
            f.unlink()
        if os.path.exists(AUDIO_FILE):
            os.remove(AUDIO_FILE)

        state = {
            "current_title": title,
            "script": script,
            "image_prompts": make_prompts(title, 95),
            "clip_prompts": make_clip_prompts(title),
            "waiting_for_audio": True
        }
        save_state(state)

        # Send script in parts
        await update.message.reply_text(script[:4000])
        if len(script) > 4000:
            await update.message.reply_text(script[4000:])

        await update.message.reply_text(
            "✅ Script ready!\n\n"
            "🎙️ Ab yeh karo:\n"
            "Voiceover record karo aur audio file yahan bhejo\n"
            "(MP3, M4A, ya voice message — kuch bhi chalega)\n\n"
            "Audio aate hi images generate hona shuru ho jayengi!"
        )

    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != CHAT_ID:
        return

    state = load_state()
    limits = load_limits()
    images = len(list(Path(IMAGES_FOLDER).glob("img_*.jpg")))
    clips = len(list(Path(CLIPS_FOLDER).glob("clip_*.mp4")))
    audio = "✅ Mil gaya" if os.path.exists(AUDIO_FILE) else "❌ Nahi aaya"

    remaining = {k: DAILY_MAX[k] - limits[k] for k in DAILY_MAX}

    await update.message.reply_text(
        f"📊 Status:\n\n"
        f"📌 Title: {state.get('current_title', 'Koi nahi')}\n"
        f"🖼️ Images: {images}/95\n"
        f"🎬 Clips: {clips}/10\n"
        f"🎙️ Audio: {audio}\n\n"
        f"📈 Aaj baki limits:\n"
        f"Grok: {remaining['grok']} images\n"
        f"Ideogram: {remaining['ideogram']} images\n"
        f"Stability: {remaining['stability']} images\n"
        f"Flux: {remaining['flux']} images\n\n"
        f"{'🔄 Generate chal raha hai...' if images < 95 else '✅ Sab ready! /makevideo karo'}"
    )

async def handle_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != CHAT_ID:
        return

    state = load_state()
    if not state.get("current_title"):
        await update.message.reply_text("Pehle /video [title] do!")
        return

    await update.message.reply_text("⬇️ Audio download ho raha hai...")

    audio = update.message.audio or update.message.voice or update.message.document
    if not audio:
        await update.message.reply_text("❌ Audio nahi mili. MP3 ya voice message bhejo.")
        return

    file = await context.bot.get_file(audio.file_id)
    await file.download_to_drive(AUDIO_FILE)

    state["waiting_for_audio"] = False
    save_state(state)

    await update.message.reply_text(
        "✅ Audio mil gaya!\n\n"
        "🚀 Images generate hona shuru...\n"
        "Grok → Ideogram → Stability → Flux\n"
        "Jab ek ki limit hogi toh automatically doosra chalega!\n\n"
        "Thoda wait karo, progress batata rahunga..."
    )

    asyncio.create_task(run_generation(context, state))

async def run_generation(context, state):
    title = state["current_title"]
    image_prompts = state["image_prompts"]
    clip_prompts = state["clip_prompts"]

    # Generate video clips
    await context.bot.send_message(chat_id=CHAT_ID, text="🎬 Pehle video clips bana raha hoon (10 clips)...")
    clips_made = 0
    for i, prompt in enumerate(clip_prompts[:10]):
        path = f"{CLIPS_FOLDER}/clip_{i:03d}.mp4"
        if Path(path).exists():
            clips_made += 1
            continue
        success = generate_clip(prompt, path)
        if success:
            clips_made += 1
        time.sleep(2)

    await context.bot.send_message(chat_id=CHAT_ID, text=f"✅ {clips_made} clips ready!\n\n🖼️ Ab 95 images bana raha hoon...")

    # Generate images
    images_made = 0
    sources_used = {"grok": 0, "ideogram": 0, "stability": 0, "flux": 0}

    for i, prompt in enumerate(image_prompts):
        path = f"{IMAGES_FOLDER}/img_{i:03d}.jpg"
        if Path(path).exists():
            images_made += 1
            continue

        source = generate_image(prompt, path)

        if source is None:
            await context.bot.send_message(
                chat_id=CHAT_ID,
                text=f"⚠️ {images_made} images ban gayi, sab APIs ki limit ho gayi aaj ke liye.\nKal /video wala command dobara chalao — wahan se continue hoga."
            )
            break

        sources_used[source] += 1
        images_made += 1

        if images_made % 15 == 0:
            await context.bot.send_message(
                chat_id=CHAT_ID,
                text=f"🖼️ {images_made}/95 images ready\n"
                     f"Grok: {sources_used['grok']} | Ideogram: {sources_used['ideogram']} | "
                     f"Stability: {sources_used['stability']} | Flux: {sources_used['flux']}"
            )

        time.sleep(1)

    total_images = len(list(Path(IMAGES_FOLDER).glob("img_*.jpg")))
    total_clips = len(list(Path(CLIPS_FOLDER).glob("clip_*.mp4")))

    if total_images >= 90:
        await context.bot.send_message(
            chat_id=CHAT_ID,
            text=f"🎉 {total_images} images + {total_clips} clips ready!\n\n🎬 Video ban raha hai..."
        )
        await build_video(context, state)
    else:
        await context.bot.send_message(
            chat_id=CHAT_ID,
            text=f"⚠️ Aaj {total_images} images bane.\nKal /makevideo se baaki banenge aur video ready hogi."
        )

async def makevideo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != CHAT_ID:
        return

    if not os.path.exists(AUDIO_FILE):
        await update.message.reply_text("❌ Audio file nahi hai. Pehle audio bhejo.")
        return

    state = load_state()
    images = len(list(Path(IMAGES_FOLDER).glob("img_*.jpg")))

    if images < 10:
        await update.message.reply_text("❌ Bahut kam images hain. Pehle /video se generation shuru karo.")
        return

    await update.message.reply_text(f"🎬 {images} images se video ban raha hai...")
    asyncio.create_task(build_video(context, state))

async def build_video(context, state):
    try:
        output = assemble_video(AUDIO_FILE)

        await context.bot.send_message(chat_id=CHAT_ID, text="📦 SEO pack generate ho raha hai...")
        seo = grok_seo(state["current_title"], state["script"])

        with open("seo_pack.txt", "w", encoding="utf-8") as f:
            f.write(seo)

        await context.bot.send_message(chat_id=CHAT_ID, text="📤 Video bhej raha hoon...")

        file_size = os.path.getsize(output) / (1024 * 1024)
        if file_size > 50:
            await context.bot.send_message(
                chat_id=CHAT_ID,
                text=f"⚠️ Video {file_size:.0f}MB hai — Telegram limit 50MB hai.\n"
                     "Compress ho raha hai..."
            )
            compressed = "final_compressed.mp4"
            subprocess.run([
                "ffmpeg", "-y", "-i", output,
                "-vf", "scale=1280:720",
                "-c:v", "libx264", "-crf", "28",
                "-c:a", "aac", "-b:a", "128k",
                compressed
            ], check=True)
            output = compressed

        with open(output, "rb") as vf:
            await context.bot.send_video(
                chat_id=CHAT_ID,
                video=vf,
                caption=f"🎬 {state['current_title']}\n✅ Video Ready!",
                supports_streaming=True,
                read_timeout=300,
                write_timeout=300
            )

        with open("seo_pack.txt", "rb") as sf:
            await context.bot.send_document(
                chat_id=CHAT_ID,
                document=sf,
                filename="seo_pack.txt",
                caption="📦 SEO Pack — Title, Description, Tags, Hashtags sab yahan!"
            )

        await context.bot.send_message(
            chat_id=CHAT_ID,
            text="🎉 Sab kuch ready!\n\nAgle video ke liye /video [title] bhejo."
        )

    except Exception as e:
        await context.bot.send_message(chat_id=CHAT_ID, text=f"❌ Error: {str(e)}")

# ─── MAIN ─────────────────────────────────────────────────────────────────────
def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("video", video_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("makevideo", makevideo_command))
    app.add_handler(MessageHandler(
        filters.AUDIO | filters.VOICE | filters.Document.AUDIO,
        handle_audio
    ))
    print("🤖 Bot chal raha hai...")
    app.run_polling()

if __name__ == "__main__":
    main()
