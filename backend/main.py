"""FastAPI entrypoint for the SLM Text-to-SQL analytics service."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
import weave

from backend.config import WANDB_API_KEY, WANDB_PROJECT
from backend.routes.chat_routes import router as chat_router
from backend.routes.health_routes import router as health_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # W&B Weave traces every @weave.op call (inputs, outputs, latency, errors).
    if WANDB_API_KEY:
        weave.init(WANDB_PROJECT)
    yield


app = FastAPI(
    title="SLM Text-to-SQL Analytics API",
    description="Chat with your database using a QLoRA fine-tuned GGUF model.",
    version="3.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", include_in_schema=False)
def root():
    """Redirect root path to interactive Swagger docs."""
    return RedirectResponse(url="/docs")


app.include_router(health_router)
app.include_router(chat_router)
