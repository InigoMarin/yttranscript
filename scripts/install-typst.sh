#!/usr/bin/env bash
#
# install-typst.sh — download the latest static typst binary from GitHub
# releases and install it into /usr/local/bin.
#
# Works on any Linux distro (Debian, Ubuntu, Arch, Fedora, ...) without
# compiling. Useful where `apt install typst` is not available (Ubuntu has
# never packaged the typst CLI; Debian only since 13/trixie).
#
# Usage:
#   bash scripts/install-typst.sh                 # latest release
#   bash scripts/install-typst.sh --version v0.14.2   # specific tag
#
set -euo pipefail

VERSION="latest"
while [[ $# -gt 0 ]]; do
    case "$1" in
        --version)
            VERSION="$2"
            shift 2
            ;;
        --version=*)
            VERSION="${1#*=}"
            shift
            ;;
        -h|--help)
            sed -n '2,12p' "$0"
            exit 0
            ;;
        *)
            echo "Unknown argument: $1" >&2
            exit 2
            ;;
    esac
done

# 1. Detect architecture (typst publishes x86_64 and aarch64 musl binaries).
ARCH_RAW="$(uname -m)"
case "$ARCH_RAW" in
    x86_64|amd64)   T_ARCH="x86_64"  ;;
    aarch64|arm64)  T_ARCH="aarch64" ;;
    *)
        echo "ERROR: unsupported architecture: $ARCH_RAW" >&2
        echo "       typst releases only include x86_64 and aarch64." >&2
        exit 1
        ;;
esac

# 2. Build the download URL.
#    The tarball contains typst-<arch>-unknown-linux-musl/typst (strip 1 component).
TRIPLET="typst-${T_ARCH}-unknown-linux-musl"
if [[ "$VERSION" == "latest" ]]; then
    URL="https://github.com/typst/typst/releases/latest/download/${TRIPLET}.tar.xz"
else
    URL="https://github.com/typst/typst/releases/download/${VERSION}/${TRIPLET}.tar.xz"
fi

echo "  arch:     $T_ARCH"
echo "  version:  $VERSION"
echo "  url:      $URL"
echo

# 3. Check required tools are in PATH (tar must support -J for xz).
for dep in curl tar xz install; do
    if ! command -v "$dep" >/dev/null 2>&1; then
        echo "ERROR: required tool '$dep' is not in PATH." >&2
        echo "       On Debian/Ubuntu: sudo apt install -y curl tar xz-utils coreutils" >&2
        exit 1
    fi
done

# 4. Download + extract into a temp dir (cleaned up on exit).
TMPDIR="$(mktemp -d)"
trap 'rm -rf "$TMPDIR"' EXIT

echo "Downloading..."
curl -fL --progress-bar -o "$TMPDIR/typst.tar.xz" "$URL"

echo "Extracting..."
if ! tar -xJf "$TMPDIR/typst.tar.xz" -C "$TMPDIR" --strip-components=1 "${TRIPLET}/typst"; then
    echo "ERROR: the downloaded .tar.xz does not contain ${TRIPLET}/typst." >&2
    echo "       The release format may have changed; inspect: $URL" >&2
    exit 1
fi

# 5. Install into /usr/local/bin (use sudo if not root).
DEST="/usr/local/bin/typst"
SUDO=""
if [[ $EUID -ne 0 ]]; then
    SUDO="sudo"
fi

echo "Installing to $DEST ..."
$SUDO install -m 0755 "$TMPDIR/typst" "$DEST"

# 6. Verify.
echo
"$DEST" --version

echo
echo "typst installed at $DEST"
