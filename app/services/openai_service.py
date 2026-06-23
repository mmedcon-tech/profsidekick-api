import json
import asyncio
import base64
import httpx
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
import openai
from openai import OpenAI, AsyncOpenAI
from app.config import settings
from app.services.context_builder import (
    build_realtime_instructions,
    resolve_vision_prompt,
    GROUNDING_POLICY_DEFAULT,
)
from PIL import Image
import traceback
import io

class OpenAIService:
    """Service for OpenAI API integration"""

    def __init__(self):
        self.client = OpenAI(api_key=settings.openai_api_key)
        self.async_client = AsyncOpenAI(api_key=settings.openai_api_key)
        
    # Valid OpenAI Realtime API model identifiers (as of 2025)
    _VALID_REALTIME_MODELS = {
        "gpt-realtime-2",
        "gpt-realtime-1.5",
        "gpt-realtime",
        "gpt-realtime-translate",
        "gpt-realtime-whisper",
    }
    _DEFAULT_REALTIME_MODEL = "gpt-realtime-2"

    def _normalize_realtime_model(self, model: str) -> str:
        """Map legacy/deprecated model names to a valid Realtime API model identifier."""
        if model in self._VALID_REALTIME_MODELS:
            return model
        # Map any legacy gpt-4o-realtime-* or unknown names to the current default
        return self._DEFAULT_REALTIME_MODEL

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
        # Publisher teaching persona (from PublisherAvatarProfile.refined_prompt)
        refined_prompt: Optional[str] = None,
        # RAG-retrieved knowledge context
        rag_context: Optional[str] = None,
        # Grounding policy override
        grounding_policy: str = GROUNDING_POLICY_DEFAULT,
    ) -> Dict[str, Any]:
        """
        Generate ephemeral token for OpenAI Realtime API using the SDK.
        Using the SDK (rather than raw httpx) guarantees the request shape matches
        the current GA API format regardless of future OpenAI API changes.
        """
        try:
            ap = assistant_parameters if isinstance(assistant_parameters, dict) else vars(assistant_parameters)

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
                refined_prompt=refined_prompt,
                rag_context=rag_context,
                grounding_policy=grounding_policy,
            )

            # Build turn_detection in the shape the SDK expects
            td = ap.get('turn_detection')
            if td is None:
                turn_detection = openai.NOT_GIVEN
            elif td.get('type') == "server_vad":
                turn_detection = {
                    "type": "server_vad",
                    "threshold": td.get('threshold'),
                    "prefix_padding_ms": td.get('prefix_padding_ms'),
                    "silence_duration_ms": td.get('silence_duration_ms'),
                }
            elif td.get('type') == "semantic_vad":
                turn_detection = {
                    "type": "semantic_vad",
                    "eagerness": td.get('eagerness'),
                }
            else:
                turn_detection = {"type": td['type']}

            noise_reduction = ap.get('input_audio_noise_reduction')
            transcription = ap.get('input_audio_transcription')

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "https://api.openai.com/v1/realtime/sessions",
                    headers={
                        "Authorization": f"Bearer {settings.openai_api_key}",
                        "Content-Type": "application/json",
                        "OpenAI-Beta": "realtime=v1",
                    },
                    json={
                        "model": model,
                        "voice": ap.get("voice", "alloy"),
                        "instructions": instructions,
                        "input_audio_format": ap.get("input_audio_format", "pcm16"),
                        "output_audio_format": ap.get("output_audio_format", "pcm16"),
                        "temperature": ap.get("temperature", 0.8),
                        "tool_choice": ap.get("tool_choice", "auto"),
                        "tools": ap.get("tools") or [],
                        "turn_detection": turn_detection,
                        "input_audio_noise_reduction": noise_reduction if noise_reduction else None,
                        "input_audio_transcription": transcription if transcription else None,
                    },
                )

            if response.status_code != 200:
                print(response.text)
                raise Exception(response.text)

            return response.json()

        except Exception as e:
            print("❌ generate_ephemeral_token FAILED")
            print(traceback.format_exc())
            raise

    async def refine_persona_prompt(
        self,
        draft: str,
        additional_context: Optional[str] = None,
    ) -> str:
        """Call gpt-4o-mini to condense a draft teaching-persona into a compact directive."""
        extra = (
            f"\n\nAdditional context from the publisher:\n{additional_context.strip()}"
            if additional_context and additional_context.strip()
            else ""
        )
        completion = await self.async_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a prompt engineer for an educational AI platform. "
                        "Your task is to rewrite the draft teaching persona below into a concise, "
                        "natural, first-person instructional style directive (max 200 words). "
                        "Preserve all teaching preferences. Remove template headers and bullet formatting. "
                        "Output only the refined persona text — no preamble, no labels."
                    ),
                },
                {"role": "user", "content": f"Draft:\n{draft}{extra}"},
            ],
            max_tokens=400,
            temperature=0.4,
        )
        if not completion.choices:
            raise ValueError("OpenAI returned no choices for persona refinement")
        return completion.choices[0].message.content.strip()

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