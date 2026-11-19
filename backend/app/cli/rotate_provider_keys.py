from app.core.database import SessionLocal
from app.core.provider_keys import rotate_provider_credentials
from app.core.security import provider_active_key_id


def main() -> None:
    with SessionLocal() as session:
        result = rotate_provider_credentials(session)
    print(
        "Provider credential rotation complete: "
        f"active_key={provider_active_key_id()} "
        f"rotated={result.rotated} "
        f"verified_current={result.verified_current}"
    )


if __name__ == "__main__":
    main()
