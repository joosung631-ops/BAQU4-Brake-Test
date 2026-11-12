# ROS 없이 토픽 통계를 수신하고 웹 화면을 제공할 Python 실행 환경입니다.
# 빌드 컨텍스트: dashboard/ (프로젝트 루트의 docker-compose.yml 참고).
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DASHBOARD_HOST=0.0.0.0 \
    DASHBOARD_PORT=8080

# 별도 컨테이너이므로 Python 패키지를 위한 추가 venv는 만들지 않습니다.
COPY docker/requirements.txt /tmp/dashboard-requirements.txt
RUN python -m pip install --no-cache-dir -r /tmp/dashboard-requirements.txt \
    && rm /tmp/dashboard-requirements.txt

RUN groupadd --gid 10001 dashboard \
    && useradd --uid 10001 --gid dashboard --create-home \
        --shell /usr/sbin/nologin dashboard

WORKDIR /workspace
COPY --chown=dashboard:dashboard . /workspace
USER dashboard

# 컨테이너 내부에서는 모든 인터페이스로 수신하고, 호스트에서의 접근 범위는
# Compose의 127.0.0.1 포트 매핑으로 제한합니다. EXPOSE 자체는 포트를 공개하지 않습니다.
EXPOSE 8080

# /workspace/dashboard/__main__.py에서 위 환경변수를 읽고 웹서버를 시작합니다.
CMD ["python", "-m", "dashboard"]
