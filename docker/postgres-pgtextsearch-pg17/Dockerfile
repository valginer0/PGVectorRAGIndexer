ARG PG_TEXTSEARCH_VERSION=v1.2.0

FROM pgvector/pgvector:pg17

ARG PG_TEXTSEARCH_VERSION

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        git \
        postgresql-server-dev-17 \
    && git clone --depth 1 --branch "$PG_TEXTSEARCH_VERSION" \
        https://github.com/timescale/pg_textsearch.git /tmp/pg_textsearch \
    && cd /tmp/pg_textsearch \
    && PG_CONFIG=/usr/lib/postgresql/17/bin/pg_config make \
    && PG_CONFIG=/usr/lib/postgresql/17/bin/pg_config make install \
    && rm -rf /tmp/pg_textsearch \
    && apt-get purge -y --auto-remove \
        build-essential \
        git \
        postgresql-server-dev-17 \
    && rm -rf /var/lib/apt/lists/*
