from html import escape


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

