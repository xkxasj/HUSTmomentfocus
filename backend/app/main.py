from collections import Counter
from contextlib import asynccontextmanager
import base64
import hashlib
import json
import os
import re
import secrets
import smtplib
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request as UrlRequest, urlopen
from datetime import datetime, timedelta
from typing import Annotated
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import FileResponse, RedirectResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session, selectinload
from .database import Base, SessionLocal, engine, get_db
from .auth import create_access_token, get_current_user, hash_code, hash_password, make_alias, send_verification_email, verify_password
from .models import ChatMessage, Conversation, Echo, Location, Moment, Resonance, User, VerificationCode
from .schemas import ConversationCreate, EchoCreate, ImageCaptionRequest, LoginRequest, MessageCreate, MomentCreate, MomentOut, PositionUpdate, PrivacyUpdate, PromptRequest, RegisterRequest, ResonanceCreate, VerificationRequest
from .seed import seed_database

UPLOAD_DIR = Path(__file__).resolve().parent / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)
MAP_CACHE_DIR = Path(__file__).resolve().parent / "map_cache"
MAP_CACHE_DIR.mkdir(exist_ok=True)
MAP_STYLE_UPSTREAM = "https://tiles.openfreemap.org/styles/bright"
MAP_SOURCE_UPSTREAM = "https://tiles.openfreemap.org/planet"
MAP_USER_AGENT = "MoukeCampus/0.3 campus-map-proxy"
_map_style_cache: dict | None = None
_map_source_cache: dict | None = None
_map_tile_template: str | None = None
_map_sprite_base = "https://tiles.openfreemap.org/sprites/ofm_f384/ofm"
_map_request_counts: Counter = Counter()

def fetch_map_bytes(url: str, timeout: int = 25) -> bytes:
    request = UrlRequest(url, headers={"User-Agent": MAP_USER_AGENT, "Accept": "*/*"})
    with urlopen(request, timeout=timeout) as response:
        return response.read()

def fetch_map_json(url: str) -> dict:
    return json.loads(fetch_map_bytes(url).decode("utf-8"))

def cached_map_file(path: Path, upstream_url: str) -> bytes:
    if path.is_file(): return path.read_bytes()
    data = fetch_map_bytes(upstream_url)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return data

def map_json_from_cache(name: str, upstream_url: str) -> dict:
    data = cached_map_file(MAP_CACHE_DIR / name, upstream_url)
    return json.loads(data.decode("utf-8"))

def ensure_map_source() -> dict:
    global _map_source_cache, _map_tile_template
    if _map_source_cache is None:
        _map_source_cache = map_json_from_cache("source.json", MAP_SOURCE_UPSTREAM)
        tiles = _map_source_cache.get("tiles") or []
        if not tiles:
            raise ValueError("Map source does not contain a tile template")
        _map_tile_template = tiles[0]
    return _map_source_cache

@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        columns = {row[1] for row in connection.execute(text("PRAGMA table_info(locations)"))}
        if "latitude" not in columns: connection.execute(text("ALTER TABLE locations ADD COLUMN latitude FLOAT DEFAULT 30.5134"))
        if "longitude" not in columns: connection.execute(text("ALTER TABLE locations ADD COLUMN longitude FLOAT DEFAULT 114.4162"))
        if "category" not in columns: connection.execute(text("ALTER TABLE locations ADD COLUMN category VARCHAR(20) DEFAULT 'landmark'"))
        moment_columns = {row[1] for row in connection.execute(text("PRAGMA table_info(moments)"))}
        if "user_id" not in moment_columns: connection.execute(text("ALTER TABLE moments ADD COLUMN user_id INTEGER REFERENCES users(id)"))
        if "image_url" not in moment_columns: connection.execute(text("ALTER TABLE moments ADD COLUMN image_url VARCHAR(255)"))
        conversation_columns = {row[1] for row in connection.execute(text("PRAGMA table_info(conversations)"))}
        if conversation_columns and "initiator_id" not in conversation_columns: connection.execute(text("ALTER TABLE conversations ADD COLUMN initiator_id INTEGER REFERENCES users(id)"))
        if conversation_columns and "recipient_id" not in conversation_columns: connection.execute(text("ALTER TABLE conversations ADD COLUMN recipient_id INTEGER REFERENCES users(id)"))
        message_columns = {row[1] for row in connection.execute(text("PRAGMA table_info(chat_messages)"))}
        if message_columns and "sender_user_id" not in message_columns: connection.execute(text("ALTER TABLE chat_messages ADD COLUMN sender_user_id INTEGER REFERENCES users(id)"))
    with SessionLocal() as db: seed_database(db)
    yield

app = FastAPI(title="某刻 API", version="0.2.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost", "https://localhost", "capacitor://localhost", "http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/docs")

def moment_out(m: Moment) -> dict:
    return {"id":m.id,"location_id":m.location_id,"location_name":m.location.name,"author_alias":m.author_alias,"content":m.content,"image_url":m.image_url,"mood":m.mood,"created_at":m.created_at,"resonance_count":len(m.resonances),"echo_count":len(m.echoes),"is_official":m.is_official}

def location_out(p: Location, cutoff: datetime) -> dict:
    today_moments = [m for m in p.moments if m.created_at >= cutoff]
    today_interactions = len(today_moments) + sum(len(m.resonances) + len(m.echoes) for m in today_moments)
    return {"id":p.id,"name":p.name,"short_name":p.short_name,"description":p.description,"prompt":p.prompt,"mood":p.mood,"accent":p.accent,"category":p.category,"x":p.x,"y":p.y,"latitude":p.latitude,"longitude":p.longitude,"moment_count":len(p.moments),"today_count":len(today_moments),"today_interaction_count":today_interactions}

def load_moments(db: Session, location_id: int | None = None) -> list[Moment]:
    query = select(Moment).options(selectinload(Moment.location),selectinload(Moment.resonances),selectinload(Moment.echoes)).order_by(Moment.created_at.desc())
    if location_id is not None: query = query.where(Moment.location_id == location_id)
    return list(db.scalars(query))

def peer_presence(conversation: Conversation, viewer: User, db: Session) -> dict | None:
    peer_id = conversation.recipient_id if conversation.initiator_id == viewer.id else conversation.initiator_id
    peer = db.get(User, peer_id) if peer_id else None
    if not peer or not peer.share_location or not peer.last_position_at or peer.last_position_at < datetime.now() - timedelta(minutes=30): return None
    if peer.last_latitude is None or peer.last_longitude is None: return None
    places = db.scalars(select(Location)).all()
    nearest = min(places, key=lambda p: (p.latitude-peer.last_latitude)**2 + (p.longitude-peer.last_longitude)**2, default=None)
    return {"label": f"{nearest.short_name}附近" if nearest else "校园内", "updated_at": peer.last_position_at}

def conversation_out(conversation: Conversation, viewer: User, db: Session) -> dict:
    last = conversation.messages[-1].content if conversation.messages else "还没有消息"
    peer_id = conversation.recipient_id if conversation.initiator_id == viewer.id else conversation.initiator_id
    peer = db.get(User, peer_id) if peer_id else None
    return {"id": conversation.id, "peer_alias": peer.alias if peer else conversation.peer_alias, "origin_moment_id": conversation.origin_moment_id, "origin_excerpt": conversation.origin_excerpt, "location_name": conversation.location_name, "last_message": last, "updated_at": conversation.updated_at, "unread_count": 0, "peer_presence": peer_presence(conversation, viewer, db)}

def message_out(message: ChatMessage, viewer: User) -> dict:
    sender = "me" if message.sender_user_id == viewer.id else "peer"
    return {"id": message.id, "conversation_id": message.conversation_id, "sender": sender, "content": message.content, "created_at": message.created_at}

@app.get("/health")
def health(): return {"status":"ok","app":"某刻校园"}

@app.get("/api/map/style.json")
def map_style(request: Request):
    _map_request_counts["style"] += 1
    base = str(request.base_url).rstrip("/")
    source = {"source": "openmaptiles", "source-layer": "landuse"}
    return {
        "version": 8,
        "name": "Mouke Campus Real Map",
        "sources": {"openmaptiles": {
            "type": "vector",
            "tiles": [f"{base}/api/map/tiles/{{z}}/{{x}}/{{y}}.pbf"],
            "minzoom": 0,
            "maxzoom": 14,
            "bounds": [-180, -85.05113, 180, 85.05113],
            "attribution": "© OpenStreetMap contributors · OpenFreeMap",
        }},
        "layers": [
            {"id": "canvas", "type": "background", "paint": {"background-color": "#edf1e8"}},
            {"id": "landcover", "type": "fill", "source": "openmaptiles", "source-layer": "landcover", "paint": {"fill-color": ["match", ["get", "class"], "wood", "#c8ddbd", "grass", "#d9e7c7", "#e7eadf"], "fill-opacity": 0.72}},
            {"id": "landuse", "type": "fill", **source, "paint": {"fill-color": ["match", ["get", "class"], "park", "#cce3c3", "school", "#eee4c9", "hospital", "#f1d8d2", "#e6e6d8"], "fill-opacity": 0.62}},
            {"id": "park", "type": "fill", "source": "openmaptiles", "source-layer": "park", "paint": {"fill-color": "#c6dfbb", "fill-opacity": 0.72}},
            {"id": "water", "type": "fill", "source": "openmaptiles", "source-layer": "water", "paint": {"fill-color": "#9fd3df", "fill-opacity": 0.88}},
            {"id": "buildings", "type": "fill", "source": "openmaptiles", "source-layer": "building", "minzoom": 13, "paint": {"fill-color": "#e2c69e", "fill-outline-color": "#b98d67", "fill-opacity": 0.88}},
            {"id": "roads-casing", "type": "line", "source": "openmaptiles", "source-layer": "transportation", "minzoom": 12, "paint": {"line-color": "#b8aa91", "line-width": ["interpolate", ["linear"], ["zoom"], 12, 1.2, 18, 8]}},
            {"id": "roads", "type": "line", "source": "openmaptiles", "source-layer": "transportation", "minzoom": 12, "paint": {"line-color": "#fffaf0", "line-width": ["interpolate", ["linear"], ["zoom"], 12, 0.7, 18, 5.5]}},
        ],
    }

@app.get("/api/map/source.json")
def map_source(request: Request):
    _map_request_counts["source"] += 1
    try:
        source = json.loads(json.dumps(ensure_map_source()))
        base = str(request.base_url).rstrip("/")
        source["tiles"] = [f"{base}/api/map/tiles/{{z}}/{{x}}/{{y}}.pbf"]
        return source
    except Exception as exc:
        raise HTTPException(502, "真实地图数据源暂时无法加载") from exc

@app.get("/api/map/tiles/{z}/{x}/{y}.pbf")
def map_tile(z: int, x: int, y: int):
    _map_request_counts["tile"] += 1
    if z < 0 or z > 14 or x < 0 or y < 0 or x >= 2 ** z or y >= 2 ** z:
        raise HTTPException(400, "无效的地图瓦片坐标")
    try:
        ensure_map_source()
        if not _map_tile_template:
            raise ValueError("Missing tile template")
        upstream = _map_tile_template.format(z=z, x=x, y=y)
        data = cached_map_file(MAP_CACHE_DIR / "tiles" / str(z) / str(x) / f"{y}.pbf", upstream)
        return Response(data, media_type="application/vnd.mapbox-vector-tile", headers={"Cache-Control": "public, max-age=604800"})
    except Exception as exc:
        raise HTTPException(502, "地图瓦片暂时无法加载") from exc

@app.get("/api/map/fonts/{fontstack}/{range_name}.pbf")
def map_font(fontstack: str, range_name: str):
    if len(fontstack) > 160 or "/" in fontstack or "\\" in fontstack or not re.fullmatch(r"\d+-\d+", range_name):
        raise HTTPException(400, "无效的地图字体请求")
    try:
        digest = hashlib.sha256(fontstack.encode("utf-8")).hexdigest()[:24]
        upstream = f"https://tiles.openfreemap.org/fonts/{quote(fontstack, safe=',')}/{range_name}.pbf"
        data = cached_map_file(MAP_CACHE_DIR / "fonts" / digest / f"{range_name}.pbf", upstream)
        return Response(data, media_type="application/x-protobuf", headers={"Cache-Control": "public, max-age=2592000"})
    except Exception as exc:
        raise HTTPException(502, "地图字体暂时无法加载") from exc

@app.get("/api/map/sprites/{filename}")
def map_sprite(filename: str):
    if not re.fullmatch(r"ofm(?:@2x)?\.(?:json|png)", filename):
        raise HTTPException(404, "地图图标不存在")
    try:
        suffix = filename.removeprefix("ofm")
        data = cached_map_file(MAP_CACHE_DIR / "sprites" / filename, f"{_map_sprite_base}{suffix}")
        media_type = "application/json" if filename.endswith(".json") else "image/png"
        return Response(data, media_type=media_type, headers={"Cache-Control": "public, max-age=2592000"})
    except Exception as exc:
        raise HTTPException(502, "地图图标暂时无法加载") from exc

@app.get("/api/map/status")
def map_status():
    cached_tiles = sum(1 for path in (MAP_CACHE_DIR / "tiles").rglob("*.pbf") if path.stat().st_size > 0)
    return {"service": "ok", "requests": dict(_map_request_counts), "cached_tiles": cached_tiles}

def user_out(user: User) -> dict:
    return {"id": user.id, "student_id": user.student_id, "email": user.email, "alias": user.alias, "share_location": user.share_location}

def normalized_student_id(value: str) -> str:
    return value.strip().upper()

@app.get("/api/auth/email-status")
def email_status():
    sender = os.getenv("MOUKE_SMTP_FROM", os.getenv("MOUKE_SMTP_USERNAME"))
    return {
        "configured": bool(os.getenv("MOUKE_SMTP_HOST") and sender),
        "development_mode": os.getenv("MOUKE_DEV_EMAIL_CODES", "0") == "1",
    }

@app.post("/api/auth/request-code")
def request_verification_code(payload: VerificationRequest, db: Session = Depends(get_db)):
    student_id = normalized_student_id(payload.student_id)
    email = payload.email.strip().lower()
    expected_email = f"{student_id.lower()}@hust.edu.cn"
    if email != expected_email:
        raise HTTPException(400, f"请使用与学号一致的华科邮箱：{expected_email}")
    if db.scalar(select(User).where(or_(User.student_id == student_id, User.email == email))):
        raise HTTPException(409, "该学号已经注册")
    latest = db.scalar(select(VerificationCode).where(VerificationCode.student_id == student_id).order_by(VerificationCode.created_at.desc()))
    if latest and latest.created_at > datetime.now() - timedelta(seconds=60):
        raise HTTPException(429, "验证码发送过于频繁，请稍后再试")
    code = f"{secrets.randbelow(1_000_000):06d}"
    row = VerificationCode(student_id=student_id, email=email, code_hash=hash_code(code), expires_at=datetime.now() + timedelta(minutes=10))
    db.add(row); db.commit()
    try:
        sent = send_verification_email(email, code)
    except (OSError, smtplib.SMTPException):
        sent = False
    dev_mode = os.getenv("MOUKE_DEV_EMAIL_CODES", "0") == "1"
    if not sent and not dev_mode:
        raise HTTPException(503, "验证码邮件发送失败，请检查发件服务配置")
    return {"sent": sent, "dev_code": code if dev_mode else None, "expires_in": 600}

@app.post("/api/auth/register", status_code=201)
def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    student_id = normalized_student_id(payload.student_id)
    email = payload.email.strip().lower()
    if email != f"{student_id.lower()}@hust.edu.cn":
        raise HTTPException(400, "教育邮箱与学号不一致")
    if db.scalar(select(User).where(or_(User.student_id == student_id, User.email == email))):
        raise HTTPException(409, "该学号已经注册")
    code = db.scalar(select(VerificationCode).where(VerificationCode.student_id == student_id, VerificationCode.email == email, VerificationCode.consumed.is_(False)).order_by(VerificationCode.created_at.desc()))
    if code is None or code.expires_at < datetime.now() or code.code_hash != hash_code(payload.code):
        raise HTTPException(400, "验证码无效或已过期")
    code.consumed = True
    user = User(student_id=student_id, email=email, password_hash=hash_password(payload.password), alias=make_alias(student_id))
    db.add(user); db.commit(); db.refresh(user)
    return {"access_token": create_access_token(user,db), "token_type": "bearer", "user": user_out(user)}

@app.post("/api/auth/login")
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.student_id == normalized_student_id(payload.student_id)))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "学号或密码错误")
    return {"access_token": create_access_token(user,db), "token_type": "bearer", "user": user_out(user)}

@app.get("/api/auth/me")
def auth_me(user: Annotated[User, Depends(get_current_user)]):
    return user_out(user)

@app.patch("/api/me/privacy")
def update_privacy(payload: PrivacyUpdate, user: Annotated[User, Depends(get_current_user)], db: Session = Depends(get_db)):
    user.share_location = payload.share_location; db.commit()
    return user_out(user)

@app.put("/api/me/position")
def update_position(payload: PositionUpdate, user: Annotated[User, Depends(get_current_user)], db: Session = Depends(get_db)):
    user.last_latitude = payload.latitude; user.last_longitude = payload.longitude; user.last_position_at = datetime.now(); db.commit()
    return {"updated": True, "shared": user.share_location}

@app.get("/api/locations")
def locations(db: Session = Depends(get_db)):
    rows=db.scalars(select(Location).options(selectinload(Location.moments).selectinload(Moment.resonances), selectinload(Location.moments).selectinload(Moment.echoes)).order_by(Location.id)).all()
    result = sorted([location_out(row,datetime.now()-timedelta(days=1)) for row in rows], key=lambda item: (-item["today_interaction_count"], item["id"]))
    for rank, item in enumerate(result, start=1): item["today_rank"] = rank
    return result

@app.get("/api/locations/{location_id}/moments",response_model=list[MomentOut])
def location_moments(location_id:int,db:Session=Depends(get_db)):
    if db.get(Location,location_id) is None: raise HTTPException(404,"地点不存在")
    return [moment_out(row) for row in load_moments(db,location_id)]

@app.get("/api/feed")
def feed(db:Session=Depends(get_db)):
    places=locations(db); rows=load_moments(db)[:8]; moods=Counter(m.mood for m in rows if not m.is_official)
    return {"greeting":"晚上好","campus_pulse":"今晚的校园正在谈论："+("、".join(m for m,_ in moods.most_common(3)) or "平静"),"locations":places,"moments":[moment_out(row) for row in rows]}

@app.post("/api/moments",response_model=MomentOut,status_code=201)
def create_moment(payload:MomentCreate,user:Annotated[User,Depends(get_current_user)],db:Session=Depends(get_db)):
    if db.get(Location,payload.location_id) is None: raise HTTPException(404,"地点不存在")
    content = payload.content.strip()
    if not content and not payload.image_url: raise HTTPException(400,"文字和图片至少保留一项")
    if payload.image_url and (not payload.image_url.startswith("/api/uploads/") or not (UPLOAD_DIR / Path(payload.image_url).name).is_file()):
        raise HTTPException(400,"图片不存在或尚未上传")
    m=Moment(location_id=payload.location_id,user_id=user.id,author_alias=user.alias,content=content,image_url=payload.image_url,mood=payload.mood); db.add(m); db.commit()
    return moment_out(load_moments(db,payload.location_id)[0])

@app.post("/api/uploads/images", status_code=201)
async def upload_image(request: Request, user: Annotated[User, Depends(get_current_user)]):
    content_type = request.headers.get("content-type", "").split(";", 1)[0].lower()
    extensions = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
    if content_type not in extensions: raise HTTPException(415,"仅支持 JPG、PNG 或 WebP 图片")
    data = await request.body()
    if not data or len(data) > 15 * 1024 * 1024: raise HTTPException(413,"图片大小需在 15MB 以内")
    signatures_ok = (
        (content_type == "image/jpeg" and data.startswith(b"\xff\xd8\xff")) or
        (content_type == "image/png" and data.startswith(b"\x89PNG\r\n\x1a\n")) or
        (content_type == "image/webp" and data.startswith(b"RIFF") and data[8:12] == b"WEBP")
    )
    if not signatures_ok: raise HTTPException(400,"图片内容与文件类型不一致")
    filename = f"{user.id}-{secrets.token_hex(16)}{extensions[content_type]}"
    (UPLOAD_DIR / filename).write_bytes(data)
    return {"image_url": f"/api/uploads/{filename}", "moderation": "format_checked"}

@app.get("/api/uploads/{filename}")
def uploaded_image(filename: str):
    safe_name = Path(filename).name
    path = UPLOAD_DIR / safe_name
    if safe_name != filename or not path.is_file(): raise HTTPException(404,"图片不存在")
    return FileResponse(path, headers={"Cache-Control":"public, max-age=31536000, immutable"})

@app.post("/api/moments/{moment_id}/resonances")
def create_resonance(moment_id:int,payload:ResonanceCreate,user:Annotated[User,Depends(get_current_user)],db:Session=Depends(get_db)):
    if db.get(Moment,moment_id) is None: raise HTTPException(404,"片段不存在")
    db.add(Resonance(moment_id=moment_id,kind=payload.kind)); db.commit()
    return {"resonance_count":db.scalar(select(func.count()).select_from(Resonance).where(Resonance.moment_id==moment_id))}

@app.post("/api/moments/{moment_id}/echoes")
def create_echo(moment_id:int,payload:EchoCreate,user:Annotated[User,Depends(get_current_user)],db:Session=Depends(get_db)):
    if db.get(Moment,moment_id) is None: raise HTTPException(404,"片段不存在")
    db.add(Echo(moment_id=moment_id,content=payload.content.strip())); db.commit()
    return {"echo_count":db.scalar(select(func.count()).select_from(Echo).where(Echo.moment_id==moment_id))}

@app.get("/api/me/activity")
def activity(user:Annotated[User,Depends(get_current_user)],db:Session=Depends(get_db)):
    rows=load_moments(db); mine=[m for m in rows if m.user_id==user.id]
    return {"alias":user.alias,"posted_count":len(mine),"resonance_given":0,"echoes_sent":0,"received_resonance":sum(len(m.resonances) for m in mine),"moments":[moment_out(m) for m in mine]}

@app.post("/api/ai/expression-prompt")
def expression_prompt(payload:PromptRequest,db:Session=Depends(get_db)):
    place=db.get(Location,payload.location_id)
    if place is None: raise HTTPException(404,"地点不存在")
    sensitive=["宿舍号","手机号","身份证","老师姓名","班级群"]
    return {"prompt":place.prompt,"privacy_note":"这段话可能包含可识别身份的信息。" if any(w in payload.draft for w in sensitive) else None}

@app.get("/api/ai/status")
def ai_status():
    return {"vision_configured": bool(os.getenv("MOUKE_VISION_API_URL") and os.getenv("MOUKE_VISION_API_KEY"))}

@app.post("/api/ai/image-caption")
def image_caption(payload: ImageCaptionRequest, user: Annotated[User, Depends(get_current_user)], db: Session = Depends(get_db)):
    place = db.get(Location, payload.location_id)
    path = UPLOAD_DIR / Path(payload.image_url).name
    if place is None: raise HTTPException(404, "地点不存在")
    if not payload.image_url.startswith("/api/uploads/") or not path.is_file(): raise HTTPException(400, "请先上传图片")
    provider_url = os.getenv("MOUKE_VISION_API_URL")
    provider_key = os.getenv("MOUKE_VISION_API_KEY")
    if not provider_url or not provider_key:
        return {"caption": f"在{place.short_name}，镜头替我记住了这一刻。", "mode": "template", "vision_used": False}
    mime_by_suffix = {".jpg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
    body = json.dumps({
        "model": os.getenv("MOUKE_VISION_MODEL", "default"),
        "image_base64": base64.b64encode(path.read_bytes()).decode("ascii"),
        "mime_type": mime_by_suffix.get(path.suffix.lower(), "application/octet-stream"),
        "prompt": f"请根据图片写一句自然、有趣、不过度暴露隐私的校园动态文案。地点：{place.name}。语气：{payload.tone}。不超过60个汉字。",
    }).encode("utf-8")
    try:
        req = UrlRequest(provider_url, data=body, headers={"Authorization": f"Bearer {provider_key}", "Content-Type": "application/json", "User-Agent": MAP_USER_AGENT}, method="POST")
        with urlopen(req, timeout=45) as response:
            result = json.loads(response.read().decode("utf-8"))
        caption = str(result.get("caption", "")).strip()
        if not caption: raise ValueError("Vision provider returned no caption")
        return {"caption": caption[:280], "mode": "vision", "vision_used": True}
    except Exception as exc:
        raise HTTPException(502, "图片理解服务暂时不可用") from exc

@app.get("/api/conversations")
def conversations(user:Annotated[User,Depends(get_current_user)],db: Session = Depends(get_db)):
    rows = db.scalars(select(Conversation).options(selectinload(Conversation.messages)).where(Conversation.is_blocked.is_(False), or_(Conversation.initiator_id == user.id, Conversation.recipient_id == user.id)).order_by(Conversation.updated_at.desc())).all()
    return [conversation_out(row,user,db) for row in rows]

@app.post("/api/conversations", status_code=201)
def start_conversation(payload: ConversationCreate, user:Annotated[User,Depends(get_current_user)],db: Session = Depends(get_db)):
    moment = db.scalar(select(Moment).options(selectinload(Moment.location)).where(Moment.id == payload.moment_id))
    if moment is None: raise HTTPException(404, "片段不存在")
    if moment.user_id is None: raise HTTPException(409,"该片段来自旧版匿名数据，无法发起实名账户会话")
    if moment.user_id == user.id: raise HTTPException(400,"不能向自己发起回声")
    existing = db.scalar(select(Conversation).options(selectinload(Conversation.messages)).where(Conversation.origin_moment_id == moment.id, Conversation.initiator_id == user.id))
    if existing is not None: return conversation_out(existing,user,db)
    row = Conversation(initiator_id=user.id,recipient_id=moment.user_id,peer_alias=moment.author_alias,origin_moment_id=moment.id, origin_excerpt=moment.content[:160], location_name=moment.location.name)
    db.add(row); db.flush()
    db.add(ChatMessage(conversation_id=row.id,sender_user_id=user.id,sender="me",content="我想回应你留在这里的这一刻。"))
    db.commit()
    row = db.scalar(select(Conversation).options(selectinload(Conversation.messages)).where(Conversation.id == row.id))
    return conversation_out(row,user,db)

@app.get("/api/conversations/{conversation_id}/messages")
def conversation_messages(conversation_id: int,user:Annotated[User,Depends(get_current_user)],db: Session = Depends(get_db)):
    row = db.scalar(select(Conversation).options(selectinload(Conversation.messages)).where(Conversation.id == conversation_id,Conversation.is_blocked.is_(False),or_(Conversation.initiator_id == user.id,Conversation.recipient_id == user.id)))
    if row is None: raise HTTPException(404, "会话不存在")
    return [message_out(message,user) for message in row.messages]

@app.post("/api/conversations/{conversation_id}/messages", status_code=201)
def send_message(conversation_id: int,payload: MessageCreate,user:Annotated[User,Depends(get_current_user)],db: Session = Depends(get_db)):
    row = db.get(Conversation, conversation_id)
    if row is None or row.is_blocked or user.id not in (row.initiator_id,row.recipient_id): raise HTTPException(404, "会话不存在")
    message = ChatMessage(conversation_id=conversation_id,sender_user_id=user.id,sender="me",content=payload.content.strip())
    row.updated_at = datetime.now(); db.add(message); db.commit(); db.refresh(message)
    return message_out(message,user)

@app.post("/api/conversations/{conversation_id}/block")
def block_conversation(conversation_id: int,user:Annotated[User,Depends(get_current_user)],db: Session = Depends(get_db)):
    row = db.get(Conversation, conversation_id)
    if row is None or user.id not in (row.initiator_id,row.recipient_id): raise HTTPException(404, "会话不存在")
    row.is_blocked = True; db.commit()
    return {"blocked": True}
