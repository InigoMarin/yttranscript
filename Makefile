.PHONY: all pkg install clean rebuild test test-cov lint help

VERSION := 2.2.0
PKGNAME := yttranscript
TARBALL := $(PKGNAME)-$(VERSION).tar.gz
SRC_DIR := $(PKGNAME)-$(VERSION)
SRC_FILES := yttranscript pyproject.toml README.md LICENSE

all: pkg

help:
	@echo "Targets:"
	@echo "  make pkg       - Build pacman package"
	@echo "  make install   - Build and install package"
	@echo "  make clean     - Remove build artifacts"
	@echo "  make rebuild   - Clean, build and install"
	@echo "  make test      - Run test suite (pytest)"
	@echo "  make test-cov  - Run tests with coverage report"
	@echo "  make lint      - Run pyflakes on source and tests"

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

clean:
	rm -rf yttranscript-* $(TARBALL) pkg/ src/ *.pkg.tar.zst *.tar.gz
	@echo "Cleaned"

test:
	python -m pytest

test-cov:
	python -m pytest --cov=yttranscript --cov-report=term-missing

lint:
	python -m pyflakes yttranscript tests
