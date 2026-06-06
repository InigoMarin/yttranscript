.PHONY: all pkg install clean help

VERSION := 1.18.0
PKGNAME := yttranscript
TARBALL := $(PKGNAME)-$(VERSION).tar.gz
SRC_DIR := $(PKGNAME)-$(VERSION)
SRC_FILES := yttranscript.py pyproject.toml README.md LICENSE

all: pkg

help:
	@echo "Targets:"
	@echo "  make pkg       - Build pacman package"
	@echo "  make install   - Build and install package"
	@echo "  make clean     - Remove build artifacts"
	@echo "  make rebuild   - Clean, build and install"

$(TARBALL): $(SRC_FILES)
	rm -rf $(SRC_DIR)
	mkdir -p $(SRC_DIR)
	cp $(SRC_FILES) $(SRC_DIR)/
	tar czf $(TARBALL) $(SRC_DIR)
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
	rm -rf $(SRC_DIR) $(TARBALL) pkg/ src/ *.pkg.tar.zst *.tar.gz
	@echo "Cleaned"
