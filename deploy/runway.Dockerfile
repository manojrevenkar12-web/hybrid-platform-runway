# runway API: non-root, any UID (OpenShift's restricted SCC assigns one), read-only root filesystem.
FROM python:3.12-slim AS build
WORKDIR /src
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir --prefix=/install .

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 RUNWAY_CONFIG=/app/config TMPDIR=/tmp
COPY --from=build /install /usr/local
COPY config /app/config
USER 1001
EXPOSE 8070
HEALTHCHECK --interval=10s --timeout=3s CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8070/healthz')"
ENTRYPOINT ["runway", "serve", "--port", "8070"]
