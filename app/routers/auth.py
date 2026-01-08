"""Authentication routes: signup, login, refresh, me."""

from datetime import date
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel, EmailStr, Field

from app.database import get_db
from app.models.user import User, AuthProvider
from app.schemas.user import (
    UserCreate,
    UserLogin,
    UserResponse,
    AuthResponse,
    RefreshTokenRequest,
    Token,
    PasswordChange,
)
from app.utils.auth import (
    hash_password,
    verify_password,
    create_access_token,
    create_refresh_token,
    decode_token,
    get_current_user,
)

router = APIRouter(prefix="/api/auth", tags=["Authentication"])


# --- Request Schemas for Availability Checks ---


class EmailCheckRequest(BaseModel):
    """Request body for email availability check."""

    email: EmailStr


class UsernameCheckRequest(BaseModel):
    """Request body for username availability check."""

    username: str = Field(..., min_length=3, max_length=50)


# --- Helper Functions ---


def calculate_age(birthday: date) -> int:
    """Calculate age from birthday."""
    today = date.today()
    return (
        today.year
        - birthday.year
        - ((today.month, today.day) < (birthday.month, birthday.day))
    )


# --- Availability Check Endpoints ---


@router.post("/check-email")
async def check_email(data: EmailCheckRequest, db: AsyncSession = Depends(get_db)):
    """
    Check if an email is available for registration.
    Uses POST to avoid leaking email addresses in URLs or server logs.
    """
    result = await db.execute(select(User).where(User.email == data.email))
    exists = result.scalar_one_or_none() is not None
    return {"available": not exists}


@router.post("/check-username")
async def check_username(
    data: UsernameCheckRequest, db: AsyncSession = Depends(get_db)
):
    """
    Check if a username is available.
    If taken, suggest alternatives.
    """
    result = await db.execute(select(User).where(User.username == data.username))
    exists = result.scalar_one_or_none() is not None

    suggestions = []
    if exists:
        # Generate simple alternatives
        for suffix in ["1", "2", "_", "99", "x"]:
            candidate = f"{data.username}{suffix}"
            check = await db.execute(select(User).where(User.username == candidate))
            if check.scalar_one_or_none() is None:
                suggestions.append(candidate)
            if len(suggestions) >= 3:
                break

    return {"available": not exists, "suggestions": suggestions}


# --- Signup Endpoint ---


@router.post(
    "/signup", response_model=AuthResponse, status_code=status.HTTP_201_CREATED
)
async def signup(user_data: UserCreate, db: AsyncSession = Depends(get_db)):
    """
    Register a new user account (atomic).
    All validation happens here. No partial users ever exist.
    """
    # Check email uniqueness
    result = await db.execute(select(User).where(User.email == user_data.email))
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered"
        )

    # Check username uniqueness
    result = await db.execute(select(User).where(User.username == user_data.username))
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Username already taken"
        )

    # Validate age (must be at least 13)
    age = calculate_age(user_data.birthday)
    if age < 13:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You must be at least 13 years old",
        )

    # Create user
    user = User(
        email=user_data.email,
        username=user_data.username,
        password_hash=hash_password(user_data.password),
        display_name=user_data.display_name,
        birthday=user_data.birthday,
        auth_provider=AuthProvider.LOCAL.value,
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)

    # Generate tokens
    access_token = create_access_token(user.id)
    refresh_token = create_refresh_token(user.id)

    return AuthResponse(
        user=UserResponse.model_validate(user),
        access_token=access_token,
        refresh_token=refresh_token,
    )


@router.post("/login", response_model=AuthResponse)
async def login(credentials: UserLogin, db: AsyncSession = Depends(get_db)):
    """
    Authenticate user and return tokens.

    Flow:
    1. Find user by email
    2. Verify password
    3. Generate new tokens
    4. Return user + tokens
    """
    # Find user
    result = await db.execute(select(User).where(User.email == credentials.email))
    user = result.scalar_one_or_none()

    if not user or not verify_password(credentials.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password"
        )

    # Generate tokens
    access_token = create_access_token(user.id)
    refresh_token = create_refresh_token(user.id)

    return AuthResponse(
        user=UserResponse.model_validate(user),
        access_token=access_token,
        refresh_token=refresh_token,
    )


@router.post("/refresh", response_model=Token)
async def refresh_token(
    request: RefreshTokenRequest, db: AsyncSession = Depends(get_db)
):
    """
    Get new access token using refresh token.

    Flow:
    1. Decode refresh token
    2. Verify it's a refresh type
    3. Verify user still exists
    4. Issue new access token
    """
    payload = decode_token(request.refresh_token)

    if payload is None or payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token"
        )

    user_id = payload.get("sub")

    # Verify user exists
    result = await db.execute(select(User).where(User.id == int(user_id)))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found"
        )

    # Generate new access token
    access_token = create_access_token(user.id)
    new_refresh_token = create_refresh_token(user.id)

    return Token(access_token=access_token, refresh_token=new_refresh_token)


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    """Get current authenticated user's profile."""
    return UserResponse.model_validate(current_user)


@router.post("/change-password")
async def change_password(
    data: PasswordChange,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Change current user's password."""
    # Google users don't have a password hash
    if current_user.password_hash is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Accounts logged in with Google do not have a password. Please use Google to login.",
        )

    if not verify_password(data.current_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Incorrect current password"
        )

    current_user.password_hash = hash_password(data.new_password)
    await db.flush()

    return {"message": "Password updated successfully"}


@router.post("/google/verify")
async def google_verify(request: dict, db: AsyncSession = Depends(get_db)):
    """
    Verify Google token and check if user already exists.
    Returns is_new_user boolean to determine next steps:
    - If existing user: returns tokens (login complete)
    - If new user: returns google_data for multi-step signup
    """
    from google.oauth2 import id_token
    from google.auth.transport import requests as google_requests
    from app.config import settings

    token = request.get("token")
    if not token:
        raise HTTPException(status_code=400, detail="Token is required")

    # Verify with Google
    try:
        idinfo = id_token.verify_oauth2_token(
            token, google_requests.Request(), settings.GOOGLE_CLIENT_ID
        )

        # Reject unverified emails
        if not idinfo.get("email_verified", False):
            raise HTTPException(
                status_code=400,
                detail="Google account email is not verified. Please verify your email first.",
            )

        google_id = idinfo["sub"]
        email = idinfo["email"]
        name = idinfo.get("name", email.split("@")[0])
        picture = idinfo.get("picture")

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Invalid Google token: {str(e)}")

    # Check if user already exists by google_id
    result = await db.execute(select(User).where(User.google_id == google_id))
    user = result.scalar_one_or_none()

    if user:
        # Existing Google user - log them in
        access_token = create_access_token(user.id)
        refresh_token = create_refresh_token(user.id)
        return {
            "is_new_user": False,
            "user": UserResponse.model_validate(user).model_dump(),
            "access_token": access_token,
            "refresh_token": refresh_token,
        }

    # Check if email exists but with local auth
    result = await db.execute(select(User).where(User.email == email))
    existing_local = result.scalar_one_or_none()

    if existing_local:
        # Email exists with password-based login
        raise HTTPException(
            status_code=400,
            detail="An account with this email already exists. Please log in with your password.",
        )

    # New user - return data for multi-step signup
    base_username = email.split("@")[0].lower().replace(".", "_")
    return {
        "is_new_user": True,
        "google_data": {"email": email, "name": name, "picture": picture},
        "suggested_username": base_username,
    }


class GoogleSignupRequest(BaseModel):
    """Request body for completing Google signup."""

    token: str
    birthday: date
    username: str = Field(..., min_length=3, max_length=50)


@router.post(
    "/google/signup", response_model=AuthResponse, status_code=status.HTTP_201_CREATED
)
async def google_signup(data: GoogleSignupRequest, db: AsyncSession = Depends(get_db)):
    """
    Complete Google signup with birthday and username.
    This is the atomic creation step for Google OAuth users.
    """
    from google.oauth2 import id_token
    from google.auth.transport import requests as google_requests
    from app.config import settings

    # Re-verify Google token
    try:
        idinfo = id_token.verify_oauth2_token(
            data.token, google_requests.Request(), settings.GOOGLE_CLIENT_ID
        )
        google_id = idinfo["sub"]
        email = idinfo["email"]
        name = idinfo.get("name", email.split("@")[0])
        picture = idinfo.get("picture")
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Invalid Google token: {str(e)}")

    # Check username availability
    result = await db.execute(select(User).where(User.username == data.username))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Username already taken")

    # Validate age
    age = calculate_age(data.birthday)
    if age < 13:
        raise HTTPException(status_code=400, detail="You must be at least 13 years old")

    # Create user
    user = User(
        email=email,
        username=data.username,
        google_id=google_id,
        display_name=name,
        avatar_url=picture,
        birthday=data.birthday,
        auth_provider=AuthProvider.GOOGLE.value,
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)

    # Generate tokens
    access_token = create_access_token(user.id)
    refresh_token = create_refresh_token(user.id)

    return AuthResponse(
        user=UserResponse.model_validate(user),
        access_token=access_token,
        refresh_token=refresh_token,
    )
