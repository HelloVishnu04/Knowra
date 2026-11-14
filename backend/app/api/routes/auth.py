from fastapi import APIRouter

router = APIRouter()


@router.post("/register")
async def register():
    return {"status": "ok", "message": "Registered successfully"}


@router.post("/login")
async def login():
    return {"access_token": "fake_token", "token_type": "bearer"}


@router.post("/refresh")
async def refresh():
    return {"access_token": "fake_token", "token_type": "bearer"}
