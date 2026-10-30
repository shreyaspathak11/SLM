"""Chat endpoint where users send analytics questions."""

from fastapi import APIRouter, HTTPException

from backend.controllers.chat_controller import answer_question
from backend.schemas.chat import ChatRequest, ChatResponse

router = APIRouter(tags=["Chat"])


@router.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    try:
        return answer_question(request.question)
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail="Sorry, I faced an issue. Please fix the query and retry.",
        ) from exc
