from fastapi import FastAPI

from .agent import OpenAIChatAgent
from .schemas import ChatRequest, ChatResponse
from .tools import ConsumerTools


def create_app() -> FastAPI:
    app = FastAPI(title="Consumer Backend")
    tools = ConsumerTools()
    agent = OpenAIChatAgent(tools=tools)

    @app.post("/chat", response_model=ChatResponse)
    def chat(payload: ChatRequest) -> ChatResponse:
        reply, tool_used = agent.respond(payload.message)
        return ChatResponse(reply=reply, tool_used=tool_used)

    return app


app = create_app()
