from __future__ import annotations

from ai.core.files import (
    VISION_IMAGE_TYPES,
    build_multimodal_user_content,
    format_parsed_note,
    parse_attachments,
)

# Back-compat alias for local fallback / older imports.
CHAT_IMAGE_TYPES = VISION_IMAGE_TYPES


def prepare_attachment_context(attachments, include_image_data=True):
    """Legacy tuple API used by local fallback: names, text_notes, image_parts."""
    parsed = parse_attachments(attachments)
    names = [item.name for item in parsed]
    notes = [format_parsed_note(item) for item in parsed]
    image_parts = []
    for item in parsed:
        if not item.has_vision:
            continue
        if include_image_data:
            import base64

            b64 = base64.b64encode(item.vision_data).decode("ascii")
            image_parts.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{item.vision_mime};base64,{b64}"},
                }
            )
        else:
            image_parts.append({"type": "image_url", "image_url": {"url": ""}})
    return names, notes, image_parts


def build_openai_messages(messages, attachments):
    api_messages = []
    for item in messages[:-1]:
        api_messages.append({"role": item["role"], "content": item["content"]})

    last = messages[-1]
    user_text = last.get("content") or ""
    content, names, _parsed = build_multimodal_user_content(
        user_text,
        attachments,
        include_image_data=True,
    )
    api_messages.append({"role": "user", "content": content})
    return api_messages, names


def parsed_for_attachments(attachments):
    return parse_attachments(attachments)
