from uuid import UUID

from fastapi import APIRouter, Query, Request, Response

from support_agent.dependencies import CurrentUser, Database, PlatformAdmin
from support_agent.schemas import Login, TokenOut, UserCreate, UserOut, UserStatus
from support_agent.services import identity

router = APIRouter(tags=["Identity"])


@router.post("/auth/login", response_model=TokenOut)
def login(data: Login, request: Request, db: Database, response: Response):
    response.headers["Cache-Control"] = "no-store"
    return identity.login(db, data, request.app.state.settings, request)


@router.get("/auth/me", response_model=UserOut)
def me(user: CurrentUser):
    return user


@router.post("/auth/logout", status_code=204)
def logout(request: Request, db: Database, user: CurrentUser):
    identity.logout(db, request.state.session_id, request)
    return Response(status_code=204)


@router.post("/users", response_model=UserOut, status_code=201)
def create_user(data: UserCreate, request: Request, db: Database, admin: PlatformAdmin):
    return identity.create_user(db, data, request)


@router.get("/users", response_model=list[UserOut])
def users(
    db: Database,
    admin: PlatformAdmin,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    return identity.list_users(db, limit, offset)


@router.patch("/users/{user_id}", response_model=UserOut)
def user_status(
    user_id: UUID, data: UserStatus, request: Request, db: Database, admin: PlatformAdmin
):
    return identity.set_user_status(db, user_id, data.status, request)
