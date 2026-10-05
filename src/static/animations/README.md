# Contactless NFC Tap Reader Animations

`nfc-tap-dark.gif` and `nfc-tap-light.gif` are custom-rendered transit-style contactless card tap animations designed for LabAuth:
- **`nfc-tap-dark.gif`**: SBB Red outline and contactless wave symbol on `--sbb-color-midnight` (`#151515`) dark terminal surface.
- **`nfc-tap-light.gif`**: SBB Red outline and contactless wave symbol on `--sbb-color-milk` (`#f6f6f6`) light terminal surface.

### Generation Script
Both animations are generated via `python src/static/animations/generate_nfc_gifs.py` using Pillow with 2x supersampling and Lanczos downsampling for crisp antialiasing and exact background surface matching.
