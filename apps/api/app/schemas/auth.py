from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=1024)


class SessionResponse(BaseModel):
    authenticated: bool
    username: str | None = None
    csrf_token: str | None = None
    role: str | None = None
    setup_required: bool = False


class SetupRequest(BaseModel):
    code: str = Field(min_length=20, max_length=128)
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=12, max_length=1024)


class UsernameChange(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    current_password: str = Field(min_length=1, max_length=1024)


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=1024)
    new_password: str = Field(min_length=12, max_length=1024)


class InviteRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    role: str = Field(pattern="^(admin|member)$")


class RedeemRequest(BaseModel):
    token: str = Field(min_length=20, max_length=128)
    password: str = Field(min_length=12, max_length=1024)


class UserChange(BaseModel):
    role: str | None = Field(default=None, pattern="^(admin|member)$")
    active: bool | None = None


class UserDelete(BaseModel):
    confirm_username: str = Field(min_length=3, max_length=128)
    current_password: str = Field(min_length=1, max_length=1024)
