def _build_right_content(
    case_title: str,
    case_subtitle: str,
    points: list[str],
) -> str:
    """Build the right-side content area for a content slide.

    Layout matches html_format.txt reference:
    - Right title (Noto Sans SC 700, 20px)
    - Right subtitle (Noto Sans SC 400, 13px, #6B7280)
    - Points as bullet items with custom dot markers
    """
    parts: list[str] = []

    # Right title
    if case_title:
        parts.append(
            "<p style=\"font-family: 'Noto Sans SC', sans-serif; font-weight: 700; "
            "font-size: 20px; color: #0A0A0A; margin-bottom: 6px;\">"
            + case_title
            + "</p>"
        )

    # Right subtitle
    if case_subtitle:
        parts.append(
            "<p style=\"font-family: 'Noto Sans SC', sans-serif; font-weight: 400; "
            "font-size: 13px; color: #6B7280; margin-bottom: 20px; line-height: 1.5;\">"
            + case_subtitle
            + "</p>"
        )

    # Points with styled dot markers
    if points:
        for pt in points:
            safe_pt = html_mod.escape(pt)
            parts.append(
                '<div style="display: flex; align-items: flex-start; margin-bottom: 12px;">'
                '<div style="width: 6px; height: 6px; border-radius: 50%; background: #1a3d32; '
                'margin-top: 7px; margin-right: 10px; flex-shrink: 0;"></div>'
                "<p style=\"font-family: 'Noto Sans SC', sans-serif; font-weight: 400; "
                "font-size: 13px; color: #374151; line-height: 1.6; margin: 0;\">"
                + safe_pt
                + "</p></div>"
            )

    return "\n".join(parts)
