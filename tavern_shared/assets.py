"""
Loads the header banner image used behind both apps' title bars. Needs
Pillow -- if it (or the embedded banner_data module) isn't available,
_HEADER_BANNER_IMG stays None and both apps fall back to a flat header
background; neither app fails to start because of this.
"""
import io
import base64

_HEADER_BANNER_IMG = None
try:
    from PIL import Image as _PILImage, ImageTk as _PILImageTk, ImageEnhance as _PILImageEnhance
    from banner_data import BANNER_B64 as _BANNER_B64
    _HEADER_BANNER_IMG = _PILImage.open(io.BytesIO(base64.b64decode(_BANNER_B64))).convert("RGB")
except Exception:
    _HEADER_BANNER_IMG = None
