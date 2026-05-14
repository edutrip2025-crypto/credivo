import sys
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.main import app


SEED_USERS = [
    {
        "email": "provider.assessment@example.com",
        "full_name": "Assessment Provider",
        "password": "Provider@12345",
        "role": "provider",
    },
    {
        "email": "student.assessment@example.com",
        "full_name": "Assessment Student",
        "password": "Student@12345",
        "role": "student",
    },
]


def main() -> None:
    client = TestClient(app)
    print("Seeding assessment users...")
    for user in SEED_USERS:
        response = client.post("/auth/signup", json=user)
        if response.status_code == 201:
            print(f"[created] {user['role']}: {user['email']}")
            continue
        if response.status_code == 400 and "Email already in use" in response.text:
            print(f"[exists]  {user['role']}: {user['email']}")
            continue
        print(f"[error]   {user['role']}: {user['email']} -> {response.status_code} {response.text}")
    print("Done.")
    print("Provider login -> provider.assessment@example.com / Provider@12345")
    print("Student  login -> student.assessment@example.com / Student@12345")


if __name__ == "__main__":
    main()
