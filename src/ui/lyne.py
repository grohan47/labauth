from html import escape
from hashlib import sha256
import sys
from pathlib import Path

LYNE_ELEMENTS_VERSION = "5.8.0"
LYNE_DESIGN_TOKENS_VERSION = "2.1.3"
JSDELIVR_NPM = "https://cdn.jsdelivr.net/npm"

# Every component the server-rendered pages use, in load order. ``menu`` also
# registers ``sbb-menu-button``; the dialog subcomponents ship with ``dialog``.
LYNE_COMPONENT_MODULES = (
    "button",
    "card",
    "carousel",
    "checkbox",
    "checkbox-group",
    "chip-label",
    "clock",
    "container",
    "dialog",
    "divider",
    "form-field",
    "header",
    "icon",
    "image",
    "link",
    "logo",
    "menu",
    "notification",
    "radio-button",
    "radio-button-group",
    "signet",
    "title",
)


def static_root() -> Path:
    """Locate the static asset directory, including inside a frozen bundle."""
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    else:
        base = Path(__file__).resolve().parent.parent / "static"
    return base


def asset_url(name: str) -> str:
    """Use a content version so normal navigation always gets matching assets."""
    path = static_root() / name
    version = sha256(path.read_bytes()).hexdigest()[:12] if path.exists() else "missing"
    return f"/static/{name}?v={version}"


def has_vendored_lyne() -> bool:
    """True when the offline bundle from ``npm run build:assets`` is present."""
    vendor = static_root() / "vendor"
    return all(
        (vendor / name).exists()
        for name in (
            "sbb-elements.bundle.js",
            "sbb-variables.css",
            "standard-theme.css",
        )
    )


def lyne_assets() -> str:
    """Return the Lyne stylesheet and component tags for a page head.

    The vendored bundle is preferred so the app works offline; version-pinned
    jsDelivr modules are the fallback when it has not been built.
    """
    if has_vendored_lyne():
        return f"""
        <link rel="stylesheet" href="{asset_url("vendor/sbb-variables.css")}">
        <link rel="stylesheet" href="{asset_url("vendor/standard-theme.css")}">
        <script type="module" src="{asset_url("vendor/sbb-elements.bundle.js")}"></script>
        """
    styles = f"""
        <link rel="stylesheet" href="{JSDELIVR_NPM}/@sbb-esta/lyne-design-tokens@{LYNE_DESIGN_TOKENS_VERSION}/dist/css/sbb-variables.css">
        <link rel="stylesheet" href="{JSDELIVR_NPM}/@sbb-esta/lyne-elements@{LYNE_ELEMENTS_VERSION}/standard-theme.css">
        """
    modules = "\n".join(
        f'<script type="module" src="{JSDELIVR_NPM}/@sbb-esta/'
        f'lyne-elements@{LYNE_ELEMENTS_VERSION}/{module}.js/+esm"></script>'
        for module in LYNE_COMPONENT_MODULES
    )
    return f"{styles}\n{modules}"


def title(
    text: str,
    *,
    level: int,
    visual_level: int | None = None,
    css_class: str = "",
    html_id: str = "",
) -> str:
    class_attribute = f' class="{escape(css_class)}"' if css_class else ""
    id_attribute = f' id="{escape(html_id)}"' if html_id else ""
    visual_attribute = f' visual-level="{visual_level}"' if visual_level else ""
    return (
        f'<sbb-title level="{level}"{visual_attribute}{class_attribute}{id_attribute}>'
        f"{escape(text)}"
        "</sbb-title>"
    )


def image(source: str, *, alt: str, css_class: str = "") -> str:
    class_attribute = f' class="{escape(css_class)}"' if css_class else ""
    return (
        f'<sbb-image image-src="{escape(source)}" alt="{escape(alt)}"'
        f"{class_attribute}></sbb-image>"
    )


def chip(text: str, *, size: str = "s") -> str:
    return f'<sbb-chip-label size="{escape(size)}">{escape(text)}</sbb-chip-label>'


def card(
    content: str,
    *,
    css_class: str = "",
    color: str = "transparent-bordered",
) -> str:
    class_attribute = f' class="{escape(css_class)}"' if css_class else ""
    return (
        f'<sbb-card color="{escape(color)}"{class_attribute}>'
        f"{content}"
        "</sbb-card>"
    )


def icon(name: str, *, css_class: str = "") -> str:
    class_attribute = f' class="{escape(css_class)}"' if css_class else ""
    return f'<sbb-icon name="{escape(name)}"{class_attribute}></sbb-icon>'

