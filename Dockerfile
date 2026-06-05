# Redline — review surface with Markdown -> .docx export (pandoc) baked in.
FROM python:3.12-slim

# pandoc enables Markdown -> .docx with linked citations (--citeproc).
RUN apt-get update \
    && apt-get install -y --no-install-recommends pandoc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY server/ /app/server/
COPY web/    /app/web/

ENV REDLINE_WEB=/app/web \
    REDLINE_DATA=/work/.redline \
    REDLINE_PORT=8787 \
    REDLINE_HOST=0.0.0.0

EXPOSE 8787

# /work is the bind-mounted project directory (docs + .redline live here).
WORKDIR /work
CMD ["python", "/app/server/redline.py"]
