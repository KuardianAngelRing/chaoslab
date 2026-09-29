"""EKS 시연용 — Online Boutique(up.sh가 설치하는 SUT)를 대시보드 App 행으로 등록한다(멱등).

실서비스 모드(USE_REAL_SERVICES=true)는 mock seed를 돌리지 않아 이 행이 없으면 위저드가 비어 있다.
관측 Service는 frontend(회귀 관측·단독 실험 트래픽 대상). scripts/demo-up.sh가 호출하며
DATABASE_URL·SUT_NAMESPACE는 환경변수로 넘긴다. 직접 실행: `.venv/bin/python scripts/register_boutique.py`
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings  # noqa: E402
from app.db.database import SessionLocal, init_db  # noqa: E402
from app.db.models import App  # noqa: E402

NAME = "online-boutique"


def main() -> None:
    init_db()
    session = SessionLocal()
    try:
        app = session.query(App).filter(App.name == NAME).one_or_none()
        if app is None:
            app = App(name=NAME, repo_url="https://github.com/GoogleCloudPlatform/microservices-demo",
                      framework="go", env="eks", status="healthy", current_sha="v0.10.5")
            session.add(app)
            verb = "등록"
        else:
            verb = "갱신"
        app.namespace = settings.sut_namespace
        app.observe_service = "frontend"
        app.health_path = "/"
        app.port = 80
        session.commit()
        print(f"  {verb}: {app.name} (env={app.env}, ns={app.namespace}, observe_service={app.observe_service}, "
              f"db={settings.database_url})")
    finally:
        session.close()


if __name__ == "__main__":
    main()
