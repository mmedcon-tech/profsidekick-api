import json
import asyncio
import base64
import httpx
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
import openai
from openai import OpenAI
from app.config import settings
from PIL import Image
import io

class OpenAIService:
    """Service for OpenAI API integration"""
    
    def __init__(self):
        self.client = OpenAI(api_key=settings.openai_api_key)
        self.url = "https://api.openai.com/v1/realtime/sessions"
        self.headers = {
            "Authorization": f"Bearer {settings.openai_api_key}",
            "Content-Type": "application/json"
        }
        
    async def generate_ephemeral_token(self, assistant_parameters: Any, slides: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Generate ephemeral token for OpenAI Realtime API
        
        Returns:
            Dictionary containing client_secret with token and expiration
        """
        try:
            # Make direct HTTP POST request to OpenAI Realtime API
            if assistant_parameters['turn_detection']['type'] == "server_vad":
                turn_detection = {
                    "type": assistant_parameters['turn_detection']['type'],
                    "prefix_padding_ms": assistant_parameters['turn_detection']['prefix_padding_ms'],
                    "silence_duration_ms": assistant_parameters['turn_detection']['silence_duration_ms'],
                    "threshold": assistant_parameters['turn_detection']['threshold'],
                }
            elif assistant_parameters['turn_detection']['type'] == "semantic_vad":
                turn_detection = {
                    "type": assistant_parameters['turn_detection']['type'],
                    "eagerness": assistant_parameters['turn_detection']['eagerness'],
                }
            else:
                turn_detection = {
                    "type": assistant_parameters['turn_detection']['type'],
                }

            if assistant_parameters['instructions'] is not None and assistant_parameters['instructions'][0] != "{":
                instructions = assistant_parameters['instructions']
            else:
                instructions_json = json.loads(assistant_parameters['instructions'])
                instructions = instructions_json['editable'] + "\n" + instructions_json['core']
            for slide in slides:
                instructions += f"\n\nSlide {slide.slideNumber}: {slide.title}\n{slide.content}"
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.url,
                    headers=self.headers,
                    json={
                        "model": assistant_parameters['model'],
                        "voice": assistant_parameters['voice'],
                        "instructions": instructions,
                        "input_audio_format": assistant_parameters['input_audio_format'],
                        "output_audio_format": assistant_parameters['output_audio_format'],
                        "temperature": assistant_parameters['temperature'],
                        "tool_choice": assistant_parameters['tool_choice'],
                        "input_audio_noise_reduction": assistant_parameters['input_audio_noise_reduction'],
                        "input_audio_transcription": assistant_parameters['input_audio_transcription'],                        
                        "tools": assistant_parameters['tools'],
                        "turn_detection": turn_detection,
                    }
                )
                
                if response.status_code == 200:
                    return response.json()
                else:
                    raise Exception(f"API request failed with status {response.status_code}: {response.text}")
            
        except Exception as e:
            raise Exception(f"Failed to generate ephemeral token: {str(e)}")

    async def process_slides_with_vision(self, slide_images: List, images_paths: List, session_id: str, vision_instructions: str, vision_model: str) -> List[Dict[str, Any]]:
        try:
            # Prepare slides for Vision API
            slides_details = []
            if not vision_instructions:
                vision_instructions = "You are a helpful assistant that can analyze the slide image and provide a detailed description of the content."
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
                                "text": vision_instructions
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
                        "content": "You are a helpful assistant that can analyze the slide content and provide a title for the slide. The title should be a single sentence that captures the main idea of the slide. It should be no more than 10 words. Just write the title directly without title tag."
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