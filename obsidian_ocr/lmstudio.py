"""Thin wrapper over the official `lmstudio` python SDK for vision OCR."""

from __future__ import annotations

OCR_PROMPT = (
    "Transcribe all text in this image as clean GitHub-flavored markdown. "
    "Preserve headings, lists, and tables where present. "
    "If the image contains no text, reply with an empty response. "
    "Output only the transcribed content, no commentary."
)


class OcrClient:
    """Loads a vision model on an LM Studio server and OCRs image bytes."""

    def __init__(self, host: str, model_name: str, max_tokens: int = 4096):
        # Imported lazily so the package (and tests) load without the SDK / a server.
        import lmstudio as lms

        self._lms = lms
        lms.configure_default_client(host)
        self._model = lms.llm(model_name)
        # Bound every page so a model that runs away (loops/over-generates on a dense or
        # noisy scan) can't block the whole run indefinitely; temperature 0 keeps OCR
        # deterministic and far less prone to such looping.
        self._config = {"maxTokens": max_tokens, "temperature": 0}

    def ocr_image(self, image_bytes: bytes) -> str:
        """Return the OCR'd text for a single image given as raw bytes."""
        lms = self._lms
        image = lms.prepare_image(image_bytes)
        chat = lms.Chat()
        chat.add_user_message(OCR_PROMPT, images=[image])
        result = self._model.respond(chat, config=self._config)
        # PredictionResult exposes the text via .content; str() is a safe fallback.
        text = getattr(result, "content", None)
        if text is None:
            text = str(result)
        return text.strip()
