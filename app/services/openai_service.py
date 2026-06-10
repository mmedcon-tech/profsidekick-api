import json
import asyncio
import base64
import httpx
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from openai import OpenAI, AsyncOpenAI
from app.config import settings
from app.services.context_builder import build_realtime_instructions, resolve_vision_prompt
from PIL import Image
import traceback
import io

class OpenAIService:
    """Service for OpenAI API integration"""

    def __init__(self):
        self.client = OpenAI(api_key=settings.openai_api_key)
        self.async_client = AsyncOpenAI(api_key=settings.openai_api_key)
        
    # Valid OpenAI Realtime API model identifiers for realtime sessions.
    _VALID_REALTIME_MODELS = {
        "gpt-realtime",
        "gpt-realtime-1.5",
        "gpt-realtime-2",
        "gpt-realtime-2025-08-28",
        "gpt-realtime-mini",
        "gpt-realtime-mini-2025-10-06",
        "gpt-realtime-mini-2025-12-15",
        "gpt-audio-1.5",
        "gpt-audio-mini",
        "gpt-audio-mini-2025-10-06",
        "gpt-audio-mini-2025-12-15",
        "gpt-4o-realtime-preview",
        "gpt-4o-realtime-preview-2024-10-01",
        "gpt-4o-realtime-preview-2024-12-17",
        "gpt-4o-realtime-preview-2025-06-03",
        "gpt-4o-mini-realtime-preview",
        "gpt-4o-mini-realtime-preview-2024-12-17",
    }
    _DEFAULT_REALTIME_MODEL = "gpt-realtime-2"


    def _normalize_realtime_model(self, model: str) -> str:
        """Map legacy/invalid model names to a valid Realtime API model identifier."""
        if model in self._VALID_REALTIME_MODELS:
            return model
        if "mini" in model.lower():
            return "gpt-realtime-mini"
        return self._DEFAULT_REALTIME_MODEL

    def _as_dict(self, value: Any) -> Dict[str, Any]:
        """Convert Pydantic models or plain objects to dictionaries."""
        if value is None:
            return {}
        if isinstance(value, dict):
            return value
        if hasattr(value, "model_dump"):
            return value.model_dump()
        return vars(value)

    def _strip_none(self, value: Dict[str, Any]) -> Dict[str, Any]:
        return {key: item for key, item in value.items() if item is not None}

    def _audio_format(self, value: Optional[str]) -> Dict[str, Any]:
        if value == "g711_ulaw":
            return {"type": "audio/pcmu"}
        if value == "g711_alaw":
            return {"type": "audio/pcma"}
        return {"type": "audio/pcm", "rate": 24000}

    def _normalize_tool(self, tool: Any) -> Dict[str, Any]:
        tool_dict = self._as_dict(tool)
        function = self._as_dict(tool_dict.get("function"))
        if tool_dict.get("type") == "function" and function:
            return self._strip_none({
                "type": "function",
                "name": function.get("name"),
                "description": function.get("description"),
                "parameters": function.get("parameters"),
            })
        return self._strip_none(tool_dict)

    def _normalize_turn_detection(self, turn_detection: Any) -> Optional[Dict[str, Any]]:
        td = self._as_dict(turn_detection)
        if not td:
            return None
        if td.get("type") != "server_vad":
            print(
                f"Realtime turn_detection '{td.get('type')}' is not supported by "
                "the GA client-secret API; using server_vad."
            )
            return {"type": "server_vad"}
        return self._strip_none({
            "type": "server_vad",
            "threshold": td.get("threshold"),
            "prefix_padding_ms": td.get("prefix_padding_ms"),
            "silence_duration_ms": td.get("silence_duration_ms"),
        })

    async def generate_ephemeral_token(
        self,
        assistant_parameters: Any,
        slides: List[Dict[str, Any]],
        solution_slides: List[Dict[str, Any]] = None,
        # Avatar / template context (resolved at call site)
        conversation_prompt: Optional[str] = None,
        teaching_prompt: Optional[str] = None,
        examination_prompt: Optional[str] = None,
        session_mode: Optional[str] = None,
        role_label: Optional[str] = None,
        role_context: Optional[str] = None,
        session_summary: Optional[str] = None,
        memories: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Generate an ephemeral client secret for OpenAI Realtime API sessions.
        """
        try:
            ap = self._as_dict(assistant_parameters)

            raw_model = ap.get('model') or self._DEFAULT_REALTIME_MODEL
            model = self._normalize_realtime_model(raw_model)
            if model != raw_model:
                print(f"⚠️  Remapped realtime model '{raw_model}' → '{model}'")

            instructions = build_realtime_instructions(
                assistant_parameters=assistant_parameters,
                slides=slides,
                solution_slides=solution_slides,
                conversation_prompt=conversation_prompt,
                teaching_prompt=teaching_prompt,
                examination_prompt=examination_prompt,
                session_mode=session_mode,
                role_label=role_label,
                role_context=role_context,
                session_summary=session_summary,
                memories=memories,
            )

            transcription = ap.get('input_audio_transcription')

            # Use httpx directly — the bundled openai SDK version is too old to
            # know about POST /v1/realtime/client_secrets.
            input_audio: Dict[str, Any] = {
                "format": self._audio_format(ap.get("input_audio_format", "pcm16")),
            }
            noise_reduction = (
                ap.get("input_audio_noise_reduction")
                or ap.get("input_audio_noice_reduction")
            )
            if noise_reduction:
                input_audio["noise_reduction"] = self._as_dict(noise_reduction)
            if transcription:
                input_audio["transcription"] = self._strip_none(
                    self._as_dict(transcription)
                )
            if "turn_detection" in ap:
                input_audio["turn_detection"] = self._normalize_turn_detection(
                    ap.get("turn_detection")
                )

            output_audio: Dict[str, Any] = {
                "format": self._audio_format(ap.get("output_audio_format", "pcm16")),
                "voice": ap.get("voice", "alloy"),
            }
            if ap.get("speed") is not None:
                output_audio["speed"] = ap.get("speed")

            session_body: Dict[str, Any] = self._strip_none({
                "type": "realtime",
                "model": model,
                "instructions": instructions,
                "audio": {
                    "input": input_audio,
                    "output": output_audio,
                },
                "tool_choice": ap.get("tool_choice", "auto"),
                "tools": [
                    self._normalize_tool(tool)
                    for tool in (ap.get("tools") or [])
                ],
                "output_modalities": (
                    ap.get("output_modalities")
                    or (["text"] if ap.get("modalities") == ["text"] else ["audio"])
                ),
                "max_output_tokens": (
                    ap.get("max_output_tokens")
                    or ap.get("max_response_output_tokens")
                ),
                "tracing": ap.get("tracing"),
                "truncation": ap.get("truncation"),
                "prompt": ap.get("prompt"),
                "include": ap.get("include"),
                "parallel_tool_calls": ap.get("parallel_tool_calls"),
            })

            body = {
                "expires_after": {
                    "anchor": "created_at",
                    "seconds": ap.get("client_secret_ttl_seconds", 600),
                },
                "session": session_body,
            }

            async with httpx.AsyncClient(timeout=30) as http:
                resp = await http.post(
                    "https://api.openai.com/v1/realtime/client_secrets",
                    headers={
                        "Authorization": f"Bearer {settings.openai_api_key}",
                        "Content-Type": "application/json",
                    },
                    json=body,
                )
            try:
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise Exception(
                    f"OpenAI Realtime client secret failed "
                    f"({resp.status_code}): {resp.text}"
                ) from exc

            token_data = resp.json()
            if "client_secret" not in token_data and "value" in token_data:
                token_data["client_secret"] = {
                    "value": token_data["value"],
                    "expires_at": token_data.get("expires_at"),
                }
            return token_data

        except Exception as e:
            print("generate_ephemeral_token FAILED")
            print(traceback.format_exc())
            raise

    async def process_slides_with_vision(
        self,
        slide_images: List,
        images_paths: List,
        session_id: str,
        vision_instructions: str,
        vision_model: str,
        template_document_analysis_prompt: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        try:
            # Prepare slides for Vision API
            slides_details = []
            # Priority: explicit vision_instructions from session > template prompt > hardcoded default
            if not vision_instructions:
                vision_instructions = resolve_vision_prompt(template_document_analysis_prompt)
            if not vision_model:
                vision_model = "gpt-4o"

            for slide_image, image_path in zip(slide_images, images_paths):
                slide_details = await self._process_slide_with_vision(slide_image, vision_instructions, vision_model)
                slides_details.append({
                    "id": image_path.get('slideNumber'),
                    "slideNumber": image_path.get('slideNumber'),
                    "title": slide_details.get('title'),
                    "content": slide_details.get('content'),
                    "imagePath": image_path.get('imagePath'),
                    "thumbnailPath": image_path.get('thumbnailPath'),
                    "visionInstructions": vision_instructions,
                    "visionModel": vision_model
                })
            
            return slides_details
        
        except Exception as e:
            raise Exception(f"Failed to process slides with Vision API: {str(e)}")
    
    async def process_slide_with_vision(self, slide_image: Image, vision_instructions: str, vision_model: str) -> Dict[str, Any]:
        try:
            print(f"Processing slide with Vision API: {slide_image}")
            slide_details = await self._process_slide_with_vision(slide_image, vision_instructions, vision_model)
            return slide_details
        except Exception as e:
            raise Exception(f"Failed to process slide with Vision API: {str(e)}")
    
    async def _process_slide_with_vision(self, slide_image: Image, vision_instructions: str, vision_model: str) -> Dict[str, Any]:
        try:
            # Convert image to base64 PNG format
            buffer = io.BytesIO()
            slide_image.save(buffer, format='PNG')
            buffer.seek(0)
            image_base64 = base64.b64encode(buffer.getvalue()).decode()

            # Call OpenAI API
            response_content = self.client.chat.completions.create(
                model=vision_model,
                messages=[
                    {
                        "role": "system",
                        "content": vision_instructions
                    },
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": "Analyze this slide and extract all content as instructed."
                            },
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/png;base64,{image_base64}",
                                    "detail": "high"
                                }
                            }
                        ]
                    }
                ],
                temperature=0.4
            )

            response_title = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": "Generate a concise academic title for this examination slide (maximum 10 words). Write only the title, no additional text."
                    },
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": response_content.choices[0].message.content
                            }
                        ]
                    }
                ]
            )

            return {
                "title": response_title.choices[0].message.content,
                "content": response_content.choices[0].message.content
            }
        
        except Exception as e:
            raise Exception(f"Failed to process slide with Vision API: {str(e)}")
