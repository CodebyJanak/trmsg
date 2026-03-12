"""trmsg - Gemini AI Integration"""
import httpx
import json
from typing import Optional
from server.config import settings

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent"

SYSTEM_PROMPT = """You are TRM-AI, the helpful AI assistant built into trmsg terminal chat.
You are concise, helpful, and friendly. You speak in a slightly hacker/tech style.
Keep responses under 300 words unless asked for more detail.
Format code with proper syntax. Use markdown formatting."""

async def ask_gemini(prompt: str, context: Optional[str] = None) -> str:
    if not settings.GEMINI_API_KEY:
        return "⚠ AI not configured. Admin needs to set GEMINI_API_KEY in server .env"

    full_prompt = f"{SYSTEM_PROMPT}\n\n"
    if context:
        full_prompt += f"Chat context:\n{context}\n\n"
    full_prompt += f"User: {prompt}"

    payload = {
        "contents": [{"parts": [{"text": full_prompt}]}],
        "generationConfig": {"maxOutputTokens": 500, "temperature": 0.7},
    }

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.post(
                f"{GEMINI_URL}?key={settings.GEMINI_API_KEY}",
                json=payload,
            )
            data = r.json()
            if "candidates" in data:
                return data["candidates"][0]["content"]["parts"][0]["text"]
            elif "error" in data:
                return f"⚠ AI error: {data['error'].get('message', 'Unknown error')}"
            return "⚠ AI returned no response"
    except httpx.TimeoutException:
        return "⚠ AI timed out. Try again."
    except Exception as e:
        return f"⚠ AI error: {str(e)}"


async def summarize_messages(messages: list) -> str:
    if not messages:
        return "No messages to summarize."
    chat_text = "\n".join(f"{m['sender']}: {m['content']}" for m in messages[:50])
    prompt = f"Summarize this chat conversation in 3-5 bullet points:\n\n{chat_text}"
    return await ask_gemini(prompt)


async def translate_text(text: str, target_lang: str) -> str:
    prompt = f"Translate this to {target_lang}. Reply with ONLY the translation, nothing else:\n\n{text}"
    return await ask_gemini(prompt)


async def explain_code(code: str, language: str = "") -> str:
    prompt = f"Explain this {language} code clearly and concisely:\n\n```{language}\n{code}\n```"
    return await ask_gemini(prompt)


async def roast_user(username: str, stats: dict) -> str:
    prompt = f"Give a funny, friendly roast of a terminal chat user named '{username}' based on these stats: {json.dumps(stats)}. Keep it light and fun!"
    return await ask_gemini(prompt)
