import httpx
import json
import logging
import asyncio
import time
from typing import List, Optional, Type
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("GeminiClient")

# Rate limit tracking variables
last_request_time = 0.0
request_lock = asyncio.Lock()

async def enforce_rate_limit(rpm_limit: int):
    """
    Blocks execution if the time since the last request is less than (60 / rpm_limit) seconds.
    This guarantees that requests are spaced out to conform to the Requests Per Minute (RPM) quota.
    """
    global last_request_time
    if rpm_limit <= 0:
        return
        
    delay_between_requests = 60.0 / rpm_limit
    
    async with request_lock:
        now = time.time()
        elapsed = now - last_request_time
        if elapsed < delay_between_requests:
            sleep_time = delay_between_requests - elapsed
            logger.info(f"Rate limiter: Sleeping for {sleep_time:.2f}s to respect the limit of {rpm_limit} RPM...")
            await asyncio.sleep(sleep_time)
        # Record the time immediately before returning to proceed with the request
        last_request_time = time.time()


def dereference_schema(schema: dict) -> dict:
    """
    Recursively replaces all $ref references with their actual definitions from $defs,
    and removes $defs from the schema. This is necessary because Gemini's schema parser
    does not support local references ($ref) under $defs.
    """
    defs = schema.get("$defs", {})
    
    def resolve(node):
        if isinstance(node, dict):
            if "$ref" in node:
                ref_path = node["$ref"]
                # e.g., "#/$defs/DialogueItem" -> "DialogueItem"
                ref_key = ref_path.split("/")[-1]
                if ref_key in defs:
                    # Recursively resolve the referenced definition
                    return resolve(defs[ref_key])
            return {k: resolve(v) for k, v in node.items() if k != "$defs"}
        elif isinstance(node, list):
            return [resolve(item) for item in node]
        return node
        
    resolved = resolve(schema)
    # Ensure any remaining $defs is purged
    if "$defs" in resolved:
        del resolved["$defs"]
    return resolved

async def generate_gemini_content(
    api_keys: List[str],
    model: str,
    prompt: str,
    system_instruction: Optional[str] = None,
    response_schema: Optional[Type[BaseModel]] = None,
    temperature: float = 0.2,
    rpm_limit: int = 5
) -> str:
    """
    Calls the Gemini API to generate content with fallback/rotation logic.
    Rotates to the next API key in the list if the current one fails (e.g. rate limit, quota, invalid key).
    """
    if not api_keys:
        raise ValueError("No API keys provided. Please supply at least one Gemini API key.")

    # Strip whitespace from keys
    api_keys = [k.strip() for k in api_keys if k.strip()]
    if not api_keys:
        raise ValueError("Provided API keys are empty or invalid.")

    # Clean up model name
    model = model.strip()
    # Normalize model names to Gemini API format if needed
    # e.g., "gemini-2.5-flash" -> "gemini-2.5-flash"
    # If it's a version name like "2.5 Flash", map it or use as is
    model_mapping = {
        "2.5 flash": "gemini-2.5-flash",
        "2.5-flash": "gemini-2.5-flash",
        "1.5 flash": "gemini-1.5-flash",
        "1.5-flash": "gemini-1.5-flash",
        "3.5 flash": "gemini-2.5-flash", # Note: Gemini 3.5 Flash doesn't exist yet officially, but if user inputs "3.5 Flash" we map it to 2.5 Flash or use as-is
    }
    normalized_model = model_mapping.get(model.lower(), model)

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{normalized_model}:generateContent"
    
    # Prepare request body
    contents = [
        {
            "parts": [
                {"text": prompt}
            ]
        }
    ]
    
    payload = {
        "contents": contents
    }

    if system_instruction:
        payload["systemInstruction"] = {
            "parts": [
                {"text": system_instruction}
            ]
        }

    # Configure generation config
    generation_config = {
        "temperature": temperature
    }
    
    if response_schema:
        raw_schema = response_schema.model_json_schema()
        clean_schema = dereference_schema(raw_schema)
        generation_config["responseMimeType"] = "application/json"
        generation_config["responseSchema"] = clean_schema
        
    payload["generationConfig"] = generation_config

    errors = []
    
    # Rotate through API keys
    for index, api_key in enumerate(api_keys):
        # Mask API key for logs (e.g. AIzaSy...xxxx)
        masked_key = f"{api_key[:8]}...{api_key[-4:]}" if len(api_key) > 12 else "INVALID_KEY_FORMAT"
        logger.info(f"Attempting API request using key index {index} ({masked_key}) with model '{normalized_model}'...")
        
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": api_key
        }
        
        try:
            # Enforce rate limits (Requests Per Minute)
            await enforce_rate_limit(rpm_limit)
            
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(url, headers=headers, json=payload)
                
                if response.status_code == 200:
                    data = response.json()
                    # Check if response text is present
                    candidates = data.get("candidates", [])
                    if candidates and len(candidates) > 0:
                        parts = candidates[0].get("content", {}).get("parts", [])
                        if parts and len(parts) > 0:
                            text = parts[0].get("text", "")
                            logger.info(f"API request succeeded with key index {index}.")
                            return text
                    raise ValueError(f"Gemini API returned 200 OK but structure was unexpected: {json.dumps(data)}")
                else:
                    error_msg = f"HTTP {response.status_code}: {response.text}"
                    logger.warning(f"Key index {index} failed: {error_msg}")
                    errors.append(f"Key {index} ({masked_key}): {error_msg}")
                    
        except Exception as e:
            error_msg = str(e)
            logger.warning(f"Key index {index} encountered exception: {error_msg}")
            errors.append(f"Key {index} ({masked_key}) error: {error_msg}")
            
    # If we exited the loop, all keys failed
    all_errors_summary = " | ".join(errors)
    raise RuntimeError(f"All provided API keys failed. Details: {all_errors_summary}")
