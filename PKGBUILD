# Maintainer: ima <ima@ima.com>
pkgname=yttranscript
pkgver=2.16.0
pkgrel=1
pkgdesc="Download YouTube video transcripts with Whisper fallback"
arch=('any')
url="https://github.com/InigoMarin/yttranscript"
license=('MIT')
depends=('python>=3.9' 'yt-dlp' 'ffmpeg')
makedepends=('python-build' 'python-installer' 'python-setuptools')
optdepends=(
    'python-openai-whisper: for Whisper transcription fallback'
    'pandoc: for PDF output'
    'typst: for PDF output'
)
source=("$pkgname-$pkgver.tar.gz")
sha256sums=('SKIP')

build() {
    cd "$srcdir/$pkgname-$pkgver"
    /usr/bin/python -m build --wheel --no-isolation
}

package() {
    cd "$srcdir/$pkgname-$pkgver"
    /usr/bin/python -m installer --destdir="$pkgdir" dist/*.whl
    install -Dm644 README.md "$pkgdir/usr/share/doc/$pkgname/README.md"
    install -Dm644 LICENSE "$pkgdir/usr/share/licenses/$pkgname/LICENSE"
}
