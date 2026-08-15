from datetime import datetime
from pydantic import BaseModel, Field

class MomentCreate(BaseModel):
    location_id: int
    content: str = Field(default="", max_length=280)
    mood: str = Field(default="平静", max_length=20)
    image_url: str | None = Field(default=None, max_length=255)

class MomentOut(BaseModel):
    id: int
    location_id: int
    location_name: str
    author_alias: str
    content: str
    image_url: str | None = None
    mood: str
    created_at: datetime
    resonance_count: int
    echo_count: int
    is_official: bool

class ResonanceCreate(BaseModel):
    kind: str = Field(pattern="^(我也这样|抱抱你|我曾经也是)$")

class EchoCreate(BaseModel):
    content: str = Field(min_length=1, max_length=30)

class PromptRequest(BaseModel):
    location_id: int
    draft: str = Field(default="", max_length=280)

class ImageCaptionRequest(BaseModel):
    image_url: str = Field(max_length=255)
    location_id: int
    tone: str = Field(default="轻松自然", max_length=30)

class ReplySuggestionRequest(BaseModel):
    conversation_id: int

class SuggestionFeedbackCreate(BaseModel):
    context_type: str = Field(pattern="^(reply|caption)$")
    suggestion: str = Field(default="", max_length=500)
    final_text: str = Field(min_length=1, max_length=500)
    selected_rank: int | None = Field(default=None, ge=1, le=3)

class ConversationCreate(BaseModel):
    moment_id: int

class MessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=500)

class VerificationRequest(BaseModel):
    student_id: str = Field(pattern=r"^[A-Za-z0-9]{6,20}$")
    email: str = Field(max_length=120)

class RegisterRequest(VerificationRequest):
    code: str = Field(pattern=r"^\d{6}$")
    password: str = Field(min_length=8, max_length=128)

class LoginRequest(BaseModel):
    student_id: str = Field(pattern=r"^[A-Za-z0-9]{6,20}$")
    password: str = Field(min_length=8, max_length=128)

class PrivacyUpdate(BaseModel):
    share_location: bool

class PositionUpdate(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class AnalyticsEventCreate(BaseModel):
    event_name: str = Field(pattern="^(app_open|page_view|session_ping|moment_published|conversation_started|message_sent)$")
    session_id: str = Field(min_length=8, max_length=64)
    page: str | None = Field(default=None, max_length=80)
    duration_seconds: int | None = Field(default=None, ge=0, le=86400)


class AdminUserStatusUpdate(BaseModel):
    is_active: bool


class AdminMomentVisibilityUpdate(BaseModel):
    is_hidden: bool
