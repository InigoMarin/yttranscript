# syntax=docker/dockerfile:1.6
#
# yttranscript Docker image: CLI + PDF/EPUB/DOCX export + --email support.
#
# External binaries baked in:
#   - pandoc       (apt)          -> all formats (pdf/epub/docx)
#   - typst        (GitHub)       -> PDF engine
#   - himalaya     (GitHub)       -> --email TO
#
# Build:
#   docker build -t yttranscript .
#   docker build --build-arg TARGETARCH=arm64 -t yttranscript:arm64 .  # cross-build
#
# Run:
#   docker run --rm -v "$PWD:/data" yttranscript URL --format pdf --output-dir /data
#
#   # With email + host config:
#   docker run --rm -v "$PWD:/data" -v "$HOME/.config:/config" \
#       yttranscript URL --format pdf --output-dir /data --email to@example.com

# ---------- build stage: wheel only ----------
FROM python:3.12-slim AS builder

WORKDIR /build
COPY pyproject.toml README.md LICENSE ./
COPY yttranscript/ ./yttranscript/

RUN pip install --no-cache-dir --upgrade pip \
    && pip wheel --no-cache-dir --no-deps -w /wheels .


# ---------- runtime stage ----------
FROM python:3.12-slim AS runtime

ARG TARGETARCH

# Install pandoc via apt, then download static binaries for typst + himalaya.
# Map TARGETARCH (amd64|arm64) to upstream naming (x86_64|aarch64).
RUN set -eux; \
    case "$TARGETARCH" in \
      amd64) TY_ARCH=x86_64 ;; \
      arm64|"") TY_ARCH=aarch64 ;; \
      *) echo "unsupported TARGETARCH: $TARGETARCH" >&2; exit 1 ;; \
    esac; \
    apt-get update && apt-get install -y --no-install-recommends \
        pandoc \
        ca-certificates \
        curl \
        xz-utils \
        fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/* \
    \
    # typst (musl static binary; tarball contains typst-<triple>/typst)
    && curl -fsSL \
        "https://github.com/typst/typst/releases/latest/download/typst-${TY_ARCH}-unknown-linux-musl.tar.xz" \
        | tar -xJ --strip-components=1 -C /usr/local/bin \
            "typst-${TY_ARCH}-unknown-linux-musl/typst" \
    \
    # himalaya (musl static binary, single binary inside the .tgz)
    && curl -fsSL -o /tmp/himalaya.tgz \
        "https://github.com/pimalaya/himalaya/releases/latest/download/himalaya.${TY_ARCH}-linux.tgz" \
    && tar -xzf /tmp/himalaya.tgz -C /usr/local/bin himalaya \
    && rm /tmp/himalaya.tgz \
    \
    && chmod +x /usr/local/bin/typst /usr/local/bin/himalaya \
    && typst --version \
    && himalaya --version

# Install the app + its deps (yt-dlp, tomli on py<3.11) from PyPI.
COPY --from=builder /wheels/*.whl /tmp/
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir /tmp/*.whl \
    && rm /tmp/*.whl

# Non-root user with uid 1000 to align with typical host uids
# (avoids permission headaches when bind-mounting /data and /config).
RUN useradd --uid 1000 --create-home --shell /bin/sh app

ENV HOME=/home/app \
    XDG_CONFIG_HOME=/config \
    XDG_CACHE_HOME=/home/app/.cache \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /data
VOLUME ["/data", "/config"]

USER app
ENTRYPOINT ["yttranscript"]
CMD ["--help"]
