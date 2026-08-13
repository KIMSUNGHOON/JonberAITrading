"""
Translation Endpoint

LLM-backed KO↔EN translation, used by the FE proposal chat
(ProposalChatMessage → client.translateText).

Extracted verbatim from the former US-stock analysis router (R2) so the
/api/analysis/translate URL contract survives the US stack removal — this
router is mounted under the same "analysis" sub-path.
"""

import structlog
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from agents.llm_provider import get_llm_provider
from langchain_core.messages import SystemMessage, HumanMessage

logger = structlog.get_logger()
router = APIRouter()


class TranslationRequest(BaseModel):
    """Translation request model."""
    text: str
    target_language: str = "en"  # "en" for English, "ko" for Korean


class TranslationResponse(BaseModel):
    """Translation response model."""
    original: str
    translated: str
    target_language: str


@router.post("/translate", response_model=TranslationResponse)
async def translate_text(request: TranslationRequest):
    """
    Translate text between Korean and English using LLM.

    Args:
        request: Translation request with text and target language

    Returns:
        Original and translated text
    """
    try:
        llm = get_llm_provider()

        if request.target_language == "en":
            prompt = "Translate the following Korean text to English. Only output the translation, nothing else."
        else:
            prompt = "Translate the following English text to Korean. Only output the translation, nothing else."

        messages = [
            SystemMessage(content=prompt),
            HumanMessage(content=request.text),
        ]

        translated = await llm.generate(messages)

        return TranslationResponse(
            original=request.text,
            translated=translated.strip(),
            target_language=request.target_language,
        )

    except Exception as e:
        logger.error("translation_failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Translation failed: {str(e)}",
        )
