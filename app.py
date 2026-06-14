import io
import os
import re
import json
import asyncio
import random as rnd
import logging
import httpx
import zipfile
from datetime import datetime
from typing import Optional, List, Dict, Any
from contextlib import asynccontextmanager
from fastapi import FastAPI, Response, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
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

FONT_MAIN = "arial_unicode_bold.otf"
FONT_CHEROKEE = "NotoSansCherokee.ttf"
PRIME_FILES = {i: f"prime{i}.png" for i in range(0, 9)}
PRIME8_FRAME_FILE = "prime8frame.png"

INFO_API_URL = "https://info.killersharmabot.online/player-info"
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

app = FastAPI(lifespan=lifespan, title="FF Banner API", description="Powerful banner generator")
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
            return resp.content
    except Exception as e:
        logger.error(f"Fetch error {item_id}: {e}")
    return None

def bytes_to_image(img_bytes: Optional[bytes]) -> Image.Image:
    if img_bytes:
        try:
            return Image.open(io.BytesIO(img_bytes)).convert("RGBA")
        except Exception:
            pass
    return Image.new("RGBA", (400, 400), (200, 200, 200, 255))

async def fetch_real_player_data(uid: str) -> Dict[str, Any]:
    resp = await app.state.client.get(f"{INFO_API_URL}?uid={uid}")
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail=f"External API error: {resp.status_code}")
    data = resp.json()
    
    profile = data.get("profileInfo", {})
    clan = data.get("clanBasicInfo", {})
    basic = data.get("basicInfo", {})
    prime_info = data.get("primeInfo", {})
    
    name = clean_text(profile.get("nickname") or basic.get("nickname") or data.get("nickname", "Unknown"))
    level = str(profile.get("level") or basic.get("level") or data.get("level", 0))
    guild = clean_text(clan.get("clanName", ""))
    headPic = str(profile.get("headPic") or basic.get("headPic") or "")
    banner_id = str(profile.get("bannerId") or basic.get("bannerId") or "")
    
    prime_level = None
    if "primeLevel" in prime_info:
        prime_level = prime_info.get("primeLevel")
    if prime_level is None and "primeLevel" in profile:
        prime_level = profile.get("primeLevel")
    if prime_level is None and "primeLevel" in basic:
        prime_level = basic.get("primeLevel")
    if prime_level is None and "primeLevel" in data:
        prime_level = data.get("primeLevel")
    if prime_level is None:
        prime_level = 0
    try:
        prime_level = max(0, min(8, int(prime_level)))
    except:
        prime_level = 0
    
    return {
        "name": name, "level": level, "guild": guild,
        "headPic": headPic, "banner_id": banner_id, "prime_level": prime_level
    }

def generate_banner_image(headPic_bytes: Optional[bytes],
                          banner_bytes: Optional[bytes],
                          player: Dict[str, Any]) -> io.BytesIO:
    TARGET_HEIGHT = 400
    avatar_img = bytes_to_image(headPic_bytes)
    try:
        zoom_size = int(TARGET_HEIGHT * AVATAR_ZOOM)
        avatar_img = avatar_img.resize((zoom_size, zoom_size), Image.LANCZOS)
        left = (zoom_size - TARGET_HEIGHT) // 2 - AVATAR_SHIFT_X
        top = (zoom_size - TARGET_HEIGHT) // 2 - AVATAR_SHIFT_Y
        avatar_img = avatar_img.crop((left, top, left + TARGET_HEIGHT, top + TARGET_HEIGHT))
    except Exception:
        avatar_img = Image.new("RGBA", (TARGET_HEIGHT, TARGET_HEIGHT), (100, 100, 100, 255))

    # Prime 8 frame
    if player["prime_level"] == 8 and app.state.prime8_frame is not None:
        try:
            frame_resized = app.state.prime8_frame.resize(avatar_img.size, Image.LANCZOS)
            avatar_img = Image.alpha_composite(avatar_img, frame_resized)
        except Exception:
            pass

    # Prime badge overlay (top-left)
    prime_img = app.state.prime_images.get(player["prime_level"])
    if prime_img is not None:
        try:
            badge_size = 70
            prime_resized = prime_img.resize((badge_size, badge_size), Image.LANCZOS)
            avatar_img.paste(prime_resized, (10, 10), prime_resized)
        except Exception:
            pass

    # Banner
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
    except Exception:
        banner_img = Image.new("RGBA", (800, TARGET_HEIGHT), (100, 100, 100, 255))

    final_w = TARGET_HEIGHT + banner_img.width
    combined = Image.new("RGBA", (final_w, TARGET_HEIGHT), (0, 0, 0, 255))
    combined.paste(avatar_img, (0, 0))
    combined.paste(banner_img, (TARGET_HEIGHT, 0))
    draw = ImageDraw.Draw(combined)

    name_x = TARGET_HEIGHT + 65
    max_text_width = banner_img.width - 100
    if max_text_width < 100:
        max_text_width = 300

    font_large = load_unicode_font(110)
    font_large_cherokee = load_unicode_font(110, FONT_CHEROKEE)
    font_guild = load_unicode_font(80)
    font_guild_cherokee = load_unicode_font(80, FONT_CHEROKEE)
    font_level = load_unicode_font(50)

    name_lines = wrap_text(player["name"], font_large, max_text_width)
    y = 40
    for line in name_lines:
        draw_text_stroked(draw, name_x, y, line, font_large, font_large_cherokee, 4)
        y += 85
    y += 50  # extra gap
    if player["guild"]:
        draw_text_stroked(draw, name_x, y, player["guild"], font_guild, font_guild_cherokee, 3)

    lvl_text = f"Lvl.{player['level']}"
    try:
        bbox = draw.textbbox((0, 0), lvl_text, font=font_level)
        w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.rectangle([final_w - w - 60, TARGET_HEIGHT - h - 50, final_w, TARGET_HEIGHT], fill="black")
        draw.text((final_w - w - 30, TARGET_HEIGHT - h - 40), lvl_text, font=font_level, fill="white")
    except Exception:
        pass

    img_io = io.BytesIO()
    combined.save(img_io, "PNG")
    img_io.seek(0)
    return img_io

# ================= API Endpoints =================
@app.get("/")
async def root():
    return {
        "endpoints": {
            "/": "This help",
            "/health": "Health check",
            "/player-info?uid={uid}": "Proxy to external player info API",
            "/profile?uid={uid}": "Generate banner with real data",
            "/profile?uid={uid}&primelevel={value}": "Override prime level",
            "/profile?uid={uid}&bannerid={id}&avatarid={id}&primelevel={value}&guildname={name}&playername={name}&level={value}": "Full manual override",
            "/random?uid={uid}": "Random avatar, banner, prime level (name/guild real)",
            "/batch?uids={uid1},{uid2}": "Generate multiple banners (ZIP)",
            "/prime/levels": "List prime levels",
            "/docs": "Swagger documentation"
        }
    }

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.get("/player-info")
async def player_info(uid: str = Query(...)):
    try:
        resp = await app.state.client.get(f"{INFO_API_URL}?uid={uid}")
        if resp.status_code != 200:
            raise HTTPException(status_code=resp.status_code, detail="External API error")
        return JSONResponse(content=resp.json())
    except Exception as e:
        logger.exception("Player-info proxy error")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/profile")
async def get_banner(
    uid: str = Query(...),
    bannerid: Optional[str] = Query(None),
    avatarid: Optional[str] = Query(None),
    primelevel: Optional[int] = Query(None, ge=0, le=8),
    guildname: Optional[str] = Query(None),
    playername: Optional[str] = Query(None),
    level: Optional[str] = Query(None)
):
    try:
        real_data = await fetch_real_player_data(uid)
        final_data = {
            "name": clean_text(playername) if playername is not None else real_data["name"],
            "level": level if level is not None else real_data["level"],
            "guild": clean_text(guildname) if guildname is not None else real_data["guild"],
            "headPic": avatarid if avatarid is not None else real_data["headPic"],
            "banner_id": bannerid if bannerid is not None else real_data["banner_id"],
            "prime_level": primelevel if primelevel is not None else real_data["prime_level"]
        }
        logger.info(f"Final data: {final_data}")
        avatar_bytes, banner_bytes = await asyncio.gather(
            fetch_image_bytes(final_data["headPic"]),
            fetch_image_bytes(final_data["banner_id"])
        )
        loop = asyncio.get_event_loop()
        img_io = await loop.run_in_executor(
            app.state.thread_pool,
            generate_banner_image,
            avatar_bytes,
            banner_bytes,
            final_data
        )
        return Response(content=img_io.getvalue(), media_type="image/png",
                        headers={"Cache-Control": "public, max-age=300"})
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error for UID {uid}")
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {str(e)}")

@app.get("/random")
async def random_banner(uid: str = Query(...)):
    try:
        real_data = await fetch_real_player_data(uid)
        random_avatar = str(rnd.randint(900000000, 909999999))
        random_banner = str(rnd.randint(901000000, 901999999))
        random_prime = rnd.randint(0, 8)
        final_data = {
            "name": real_data["name"],
            "level": real_data["level"],
            "guild": real_data["guild"],
            "headPic": random_avatar,
            "banner_id": random_banner,
            "prime_level": random_prime
        }
        avatar_bytes, banner_bytes = await asyncio.gather(
            fetch_image_bytes(final_data["headPic"]),
            fetch_image_bytes(final_data["banner_id"])
        )
        loop = asyncio.get_event_loop()
        img_io = await loop.run_in_executor(
            app.state.thread_pool,
            generate_banner_image,
            avatar_bytes,
            banner_bytes,
            final_data
        )
        return Response(content=img_io.getvalue(), media_type="image/png",
                        headers={"Cache-Control": "public, max-age=300"})
    except Exception as e:
        logger.exception(f"Random error for UID {uid}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/batch")
async def batch_banners(uids: str = Query(...)):
    uid_list = [uid.strip() for uid in uids.split(",") if uid.strip()]
    if not uid_list:
        raise HTTPException(status_code=400, detail="No valid UIDs provided")
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for uid in uid_list:
            try:
                real_data = await fetch_real_player_data(uid)
                avatar_bytes, banner_bytes = await asyncio.gather(
                    fetch_image_bytes(real_data["headPic"]),
                    fetch_image_bytes(real_data["banner_id"])
                )
                loop = asyncio.get_event_loop()
                img_io = await loop.run_in_executor(
                    app.state.thread_pool,
                    generate_banner_image,
                    avatar_bytes,
                    banner_bytes,
                    real_data
                )
                zip_file.writestr(f"banner_{uid}.png", img_io.getvalue())
            except Exception as e:
                logger.warning(f"Failed for {uid}: {e}")
    zip_buffer.seek(0)
    return Response(content=zip_buffer.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": "attachment; filename=banners.zip"})

@app.get("/prime/levels")
async def prime_levels():
    return {
        "prime_levels": [
            {"level": i, "badge_file": f"prime{i}.png", "frame": "prime8frame.png" if i == 8 else None}
            for i in range(9)
        ]
    }

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 5000))
    uvicorn.run(app, host="0.0.0.0", port=port)