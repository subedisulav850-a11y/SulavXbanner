import io
import os
import re
import asyncio
import random
import logging
import urllib.request
import urllib.error
import zipfile
from datetime import datetime
from typing import Optional, List, Dict, Any
from contextlib import asynccontextmanager
from fastapi import FastAPI, Response, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from PIL import Image, ImageDraw, ImageFont
from concurrent.futures import ThreadPoolExecutor
import httpx

# ================= Logging =================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ff_api")

# ================= Configuration =================
AVATAR_ZOOM = 1.26
AVATAR_SHIFT_Y = 0
AVATAR_SHIFT_X = 0
BANNER_START_X = 0.25
BANNER_START_Y = 0.29
BANNER_END_X = 0.81
BANNER_END_Y = 0.65

FONT_MAIN = "arial_unicode_bold.otf"
FONT_CHEROKEE = "NotoSansCherokee.ttf"
PRIME_FILES = {i: f"prime{i}.png" for i in range(0, 9)}
PRIME8_FRAME_FILE = "prime8frame.png"

OUTFIT_BACKGROUND = "outfit.png"
ICON_SIZE = (95, 95)
CHARACTER_RENDER_SIZE = (700, 700)
FALLBACK_IDS = ["211000000", "214000000", "208000000", "203000000", "204000000", "205000000", "212000000"]
DEFAULT_AVATAR_ID = "710034057"

HEX_POSITIONS = {
    "mask": (990, 420), "shirt": (190, 90), "pants": (40, 420),
    "shoes": (840, 90), "emote": (40, 230), "armor": (990, 230),
    "weapon": (190, 560), "pet": (840, 560)
}

INFO_API_URL = "https://info.killersharmabot.online/player-info"
CDN_URL = "https://cdn.jsdelivr.net/gh/ShahGCreator/icon@main/PNG"

# ================= Lifespan =================
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting up...")
    app.state.prime_images = {}
    for lvl, path in PRIME_FILES.items():
        if os.path.exists(path):
            try:
                app.state.prime_images[lvl] = Image.open(path).convert("RGBA")
                logger.info(f"Loaded {path}")
            except Exception as e:
                logger.warning(f"Failed {path}: {e}")
    app.state.prime8_frame = None
    if os.path.exists(PRIME8_FRAME_FILE):
        try:
            app.state.prime8_frame = Image.open(PRIME8_FRAME_FILE).convert("RGBA")
            logger.info(f"Loaded {PRIME8_FRAME_FILE}")
        except Exception as e:
            logger.warning(f"Failed {PRIME8_FRAME_FILE}: {e}")
    app.state.client = httpx.AsyncClient(timeout=30.0, follow_redirects=True)
    app.state.thread_pool = ThreadPoolExecutor(max_workers=4)
    app.state.outfit_available = os.path.exists(OUTFIT_BACKGROUND)
    if not app.state.outfit_available:
        logger.warning(f"Outfit background missing: {OUTFIT_BACKGROUND}")
    yield
    await app.state.client.aclose()
    app.state.thread_pool.shutdown()
    logger.info("Shutdown complete")

app = FastAPI(lifespan=lifespan, title="FF Banner + Outfit API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ================= Helpers =================
def clean_text(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f\u200b\uFEFF\uf8ff]', '', str(text))
    return ' '.join(text.split())

def load_unicode_font(size: int, font_file: str = FONT_MAIN):
    try:
        font_path = os.path.join(os.path.dirname(__file__), font_file)
        if os.path.exists(font_path):
            return ImageFont.truetype(font_path, size)
    except Exception:
        pass
    return ImageFont.load_default()

def is_cherokee(c: str) -> bool:
    return 0x13A0 <= ord(c) <= 0x13FF or 0xAB70 <= ord(c) <= 0xABBF

def draw_text_stroked(draw, x, y, text, f_main, f_alt, stroke=3):
    if not text:
        return
    cx = x
    for ch in text:
        font = f_alt if is_cherokee(ch) else f_main
        for dx in range(-stroke, stroke+1):
            for dy in range(-stroke, stroke+1):
                draw.text((cx+dx, y+dy), ch, font=font, fill="black")
        draw.text((cx, y), ch, font=font, fill="white")
        cx += font.getlength(ch)

async def fetch_image_bytes(item_id: str) -> Optional[bytes]:
    if not item_id or str(item_id).lower() in ("0", "none", "null"):
        return None
    url = f"{CDN_URL}/{item_id}.png"
    try:
        resp = await app.state.client.get(url)
        if resp.status_code == 200:
            return resp.content
    except Exception as e:
        logger.warning(f"Fetch error {item_id}: {e}")
    return None

def bytes_to_image(img_bytes: Optional[bytes]) -> Image.Image:
    if img_bytes:
        try:
            return Image.open(io.BytesIO(img_bytes)).convert("RGBA")
        except Exception:
            pass
    return Image.new("RGBA", (400, 400), (200, 200, 200, 255))

def sync_fetch_url(url: str) -> Optional[bytes]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.read()
    except Exception as e:
        logger.warning(f"Sync fetch error {url}: {e}")
        return None

def fetch_icon(icon_id, size=ICON_SIZE, is_character=False):
    try:
        if is_character:
            url = f"https://raw.githubusercontent.com/danggerr88-alt/danger-character-api/main/pngs/{icon_id}.png"
            data = sync_fetch_url(url)
            if data:
                img = Image.open(io.BytesIO(data)).convert("RGBA")
                bbox = img.getbbox()
                if bbox:
                    img = img.crop(bbox)
                w, h = img.size
                ratio = min(size[0] / w, size[1] / h)
                new_size = (int(w * ratio), int(h * ratio))
                return img.resize(new_size, Image.Resampling.LANCZOS)
        ids_to_try = [str(icon_id)] if icon_id and str(icon_id) != "0" else []
        for fid in FALLBACK_IDS:
            if fid not in ids_to_try:
                ids_to_try.append(fid)
        for i in ids_to_try:
            url = f"https://iconapi.wasmer.app/{i}"
            data = sync_fetch_url(url)
            if data:
                img = Image.open(io.BytesIO(data)).convert("RGBA")
                return img.resize(size, Image.Resampling.LANCZOS)
    except Exception as e:
        logger.warning(f"Icon fetch error: {e}")
    return None

async def fetch_real_player_data(uid: str) -> Dict[str, Any]:
    resp = await app.state.client.get(f"{INFO_API_URL}?uid={uid}")
    if resp.status_code != 200:
        raise HTTPException(502, f"API error: {resp.status_code}")
    data = resp.json()
    profile = data.get("profileInfo", {})
    clan = data.get("clanBasicInfo", {})
    basic = data.get("basicInfo", {})
    prime_info = data.get("primeInfo", {})

    name = clean_text(profile.get("nickname") or basic.get("nickname") or "Unknown")
    level = str(profile.get("level") or basic.get("level") or 0)
    guild = clean_text(clan.get("clanName", ""))
    headPic = str(profile.get("headPic") or basic.get("headPic") or "")
    banner_id = str(profile.get("bannerId") or basic.get("bannerId") or "")

    prime_level = 0
    if "primeLevel" in prime_info:
        prime_level = prime_info.get("primeLevel")
    elif "primeLevel" in profile:
        prime_level = profile.get("primeLevel")
    elif "primeLevel" in basic:
        prime_level = basic.get("primeLevel")
    try:
        prime_level = max(0, min(8, int(prime_level)))
    except:
        prime_level = 0

    clothes = profile.get("clothes") or []
    weapon_skins = basic.get("weaponSkinShows") or []
    weapon = weapon_skins[0] if weapon_skins else None
    pet = data.get("petInfo", {}).get("skinId")
    character = profile.get("avatarId") or DEFAULT_AVATAR_ID

    return {
        "name": name, "level": level, "guild": guild,
        "headPic": headPic, "banner_id": banner_id, "prime_level": prime_level,
        "clothes": clothes, "weapon": weapon, "pet": pet, "character": character
    }

def wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> List[str]:
    words = text.split()
    if len(words) <= 1:
        return [text]
    for i in range(1, len(words)):
        line1 = ' '.join(words[:i])
        line2 = ' '.join(words[i:])
        try:
            if font.getlength(line1) <= max_width and font.getlength(line2) <= max_width:
                return [line1, line2]
        except:
            pass
    return [text]

def generate_banner_image(avatar_bytes: Optional[bytes], banner_bytes: Optional[bytes], player: Dict[str, Any]) -> io.BytesIO:
    TARGET = 400
    avatar = bytes_to_image(avatar_bytes)
    try:
        zoom = int(TARGET * AVATAR_ZOOM)
        avatar = avatar.resize((zoom, zoom), Image.LANCZOS)
        left = (zoom - TARGET) // 2 - AVATAR_SHIFT_X
        top = (zoom - TARGET) // 2 - AVATAR_SHIFT_Y
        avatar = avatar.crop((left, top, left + TARGET, top + TARGET))
    except:
        avatar = Image.new("RGBA", (TARGET, TARGET), (100, 100, 100, 255))

    # Prime 8 frame
    if player.get("prime_level") == 8 and app.state.prime8_frame:
        try:
            frame = app.state.prime8_frame.resize(avatar.size, Image.LANCZOS)
            avatar = Image.alpha_composite(avatar, frame)
        except:
            pass

    # Prime badge overlay - NOW ON TOP-RIGHT CORNER
    prime_img = app.state.prime_images.get(player.get("prime_level", 0))
    if prime_img:
        try:
            badge_size = 70
            badge = prime_img.resize((badge_size, badge_size), Image.LANCZOS)
            # Position: right side, 10px from top and right edges
            x_pos = avatar.width - badge_size - 10
            y_pos = 10
            avatar.paste(badge, (x_pos, y_pos), badge)
        except:
            pass

    banner = bytes_to_image(banner_bytes)
    try:
        w, h = banner.size
        if w > 100 and h > 100:
            banner = banner.rotate(3, expand=True)
            w, h = banner.size
            l = w * BANNER_START_X
            t = h * BANNER_START_Y
            r = w * BANNER_END_X
            b = h * BANNER_END_Y
            banner = banner.crop((l, t, r, b))
        w, h = banner.size
        new_w = int(TARGET * (w / h) * 2) if h else 800
        banner = banner.resize((new_w, TARGET), Image.LANCZOS)
    except:
        banner = Image.new("RGBA", (800, TARGET), (100, 100, 100, 255))

    final_w = TARGET + banner.width
    combined = Image.new("RGBA", (final_w, TARGET), (0, 0, 0, 255))
    combined.paste(avatar, (0, 0))
    combined.paste(banner, (TARGET, 0))
    draw = ImageDraw.Draw(combined)

    name_x = TARGET + 65
    max_width = banner.width - 100
    if max_width < 100:
        max_width = 300

    font_name = load_unicode_font(110)
    font_name_che = load_unicode_font(110, FONT_CHEROKEE)
    font_guild = load_unicode_font(80)
    font_guild_che = load_unicode_font(80, FONT_CHEROKEE)
    font_level = load_unicode_font(50)

    y = 40
    for line in wrap_text(player.get("name", "Unknown"), font_name, max_width):
        draw_text_stroked(draw, name_x, y, line, font_name, font_name_che, 4)
        y += 85
    y += 60
    if player.get("guild"):
        draw_text_stroked(draw, name_x, y, player["guild"], font_guild, font_guild_che, 3)

    lvl_text = f"Lvl.{player.get('level', '0')}"
    try:
        bbox = draw.textbbox((0, 0), lvl_text, font=font_level)
        w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.rectangle([final_w - w - 60, TARGET - h - 50, final_w, TARGET], fill="black")
        draw.text((final_w - w - 30, TARGET - h - 40), lvl_text, font=font_level, fill="white")
    except:
        pass

    img_io = io.BytesIO()
    combined.save(img_io, "PNG")
    img_io.seek(0)
    return img_io

def generate_outfit_image(outfit_data: Dict[str, Any]) -> io.BytesIO:
    if not os.path.exists(OUTFIT_BACKGROUND):
        raise FileNotFoundError(f"Missing {OUTFIT_BACKGROUND}")
    canvas = Image.open(OUTFIT_BACKGROUND).convert("RGBA")
    slots = {
        "mask": outfit_data.get("mask"), "shirt": outfit_data.get("shirt"),
        "pants": outfit_data.get("pants"), "shoes": outfit_data.get("shoes"),
        "emote": outfit_data.get("emote"), "armor": outfit_data.get("armor"),
        "weapon": outfit_data.get("weapon"), "pet": outfit_data.get("pet"),
        "character": outfit_data.get("character", DEFAULT_AVATAR_ID)
    }
    for slot, item_id in slots.items():
        if not item_id:
            continue
        if slot == "character":
            img = fetch_icon(item_id, size=CHARACTER_RENDER_SIZE, is_character=True)
            if img:
                w, h = img.size
                cx = canvas.width // 2
                by = canvas.height - 20
                pos = (cx - w // 2, by - h)
        else:
            img = fetch_icon(item_id)
            if img:
                pos = HEX_POSITIONS.get(slot)
        if img and pos:
            canvas.paste(img, pos, img)
    # No watermark – just the combined image
    img_io = io.BytesIO()
    canvas.save(img_io, "PNG")
    img_io.seek(0)
    return img_io

# ================= API Endpoints =================
@app.get("/")
async def root():
    return {"endpoints": {"/health": "Health", "/player-info": "Player data", "/banner": "Generate banner", "/random-banner": "Random prime level banner", "/batch-banners": "ZIP of banners", "/outfit": "Generate outfit", "/prime-levels": "List prime levels"}, "docs": "/docs"}

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.get("/player-info")
async def player_info(uid: str = Query(...)):
    resp = await app.state.client.get(f"{INFO_API_URL}?uid={uid}")
    if resp.status_code != 200:
        raise HTTPException(502, "External API error")
    return JSONResponse(content=resp.json())

@app.get("/banner")
async def banner(
    uid: str = Query(...),
    bannerid: Optional[str] = None,
    avatarid: Optional[str] = None,
    primelevel: Optional[int] = Query(None, ge=0, le=8),
    guildname: Optional[str] = None,
    playername: Optional[str] = None,
    level: Optional[str] = None
):
    real = await fetch_real_player_data(uid)
    final = {
        "name": clean_text(playername) if playername is not None else real["name"],
        "level": level if level is not None else real["level"],
        "guild": clean_text(guildname) if guildname is not None else real["guild"],
        "headPic": avatarid if avatarid is not None else real["headPic"],
        "banner_id": bannerid if bannerid is not None else real["banner_id"],
        "prime_level": primelevel if primelevel is not None else real["prime_level"]
    }
    ava, ban = await asyncio.gather(fetch_image_bytes(final["headPic"]), fetch_image_bytes(final["banner_id"]))
    loop = asyncio.get_event_loop()
    img = await loop.run_in_executor(app.state.thread_pool, generate_banner_image, ava, ban, final)
    return Response(content=img.getvalue(), media_type="image/png")

@app.get("/random-banner")
async def random_banner(uid: str = Query(...)):
    """Generate banner with REAL avatar and banner, only prime level is randomised."""
    real = await fetch_real_player_data(uid)
    final = {
        "name": real["name"],
        "level": real["level"],
        "guild": real["guild"],
        "headPic": real["headPic"],      # Use real avatar ID
        "banner_id": real["banner_id"],  # Use real banner ID
        "prime_level": random.randint(0, 8)  # Only prime level is random
    }
    ava, ban = await asyncio.gather(fetch_image_bytes(final["headPic"]), fetch_image_bytes(final["banner_id"]))
    loop = asyncio.get_event_loop()
    img = await loop.run_in_executor(app.state.thread_pool, generate_banner_image, ava, ban, final)
    return Response(content=img.getvalue(), media_type="image/png")

@app.get("/batch-banners")
async def batch_banners(uids: str = Query(...)):
    uid_list = [u.strip() for u in uids.split(",") if u.strip()]
    if not uid_list:
        raise HTTPException(400, "No UIDs")
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for uid in uid_list:
            try:
                real = await fetch_real_player_data(uid)
                ava, ban = await asyncio.gather(fetch_image_bytes(real["headPic"]), fetch_image_bytes(real["banner_id"]))
                loop = asyncio.get_event_loop()
                img = await loop.run_in_executor(app.state.thread_pool, generate_banner_image, ava, ban, real)
                zf.writestr(f"banner_{uid}.png", img.getvalue())
            except Exception as e:
                logger.warning(f"Failed {uid}: {e}")
    zip_buf.seek(0)
    return Response(content=zip_buf.getvalue(), media_type="application/zip", headers={"Content-Disposition": "attachment; filename=banners.zip"})

@app.get("/outfit")
async def outfit(
    uid: str = Query(...),
    head: Optional[str] = None,
    mask: Optional[str] = None,
    top: Optional[str] = None,
    pants: Optional[str] = None,
    shoes: Optional[str] = None,
    faceprint: Optional[str] = None,
    paint: Optional[str] = None,
    weapon: Optional[str] = None,
    pet: Optional[str] = None
):
    if not app.state.outfit_available:
        raise HTTPException(503, f"Missing background file: {OUTFIT_BACKGROUND}")
    real = await fetch_real_player_data(uid)
    clothes = real.get("clothes", [])
    data = {
        "character": head or real.get("character"),
        "mask": mask or (clothes[0] if len(clothes) > 0 else None),
        "shirt": top or (clothes[1] if len(clothes) > 1 else None),
        "pants": pants or (clothes[2] if len(clothes) > 2 else None),
        "shoes": shoes or (clothes[3] if len(clothes) > 3 else None),
        "emote": faceprint or (clothes[4] if len(clothes) > 4 else None),
        "armor": paint or (clothes[5] if len(clothes) > 5 else None),
        "weapon": weapon or real.get("weapon"),
        "pet": pet or real.get("pet")
    }
    loop = asyncio.get_event_loop()
    img = await loop.run_in_executor(app.state.thread_pool, generate_outfit_image, data)
    return Response(content=img.getvalue(), media_type="image/png")

@app.get("/prime-levels")
async def prime_levels():
    return {"levels": [{"level": i, "badge": f"prime{i}.png", "frame": "prime8frame.png" if i == 8 else None} for i in range(9)]}

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 5000))
    uvicorn.run(app, host="0.0.0.0", port=port)