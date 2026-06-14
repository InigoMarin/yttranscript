#!/usr/bin/env bash
#
# install-himalaya.sh — download the latest static himalaya binary from GitHub
# releases and install it into /usr/local/bin.
#
# Works on any Linux distro (Debian, Ubuntu, Arch, Fedora, ...) without
# compiling. Useful where `apt install himalaya` is not available (Ubuntu has
# never packaged himalaya; Debian only since 13/trixie).
#
# Usage:
#   bash scripts/install-himalaya.sh                 # latest release
#   bash scripts/install-himalaya.sh --version v1.2.0    # specific tag
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

# 1. Detect architecture (himalaya publishes x86_64 and aarch64 only).
ARCH_RAW="$(uname -m)"
case "$ARCH_RAW" in
    x86_64|amd64)   H_ARCH="x86_64"  ;;
    aarch64|arm64)  H_ARCH="aarch64" ;;
    *)
        echo "ERROR: unsupported architecture: $ARCH_RAW" >&2
        echo "       himalaya releases only include x86_64 and aarch64." >&2
        exit 1
        ;;
esac

# 2. Build the download URL.
if [[ "$VERSION" == "latest" ]]; then
    URL="https://github.com/pimalaya/himalaya/releases/latest/download/himalaya.${H_ARCH}-linux.tgz"
else
    URL="https://github.com/pimalaya/himalaya/releases/download/${VERSION}/himalaya.${H_ARCH}-linux.tgz"
fi

echo "  arch:     $H_ARCH"
echo "  version:  $VERSION"
echo "  url:      $URL"
echo

# 3. Check required tools are in PATH.
for dep in curl tar install; do
    if ! command -v "$dep" >/dev/null 2>&1; then
        echo "ERROR: required tool '$dep' is not in PATH." >&2
        echo "       On Debian/Ubuntu: sudo apt install -y curl tar coreutils" >&2
        exit 1
    fi
done

# 4. Download + extract into a temp dir (cleaned up on exit).
TMPDIR="$(mktemp -d)"
trap 'rm -rf "$TMPDIR"' EXIT

echo "Downloading..."
curl -fL --progress-bar -o "$TMPDIR/himalaya.tgz" "$URL"

echo "Extracting..."
if ! tar -xzf "$TMPDIR/himalaya.tgz" -C "$TMPDIR" himalaya; then
    echo "ERROR: the downloaded .tgz does not contain a top-level 'himalaya' binary." >&2
    echo "       The release format may have changed; inspect: $URL" >&2
    exit 1
fi

# 5. Install into /usr/local/bin (use sudo if not root).
DEST="/usr/local/bin/himalaya"
SUDO=""
if [[ $EUID -ne 0 ]]; then
    SUDO="sudo"
fi

echo "Installing to $DEST ..."
$SUDO install -m 0755 "$TMPDIR/himalaya" "$DEST"

# 6. Verify.
echo
"$DEST" --version

echo
echo "himalaya installed at $DEST"
echo
echo "Next: configure your account in ~/.config/himalaya/config.toml"
echo "      Examples: https://github.com/pimalaya/himalaya#configuration"
