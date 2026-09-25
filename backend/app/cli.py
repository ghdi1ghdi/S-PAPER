import argparse
import getpass
from pydantic import TypeAdapter, EmailStr
from sqlalchemy import select
from .db import SessionLocal
from .auth import hasher
from .models import User


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["create-user"])
    parser.add_argument("--email", required=True)
    parser.add_argument("--admin", action="store_true")
    args = parser.parse_args()
    email = str(TypeAdapter(EmailStr).validate_python(args.email)).lower()
    password = getpass.getpass("Password (12+ characters): ")
    if len(password) < 12 or password != getpass.getpass("Confirm password: "):
        raise SystemExit("비밀번호는 12자 이상이며 확인 값이 일치해야 합니다")
    with SessionLocal() as db:
        if db.scalar(select(User.id).where(User.email == email)):
            raise SystemExit("이미 존재하는 사용자입니다")
        db.add(User(email=email, password_hash=hasher.hash(password), is_admin=args.admin))
        db.commit()
    print("사용자를 생성했습니다")


if __name__ == "__main__":
    main()
