from html import escape
from hashlib import sha256
import json
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
    "option",
    "radio-button",
    "radio-button-group",
    "select",
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
    """Accept only a complete, current offline bundle, not leftover assets."""
    vendor = static_root() / "vendor"
    if not all(
        (vendor / name).exists()
        for name in (
            "sbb-elements.bundle.js",
            "sbb-variables.css",
            "standard-theme.css",
        )
    ):
        return False
    try:
        manifest = json.loads((vendor / "manifest.json").read_text())
        if not isinstance(manifest, dict):
            return False
        return (
            manifest.get("elements_version") == LYNE_ELEMENTS_VERSION
            and manifest.get("tokens_version") == LYNE_DESIGN_TOKENS_VERSION
            and set(manifest.get("components", [])) == set(LYNE_COMPONENT_MODULES)
            and manifest.get("bundle_sha256")
            == sha256((vendor / "sbb-elements.bundle.js").read_bytes()).hexdigest()
        )
    except (OSError, ValueError, TypeError):
        return False


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


def _attributes(attrs: dict) -> str:
    """Render keyword arguments as escaped HTML attributes.

    Underscored names become hyphenated (``aria_label`` -> ``aria-label``),
    a trailing underscore is dropped (``type_`` -> ``type``), ``True`` renders a
    bare boolean attribute, and ``None``/``False`` are omitted.
    """
    rendered: list[str] = []
    for name, value in attrs.items():
        if value is None or value is False:
            continue
        name = name.rstrip("_").replace("_", "-")
        rendered.append(name if value is True else f'{name}="{escape(str(value))}"')
    return (" " + " ".join(rendered)) if rendered else ""


def element(tag: str, content: str = "", *, css_class: str = "", **attrs) -> str:
    """Render an arbitrary HTML element with escaped attributes."""
    if css_class:
        attrs["class"] = css_class
    return f"<{tag}{_attributes(attrs)}>{content}</{tag}>"


def void_element(tag: str, *, css_class: str = "", **attrs) -> str:
    """Render an HTML void element such as ``<input>``."""
    if css_class:
        attrs["class"] = css_class
    return f"<{tag}{_attributes(attrs)}>"


def title(
    text: str,
    *,
    level: int,
    visual_level: int | None = None,
    css_class: str = "",
    html_id: str = "",
    **attrs,
) -> str:
    return element(
        "sbb-title",
        escape(text),
        level=level,
        visual_level=visual_level,
        css_class=css_class,
        id=html_id or None,
        **attrs,
    )


def image(source: str, *, alt: str, css_class: str = "") -> str:
    return element("sbb-image", "", image_src=source, alt=alt, css_class=css_class)


def chip(text: str, *, size: str = "s") -> str:
    return element("sbb-chip-label", escape(text), size=size)


def card(
    content: str,
    *,
    css_class: str = "",
    color: str = "transparent-bordered",
    html_id: str = "",
) -> str:
    return element("sbb-card", content, color=color, css_class=css_class, id=html_id or None)


def icon(name: str, *, css_class: str = "", slot: str | None = None, **attrs) -> str:
    return element("sbb-icon", "", name=name, slot=slot, css_class=css_class, **attrs)


_BUTTON_TAGS = {
    "primary": "sbb-button",
    "secondary": "sbb-secondary-button",
    "transparent": "sbb-transparent-button",
}


def button(
    text: str = "",
    *,
    variant: str = "primary",
    link: bool = False,
    size: str | None = None,
    html_id: str = "",
    css_class: str = "",
    icon_name: str | None = None,
    icon_placement: str | None = None,
    slot_icon: str | None = None,
    type_: str | None = None,
    href: str | None = None,
    aria_label: str | None = None,
    disabled: bool = False,
    **attrs,
) -> str:
    """Render a Lyne button or button-link.

    Use ``slot_icon`` for markup that expects ``<sbb-icon slot="icon">`` and
    ``icon_name`` for markup that drives the icon through the attribute.
    """
    tag = _BUTTON_TAGS[variant] + ("-link" if link else "")
    content = (icon(slot_icon, slot="icon") if slot_icon else "") + escape(text)
    return element(
        tag,
        content,
        id=html_id or None,
        css_class=css_class,
        size=size,
        icon_name=icon_name,
        icon_placement=icon_placement,
        type=type_,
        href=href,
        aria_label=aria_label,
        disabled=disabled,
        **attrs,
    )


def checkbox(
    label: str,
    *,
    name: str | None = None,
    value: str | int | None = None,
    size: str | None = None,
    checked: bool = False,
    data_setting: str | None = None,
    css_class: str = "",
    **attrs,
) -> str:
    return element(
        "sbb-checkbox",
        escape(label),
        name=name,
        value=value,
        size=size,
        checked=checked,
        data_setting=data_setting,
        css_class=css_class,
        **attrs,
    )


def radio_button(
    label: str,
    *,
    value: str | None = None,
    name: str | None = None,
    checked: bool = False,
    size: str | None = None,
    **attrs,
) -> str:
    return element(
        "sbb-radio-button",
        escape(label),
        value=value,
        name=name,
        checked=checked,
        size=size,
        **attrs,
    )


def select(
    *,
    name: str,
    options: tuple[tuple[str, str], ...],
    value: str | None = None,
    size: str | None = None,
    css_class: str = "",
    html_id: str = "",
    aria_label: str | None = None,
    **attrs,
) -> str:
    """Render a Lyne select with ``(value, label)`` options."""
    inner = "".join(
        element("sbb-option", escape(label), value=option_value, selected=option_value == value)
        for option_value, label in options
    )
    return element(
        "sbb-select",
        inner,
        name=name,
        value=value,
        size=size,
        css_class=css_class,
        id=html_id or None,
        aria_label=aria_label,
        **attrs,
    )


def form_field(
    *,
    label: str,
    input_id: str,
    size: str | None = None,
    width: str | None = None,
    floating_label: bool = False,
    css_class: str = "",
    input_attrs: dict | None = None,
    content: str = "",
) -> str:
    """Render a Lyne form field wrapping a labelled native input."""
    attrs = dict(input_attrs or {})
    attrs.setdefault("id", input_id)
    inner = element("label", escape(label), **{"for": input_id})
    inner += void_element("input", **attrs)
    inner += content
    return element(
        "sbb-form-field",
        inner,
        size=size,
        width=width,
        floating_label=floating_label,
        css_class=css_class,
    )


def container(content: str, *, expanded: bool = False, css_class: str = "") -> str:
    return element("sbb-container", content, color="transparent", expanded=expanded, css_class=css_class)


def menu_button(
    text: str,
    *,
    html_id: str = "",
    icon_name: str | None = None,
    hidden: bool = False,
    **attrs,
) -> str:
    return element(
        "sbb-menu-button",
        escape(text),
        id=html_id or None,
        icon_name=icon_name,
        hidden=hidden,
        **attrs,
    )


def card_link(text: str, *, href: str, **attrs) -> str:
    return element("sbb-card-link", escape(text), href=href, **attrs)


def card_button(text: str, *, html_id: str = "", **attrs) -> str:
    return element("sbb-card-button", escape(text), id=html_id or None, **attrs)
