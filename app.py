import io
import os
import re
import asyncio
import logging
import httpx
from datetime import datetime
from typing import Optional, List, Dict, Any
from contextlib import asynccontextmanager
from fastapi import FastAPI, Response, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image, ImageDraw, ImageFont
from concurrent.futures import ThreadPoolExecutor

# ================= Logging =================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("banner_api")

# ================= Configuration =================
AVATAR_ZOOM = 1.26
AVATAR_SHIFT_Y = 0
AVATAR_SHIFT_X = 0
BANNER_START_X = 0.25
BANNER_START_Y = 0.29
BANNER_END_X = 0.81
BANNER_END_Y = 0.65

# Old fonts (kept as requested)
FONT_MAIN = "arial_unicode_bold.otf"
FONT_CHEROKEE = "NotoSansCherokee.ttf"

PRIME_FILES = {i: f"prime{i}.png" for i in range(0, 9)}
PRIME8_FRAME_FILE = "prime8frame.png"

# NEW API URL
INFO_API_URL = "http://krsxh-ff-info.vercel.app/player-info"
CDN_URL = "https://cdn.jsdelivr.net/gh/ShahGCreator/icon@main/PNG"

# ================= Lifespan =================
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting up...")
    app.state.prime_images = load_prime_images()
    app.state.prime8_frame = load_prime8_frame()
    app.state.client = httpx.AsyncClient(
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=30.0,
        follow_redirects=True
    )
    app.state.thread_pool = ThreadPoolExecutor(max_workers=4)
    yield
    logger.info("Shutting down...")
    await app.state.client.aclose()
    app.state.thread_pool.shutdown()

app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ================= Helper Functions =================
def clean_text(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f\u200b\uFEFF\uf8ff]', '', str(text))
    return ' '.join(text.split())

def wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> List[str]:
    words = text.split()
    if len(words) <= 1:
        return [text]
    for i in range(1, len(words)):
        line1 = ' '.join(words[:i])
        line2 = ' '.join(words[i:])
        try:
            w1 = font.getlength(line1)
            w2 = font.getlength(line2)
            if w1 <= max_width and w2 <= max_width:
                return [line1, line2]
        except:
            pass
    return [text]

def load_unicode_font(size: int, font_file: str = FONT_MAIN):
    try:
        font_path = os.path.join(os.path.dirname(__file__), font_file)
        if os.path.exists(font_path):
            return ImageFont.truetype(font_path, size)
    except Exception as e:
        logger.warning(f"Font error: {e}")
    return ImageFont.load_default()

def is_cherokee(c: str) -> bool:
    return 0x13A0 <= ord(c) <= 0x13FF or 0xAB70 <= ord(c) <= 0xABBF

def draw_text_stroked(draw, x, y, text, f_main, f_alt, stroke=3):
    cx = x
    for ch in text:
        font = f_alt if is_cherokee(ch) else f_main
        for dx in range(-stroke, stroke+1):
            for dy in range(-stroke, stroke+1):
                draw.text((cx+dx, y+dy), ch, font=font, fill="black")
        draw.text((cx, y), ch, font=font, fill="white")
        cx += font.getlength(ch)

def load_prime_images() -> Dict[int, Optional[Image.Image]]:
    images = {}
    for lvl, path in PRIME_FILES.items():
        if os.path.exists(path):
            try:
                images[lvl] = Image.open(path).convert("RGBA")
                logger.info(f"Loaded {path}")
            except Exception as e:
                logger.warning(f"Failed {path}: {e}")
                images[lvl] = None
        else:
            images[lvl] = None
    return images

def load_prime8_frame() -> Optional[Image.Image]:
    if os.path.exists(PRIME8_FRAME_FILE):
        try:
            img = Image.open(PRIME8_FRAME_FILE).convert("RGBA")
            logger.info(f"Loaded {PRIME8_FRAME_FILE}")
            return img
        except Exception as e:
            logger.warning(f"Failed {PRIME8_FRAME_FILE}: {e}")
    return None

async def fetch_image_bytes(item_id: str) -> Optional[bytes]:
    if not item_id or str(item_id).lower() in ("0", "none", "null", ""):
        return None
    url = f"{CDN_URL}/{item_id}.png"
    try:
        resp = await app.state.client.get(url)
        if resp.status_code == 200:
            logger.info(f"Downloaded {url}")
            return resp.content
        else:
            logger.warning(f"Failed {url}: HTTP {resp.status_code}")
    except Exception as e:
        logger.error(f"Fetch error {item_id}: {e}")
    return None

def bytes_to_image(img_bytes: Optional[bytes]) -> Image.Image:
    if img_bytes:
        try:
            return Image.open(io.BytesIO(img_bytes)).convert("RGBA")
        except Exception as e:
            logger.warning(f"Image decode error: {e}")
    return Image.new("RGBA", (400, 400), (200, 200, 200, 255))

# ================= Data Extraction (FIXED Prime Level) =================
def extract_player_data(data: Dict[str, Any]) -> Dict[str, Any]:
    # New API structure
    profile = data.get("profileInfo", {})
    clan = data.get("clanBasicInfo", {})
    prime_info = data.get("primeInfo", {})
    
    # Basic info might be nested differently
    basic = data.get("basicInfo", {})
    
    # Player name
    name = profile.get("nickname") or basic.get("nickname") or data.get("nickname", "Unknown")
    name = clean_text(name)
    
    # Level
    level = profile.get("level") or basic.get("level") or data.get("level", 0)
    level = str(level) if level else "0"
    
    # Guild name
    guild = clan.get("clanName", "")
    guild = clean_text(guild)
    
    # Avatar ID: from profileInfo.avatarId
    avatar_id = profile.get("avatarId")
    if not avatar_id:
        avatar_id = basic.get("headPic")
    avatar_id = str(avatar_id) if avatar_id else ""
    
    # Banner ID: from profileInfo.bannerId
    banner_id = profile.get("bannerId")
    if not banner_id:
        banner_id = basic.get("bannerId")
    banner_id = str(banner_id) if banner_id else ""
    
    # ========== FIXED: Prime level extraction ==========
    # Try primeInfo.primeLevel first (as per new API)
    prime_level = prime_info.get("primeLevel")
    
    # If not found, try other locations
    if prime_level is None:
        prime_level = basic.get("primeLevel", {}).get("level")
    if prime_level is None:
        prime_level = data.get("primeLevel")
    if prime_level is None:
        prime_level = 0
    
    # Ensure it's an integer
    try:
        prime_level = int(prime_level)
    except (TypeError, ValueError):
        prime_level = 0
    
    # Creation date (for prime 8 layout)
    create_at = profile.get("createAt") or basic.get("createAt", "")
    since_text = ""
    if create_at and str(create_at).isdigit():
        try:
            dt = datetime.fromtimestamp(int(create_at))
            since_text = dt.strftime("Since %d %b %Y")
        except:
            since_text = str(create_at)
    
    # Country
    country = profile.get("region") or basic.get("region", "")
    country = clean_text(country)
    
    logger.info(f"Extracted: name='{name}', level={level}, guild='{guild}', avatar_id={avatar_id}, banner_id={banner_id}, prime_level={prime_level}, since='{since_text}', country='{country}'")
    
    return {
        "name": name,
        "level": level,
        "guild": guild,
        "avatar_id": avatar_id,
        "banner_id": banner_id,
        "prime_level": prime_level,
        "since_text": since_text,
        "country": country
    }

# ================= Image Processing =================
def process_banner_image(avatar_bytes: Optional[bytes],
                         banner_bytes: Optional[bytes],
                         player: Dict[str, Any]) -> io.BytesIO:
    TARGET_HEIGHT = 400

    # --- Avatar ---
    avatar_img = bytes_to_image(avatar_bytes)
    try:
        zoom_size = int(TARGET_HEIGHT * AVATAR_ZOOM)
        avatar_img = avatar_img.resize((zoom_size, zoom_size), Image.LANCZOS)
        left = (zoom_size - TARGET_HEIGHT) // 2 - AVATAR_SHIFT_X
        top = (zoom_size - TARGET_HEIGHT) // 2 - AVATAR_SHIFT_Y
        avatar_img = avatar_img.crop((left, top, left + TARGET_HEIGHT, top + TARGET_HEIGHT))
    except Exception as e:
        logger.error(f"Avatar processing failed: {e}")
        avatar_img = Image.new("RGBA", (TARGET_HEIGHT, TARGET_HEIGHT), (100, 100, 100, 255))

    # Prime 8 frame (only for prime level 8)
    if player["prime_level"] == 8 and app.state.prime8_frame is not None:
        try:
            frame_resized = app.state.prime8_frame.resize(avatar_img.size, Image.LANCZOS)
            avatar_img = Image.alpha_composite(avatar_img, frame_resized)
            logger.info("Applied prime 8 frame to avatar")
        except Exception as e:
            logger.warning(f"Frame composite failed: {e}")

    # Prime badge overlay (top-left corner of avatar)
    prime_img = app.state.prime_images.get(player["prime_level"])
    if prime_img is not None:
        try:
            badge_size = 70
            prime_resized = prime_img.resize((badge_size, badge_size), Image.LANCZOS)
            avatar_img.paste(prime_resized, (10, 10), prime_resized)
            logger.info(f"Applied prime {player['prime_level']} badge to avatar")
        except Exception as e:
            logger.warning(f"Prime badge overlay error: {e}")

    # --- Banner ---
    banner_img = bytes_to_image(banner_bytes)
    try:
        b_w, b_h = banner_img.size
        if b_w > 100 and b_h > 100:
            banner_img = banner_img.rotate(3, expand=True)
            bw_rot, bh_rot = banner_img.size
            crop_left = bw_rot * BANNER_START_X
            crop_top = bh_rot * BANNER_START_Y
            crop_right = bw_rot * BANNER_END_X
            crop_bottom = bh_rot * BANNER_END_Y
            banner_img = banner_img.crop((crop_left, crop_top, crop_right, crop_bottom))

        b_w, b_h = banner_img.size
        aspect = (b_w / b_h) if b_h > 0 else 2.0
        new_banner_w = int(TARGET_HEIGHT * aspect * 2)
        banner_img = banner_img.resize((new_banner_w, TARGET_HEIGHT), Image.LANCZOS)
    except Exception as e:
        logger.error(f"Banner processing failed: {e}")
        banner_img = Image.new("RGBA", (800, TARGET_HEIGHT), (100, 100, 100, 255))

    # --- Combine ---
    final_w = TARGET_HEIGHT + banner_img.width
    combined = Image.new("RGBA", (final_w, TARGET_HEIGHT), (0, 0, 0, 255))
    combined.paste(avatar_img, (0, 0))
    combined.paste(banner_img, (TARGET_HEIGHT, 0))
    draw = ImageDraw.Draw(combined)

    name_x = TARGET_HEIGHT + 65
    max_text_width = banner_img.width - 100
    if max_text_width < 100:
        max_text_width = 300

    # Fonts (old fonts kept)
    font_large = load_unicode_font(110)
    font_large_cherokee = load_unicode_font(110, FONT_CHEROKEE)
    font_guild = load_unicode_font(80)
    font_guild_cherokee = load_unicode_font(80, FONT_CHEROKEE)
    font_level = load_unicode_font(50)

    # Layout: player name (wrapped) then guild name with large gap
    name_lines = wrap_text(player["name"], font_large, max_text_width)
    y = 40
    for line in name_lines:
        draw_text_stroked(draw, name_x, y, line, font_large, font_large_cherokee, 4)
        y += 85

    # Extra spacing before guild name (far below)
    y += 60

    if player["guild"]:
        draw_text_stroked(draw, name_x, y, player["guild"], font_guild, font_guild_cherokee, 3)

    # Level badge (bottom right)
    lvl_text = f"Lvl.{player['level']}"
    try:
        bbox = draw.textbbox((0, 0), lvl_text, font=font_level)
        w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.rectangle([final_w - w - 60, TARGET_HEIGHT - h - 50, final_w, TARGET_HEIGHT], fill="black")
        draw.text((final_w - w - 30, TARGET_HEIGHT - h - 40), lvl_text, font=font_level, fill="white")
    except Exception as e:
        logger.warning(f"Level badge error: {e}")

    img_io = io.BytesIO()
    combined.save(img_io, "PNG")
    img_io.seek(0)
    return img_io

# ================= API Endpoint =================
@app.get("/profile")
async def get_banner(uid: str):
    try:
        if not uid:
            raise HTTPException(status_code=400, detail="UID required")

        logger.info(f"Processing UID: {uid}")
        resp = await app.state.client.get(f"{INFO_API_URL}?uid={uid}")
        if resp.status_code != 200:
            logger.error(f"Info API returned {resp.status_code}")
            raise HTTPException(status_code=502, detail=f"Info API error: {resp.status_code}")

        data = resp.json()
        player = extract_player_data(data)

        avatar_bytes, banner_bytes = await asyncio.gather(
            fetch_image_bytes(player["avatar_id"]),
            fetch_image_bytes(player["banner_id"])
        )

        loop = asyncio.get_event_loop()
        img_io = await loop.run_in_executor(
            app.state.thread_pool,
            process_banner_image,
            avatar_bytes,
            banner_bytes,
            player
        )

        return Response(content=img_io.getvalue(), media_type="image/png",
                        headers={"Cache-Control": "public, max-age=300"})

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Unhandled exception for UID {uid}")
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {str(e)}")

@app.get("/health")
async def health():
    return {"status": "ok"}

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 5000))
    uvicorn.run(app, host="0.0.0.0", port=port)