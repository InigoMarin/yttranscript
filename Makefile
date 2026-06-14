.PHONY: all pkg deb install deb-install clean rebuild test test-cov lint help

VERSION := 2.15.0
PKGNAME := yttranscript
TARBALL := $(PKGNAME)-$(VERSION).tar.gz
SRC_DIR := $(PKGNAME)-$(VERSION)
SRC_FILES := yttranscript pyproject.toml README.md LICENSE

# Debian packaging
DEB_DATE := $(shell LC_ALL=C date -u '+%a, %d %b %Y %H:%M:%S %z')
DEB_VERSION := $(VERSION)-1
DEB_PKG := $(PKGNAME)_$(DEB_VERSION)_all.deb

all: pkg

help:
	@echo "Targets:"
	@echo "  make pkg         - Build pacman (Arch) package"
	@echo "  make deb         - Build .deb (Debian/Ubuntu) package"
	@echo "  make install     - Build and install pacman package"
	@echo "  make deb-install - Build and install .deb package"
	@echo "  make clean       - Remove build artifacts (pacman + deb)"
	@echo "  make rebuild     - Clean, build and install pacman package"
	@echo "  make test        - Run test suite (pytest)"
	@echo "  make test-cov    - Run tests with coverage report"
	@echo "  make lint        - Run pyflakes on source and tests"

$(TARBALL): $(SRC_FILES)
	rm -rf $(SRC_DIR)
	mkdir -p $(SRC_DIR)
	cp -r $(SRC_FILES) $(SRC_DIR)/
	find $(SRC_DIR) -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	tar czf $(TARBALL) --exclude='__pycache__' $(SRC_DIR)
	@echo "Built $(TARBALL)"

pkg: $(TARBALL)
	makepkg -sf
	@echo ""
	@echo "Package built: $$(ls *.pkg.tar.zst 2>/dev/null)"
	@echo "Install with: sudo pacman -U $$(ls *.pkg.tar.zst)"

install: $(TARBALL)
	makepkg -si --noconfirm

rebuild: clean install

# ---------------------------------------------------------------------------
# Debian package
#
# debian/changelog is generated from debian/changelog.template + VERSION
# so the Makefile's VERSION remains the single source of truth (no fifth
# place to bump manually).
# ---------------------------------------------------------------------------

debian/changelog: debian/changelog.template
	sed -e 's/__VERSION__/$(VERSION)/g' \
	    -e 's/__DATE__/$(DEB_DATE)/g' \
	    debian/changelog.template > debian/changelog
	@echo "Generated debian/changelog for version $(VERSION)-1"

deb: debian/changelog
	dpkg-buildpackage -us -uc -b
	@echo ""
	@echo "Package built: ../$(DEB_PKG)"
	@echo "Install with: sudo apt install ../$(DEB_PKG)"

deb-install: deb
	sudo apt install -y ../$(DEB_PKG)

clean:
	rm -rf yttranscript-* $(TARBALL) pkg/ src/ *.pkg.tar.zst *.tar.gz *.pkg.tar.xz *.pkg.tar.gz
	rm -f debian/changelog
	rm -rf $(CURDIR)/../$(PKGNAME)_*.deb $(CURDIR)/../$(PKGNAME)_*.changes \
	       $(CURDIR)/../$(PKGNAME)_*.buildinfo $(CURDIR)/../$(PKGNAME)_*.dsc
	rm -rf debian/.debhelper debian/files debian/*debhelper* \
	       debian/debhelper-build-stamp debian/$(PKGNAME).substvars \
	       debian/$(PKGNAME)/ debian/tmp/
	@echo "Cleaned"

test:
	python -m pytest

test-cov:
	python -m pytest --cov=yttranscript --cov-report=term-missing

lint:
	python -m pyflakes yttranscript tests
