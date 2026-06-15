import io
import os
import re
import asyncio
import random
import logging
import httpx
import zipfile
import requests
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
logger = logging.getLogger("ff_api")

# ================= Configuration =================
# Banner settings
AVATAR_ZOOM = 1.26
AVATAR_SHIFT_Y = 0
AVATAR_SHIFT_X = 0
BANNER_START_X = 0.25
BANNER_START_Y = 0.29
BANNER_END_X = 0.81
BANNER_END_Y = 0.65

# Fonts (optional)
FONT_MAIN = "arial_unicode_bold.otf"
FONT_CHEROKEE = "NotoSansCherokee.ttf"

# Prime assets (optional)
PRIME_FILES = {i: f"prime{i}.png" for i in range(0, 9)}
PRIME8_FRAME_FILE = "prime8frame.png"

# Outfit settings
OUTFIT_BACKGROUND = "outfit.png"
ICON_SIZE = (95, 95)
CHARACTER_RENDER_SIZE = (700, 700)

# Fallback IDs for outfit icons
FALLBACK_IDS = ["211000000", "214000000", "208000000", "203000000", "204000000", "205000000", "212000000"]
DEFAULT_AVATAR_ID = "710034057"

# Outfit positions
HEX_POSITIONS = {
    "mask": (990, 420),
    "shirt": (190, 90),
    "pants": (40, 420),
    "shoes": (840, 90),
    "emote": (40, 230),
    "armor": (990, 230),
    "weapon": (190, 560),
    "pet": (840, 560)
}

# API URLs
INFO_API_URL = "https://info.killersharmabot.online/player-info"
CDN_URL = "https://cdn.jsdelivr.net/gh/ShahGCreator/icon@main/PNG"

# ================= Lifespan =================
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 Starting up...")
    app.state.prime_images = load_prime_images()
    app.state.prime8_frame = load_prime8_frame()
    app.state.client = httpx.AsyncClient(
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=30.0,
        follow_redirects=True
    )
    app.state.thread_pool = ThreadPoolExecutor(max_workers=4)
    
    # Check outfit background
    app.state.outfit_available = os.path.exists(OUTFIT_BACKGROUND)
    if app.state.outfit_available:
        logger.info(f"✅ Outfit background found: {OUTFIT_BACKGROUND}")
    else:
        logger.warning(f"⚠️ Outfit background not found: {OUTFIT_BACKGROUND} – outfit endpoint will return 503")
    
    yield
    logger.info("🛑 Shutting down...")
    await app.state.client.aclose()
    app.state.thread_pool.shutdown()

app = FastAPI(lifespan=lifespan, title="FF Banner + Outfit API", description="Professional Free Fire Image Generator")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ================= Shared Helper Functions =================
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
    except Exception as e:
        logger.warning(f"Font error: {e}")
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
        try:
            cx += font.getlength(ch)
        except:
            cx += font.getsize(ch)[0]

def load_prime_images() -> Dict[int, Optional[Image.Image]]:
    images = {}
    for lvl, path in PRIME_FILES.items():
        if os.path.exists(path):
            try:
                images[lvl] = Image.open(path).convert("RGBA")
                logger.info(f"✅ Loaded {path}")
            except Exception as e:
                logger.warning(f"❌ Failed {path}: {e}")
                images[lvl] = None
        else:
            images[lvl] = None
    return images

def load_prime8_frame() -> Optional[Image.Image]:
    if os.path.exists(PRIME8_FRAME_FILE):
        try:
            img = Image.open(PRIME8_FRAME_FILE).convert("RGBA")
            logger.info(f"✅ Loaded {PRIME8_FRAME_FILE}")
            return img
        except Exception as e:
            logger.warning(f"❌ Failed {PRIME8_FRAME_FILE}: {e}")
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
        except Exception as e:
            logger.warning(f"Image decode error: {e}")
    return Image.new("RGBA", (400, 400), (200, 200, 200, 255))

def fetch_sync_image_bytes(item_id: str) -> Optional[bytes]:
    if not item_id or str(item_id).lower() in ("0", "none", "null", ""):
        return None
    url = f"{CDN_URL}/{item_id}.png"
    try:
        resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        if resp.status_code == 200:
            return resp.content
    except Exception as e:
        logger.error(f"Sync fetch error {item_id}: {e}")
    return None

def fetch_icon(icon_id, size=ICON_SIZE, is_character=False):
    try:
        if is_character:
            url = f"https://raw.githubusercontent.com/danggerr88-alt/danger-character-api/main/pngs/{icon_id}.png"
            r = requests.get(url, timeout=10)
            if r.status_code == 200:
                img = Image.open(io.BytesIO(r.content)).convert("RGBA")
                bbox = img.getbbox()
                if bbox:
                    img = img.crop(bbox)
                w, h = img.size
                ratio = min(size[0] / w, size[1] / h)
                new_size = (int(w * ratio), int(h * ratio))
                img = img.resize(new_size, Image.Resampling.LANCZOS)
                return img

        ids_to_try = []
        if icon_id and str(icon_id) != "0":
            ids_to_try.append(str(icon_id))
        for fid in FALLBACK_IDS:
            if fid not in ids_to_try:
                ids_to_try.append(fid)

        for i in ids_to_try:
            try:
                url = f"https://iconapi.wasmer.app/{i}"
                r = requests.get(url, timeout=10)
                if r.status_code == 200:
                    img = Image.open(io.BytesIO(r.content)).convert("RGBA")
                    return img.resize(size, Image.Resampling.LANCZOS)
            except:
                continue
    except Exception as e:
        logger.warning(f"Icon fetch error: {e}")
    return None

# ================= Player Data Extraction =================
async def fetch_real_player_data(uid: str) -> Dict[str, Any]:
    try:
        resp = await app.state.client.get(f"{INFO_API_URL}?uid={uid}")
        if resp.status_code != 200:
            raise HTTPException(status_code=502, detail=f"API error: {resp.status_code}")
        data = resp.json()
    except Exception as e:
        logger.error(f"Failed to fetch data for {uid}: {e}")
        raise HTTPException(status_code=502, detail=f"Cannot fetch player data: {e}")
    
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
    
    logger.info(f"📊 Extracted: name='{name}', level={level}, guild='{guild}', prime={prime_level}, clothes={len(clothes)}")
    
    return {
        "name": name, "level": level, "guild": guild,
        "headPic": headPic, "banner_id": banner_id, "prime_level": prime_level,
        "clothes": clothes, "weapon": weapon, "pet": pet, "character": character
    }

# ================= Banner Generation =================
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

def generate_banner_image(avatar_bytes: Optional[bytes],
                          banner_bytes: Optional[bytes],
                          player: Dict[str, Any]) -> io.BytesIO:
    TARGET_HEIGHT = 400
    
    avatar_img = bytes_to_image(avatar_bytes)
    try:
        zoom_size = int(TARGET_HEIGHT * AVATAR_ZOOM)
        avatar_img = avatar_img.resize((zoom_size, zoom_size), Image.LANCZOS)
        left = (zoom_size - TARGET_HEIGHT) // 2 - AVATAR_SHIFT_X
        top = (zoom_size - TARGET_HEIGHT) // 2 - AVATAR_SHIFT_Y
        avatar_img = avatar_img.crop((left, top, left + TARGET_HEIGHT, top + TARGET_HEIGHT))
    except Exception as e:
        logger.error(f"Avatar crop failed: {e}")
        avatar_img = Image.new("RGBA", (TARGET_HEIGHT, TARGET_HEIGHT), (100, 100, 100, 255))
    
    prime_level = player.get("prime_level", 0)
    if prime_level == 8 and app.state.prime8_frame is not None:
        try:
            frame_resized = app.state.prime8_frame.resize(avatar_img.size, Image.LANCZOS)
            avatar_img = Image.alpha_composite(avatar_img, frame_resized)
        except Exception as e:
            logger.warning(f"Frame failed: {e}")
    
    prime_img = app.state.prime_images.get(prime_level)
    if prime_img is not None:
        try:
            badge_size = 70
            prime_resized = prime_img.resize((badge_size, badge_size), Image.LANCZOS)
            avatar_img.paste(prime_resized, (10, 10), prime_resized)
        except Exception as e:
            logger.warning(f"Badge overlay failed: {e}")
    
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
    
    final_w = TARGET_HEIGHT + banner_img.width
    combined = Image.new("RGBA", (final_w, TARGET_HEIGHT), (0, 0, 0, 255))
    combined.paste(avatar_img, (0, 0))
    combined.paste(banner_img, (TARGET_HEIGHT, 0))
    draw = ImageDraw.Draw(combined)
    
    name_x = TARGET_HEIGHT + 65
    max_text_width = banner_img.width - 100
    if max_text_width < 100:
        max_text_width = 300
    
    font_name = load_unicode_font(110)
    font_name_cherokee = load_unicode_font(110, FONT_CHEROKEE)
    font_guild = load_unicode_font(80)
    font_guild_cherokee = load_unicode_font(80, FONT_CHEROKEE)
    font_level = load_unicode_font(50)
    
    name_lines = wrap_text(player.get("name", "Unknown"), font_name, max_text_width)
    y = 40
    for line in name_lines:
        draw_text_stroked(draw, name_x, y, line, font_name, font_name_cherokee, 4)
        y += 85
    
    y += 60
    guild = player.get("guild", "")
    if guild:
        draw_text_stroked(draw, name_x, y, guild, font_guild, font_guild_cherokee, 3)
    
    lvl_text = f"Lvl.{player.get('level', '0')}"
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

# ================= Outfit Generation =================
def generate_outfit_image(outfit_data: Dict[str, Any]) -> io.BytesIO:
    if not os.path.exists(OUTFIT_BACKGROUND):
        raise FileNotFoundError(f"Background template '{OUTFIT_BACKGROUND}' not found")
    
    canvas = Image.open(OUTFIT_BACKGROUND).convert("RGBA")
    
    draw_tasks = {
        "mask": outfit_data.get("mask"),
        "shirt": outfit_data.get("shirt"),
        "pants": outfit_data.get("pants"),
        "shoes": outfit_data.get("shoes"),
        "emote": outfit_data.get("emote"),
        "armor": outfit_data.get("armor"),
        "weapon": outfit_data.get("weapon"),
        "pet": outfit_data.get("pet"),
        "character": outfit_data.get("character", DEFAULT_AVATAR_ID)
    }
    
    for slot, item_id in draw_tasks.items():
        if not item_id:
            continue
        
        if slot == "character":
            icon_img = fetch_icon(item_id, size=CHARACTER_RENDER_SIZE, is_character=True)
            if not icon_img:
                continue
            w, h = icon_img.size
            center_x = canvas.width // 2
            bottom_y = canvas.height - 20
            pos = (int(center_x - w // 2), int(bottom_y - h))
        else:
            icon_img = fetch_icon(item_id)
            if not icon_img:
                continue
            pos = HEX_POSITIONS.get(slot)
        
        if not pos:
            continue
        
        canvas.paste(icon_img, pos, icon_img)
    
    img_io = io.BytesIO()
    canvas.save(img_io, format='PNG', optimize=True)
    img_io.seek(0)
    return img_io

# ================= API Endpoints =================
@app.get("/")
async def root():
    return {
        "name": "FF Banner + Outfit API",
        "version": "3.0",
        "endpoints": {
            "/": "This help page",
            "/health": "Health check",
            "/player-info?uid={uid}": "Get raw player data",
            "/banner?uid={uid}": "Generate banner (real data)",
            "/banner?uid={uid}&primelevel={value}": "Override prime level",
            "/banner?uid={uid}&bannerid={id}&avatarid={id}&primelevel={value}&guildname={name}&playername={name}&level={value}": "Full manual override",
            "/random-banner?uid={uid}": "Random banner",
            "/batch-banners?uids={uid1},{uid2}": "Generate multiple banners (ZIP)",
            "/outfit?uid={uid}": "Generate outfit image (real data)",
            "/outfit?uid={uid}&head={id}&mask={id}&top={id}&pants={id}&shoes={id}&faceprint={id}&paint={id}&weapon={id}&pet={id}": "Outfit with custom overrides",
            "/prime-levels": "List prime levels"
        },
        "docs": "/docs"
    }

@app.get("/health")
async def health():
    return {"status": "ok", "timestamp": datetime.now().isoformat()}

@app.get("/player-info")
async def get_player_info(uid: str = Query(...)):
    try:
        resp = await app.state.client.get(f"{INFO_API_URL}?uid={uid}")
        if resp.status_code != 200:
            raise HTTPException(status_code=resp.status_code, detail="External API error")
        return JSONResponse(content=resp.json())
    except Exception as e:
        logger.exception("Player-info proxy error")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/banner")
async def generate_banner(
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
        logger.info(f"🎨 Generating banner with: {final_data}")
        
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
        
        return Response(
            content=img_io.getvalue(),
            media_type="image/png",
            headers={"Cache-Control": "public, max-age=300"}
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Banner generation failed for {uid}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/random-banner")
async def random_banner(uid: str = Query(...)):
    try:
        real_data = await fetch_real_player_data(uid)
        random_avatar = str(random.randint(900000000, 909999999))
        random_banner = str(random.randint(901000000, 901999999))
        random_prime = random.randint(0, 8)
        
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
        
        return Response(
            content=img_io.getvalue(),
            media_type="image/png",
            headers={"Cache-Control": "public, max-age=300"}
        )
    except Exception as e:
        logger.exception(f"Random banner failed for {uid}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/batch-banners")
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
                logger.info(f"✅ Generated banner for {uid}")
            except Exception as e:
                logger.warning(f"❌ Failed for {uid}: {e}")
    
    zip_buffer.seek(0)
    return Response(
        content=zip_buffer.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=banners.zip"}
    )

@app.get("/outfit")
async def generate_outfit(
    uid: str = Query(...),
    head: Optional[str] = Query(None, description="Override character (avatarId)"),
    mask: Optional[str] = Query(None, description="Override mask ID"),
    top: Optional[str] = Query(None, description="Override shirt/top ID"),
    pants: Optional[str] = Query(None, description="Override pants ID"),
    shoes: Optional[str] = Query(None, description="Override shoes ID"),
    faceprint: Optional[str] = Query(None, description="Override emote/faceprint ID"),
    paint: Optional[str] = Query(None, description="Override armor/paint ID"),
    weapon: Optional[str] = Query(None, description="Override weapon ID"),
    pet: Optional[str] = Query(None, description="Override pet ID")
):
    # Check if outfit background exists
    if not app.state.outfit_available:
        raise HTTPException(
            status_code=503,
            detail=f"Outfit background '{OUTFIT_BACKGROUND}' not found. Please upload this file to the server."
        )
    
    try:
        real_data = await fetch_real_player_data(uid)
        clothes = real_data.get("clothes", [])
        
        outfit_data = {
            "character": head if head is not None else real_data.get("character"),
            "mask": mask if mask is not None else (clothes[0] if len(clothes) > 0 else None),
            "shirt": top if top is not None else (clothes[1] if len(clothes) > 1 else None),
            "pants": pants if pants is not None else (clothes[2] if len(clothes) > 2 else None),
            "shoes": shoes if shoes is not None else (clothes[3] if len(clothes) > 3 else None),
            "emote": faceprint if faceprint is not None else (clothes[4] if len(clothes) > 4 else None),
            "armor": paint if paint is not None else (clothes[5] if len(clothes) > 5 else None),
            "weapon": weapon if weapon is not None else real_data.get("weapon"),
            "pet": pet if pet is not None else real_data.get("pet")
        }
        
        logger.info(f"👕 Generating outfit for UID: {uid} with overrides")
        
        loop = asyncio.get_event_loop()
        img_io = await loop.run_in_executor(
            app.state.thread_pool,
            generate_outfit_image,
            outfit_data
        )
        
        return Response(
            content=img_io.getvalue(),
            media_type="image/png",
            headers={"Cache-Control": "public, max-age=300"}
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.exception(f"Outfit generation failed for {uid}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/prime-levels")
async def list_prime_levels():
    prime_info = []
    for i in range(9):
        prime_info.append({
            "level": i,
            "badge_file": f"prime{i}.png",
            "frame": "prime8frame.png" if i == 8 else None,
            "has_frame": i == 8,
            "description": "Prime Level 8 (Special Frame)" if i == 8 else f"Prime Level {i}"
        })
    return {"prime_levels": prime_info}

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 5000))
    uvicorn.run(app, host="0.0.0.0", port=port)