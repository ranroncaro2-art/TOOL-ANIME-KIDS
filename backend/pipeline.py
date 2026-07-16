import json
from typing import List, Dict, Any
from pydantic import BaseModel
from schemas import (
    StoryAnalysisResponse,
    AssetsResponse,
    ShotPlannerResponse,
    KeyframePromptResponse,
    MotionPromptResponse,
    CharacterAsset,
    EnvironmentAsset,
    PropAsset,
    Shot,
    ShotKeyframePrompt,
    ShotMotionPrompt
)
from gemini_client import generate_gemini_content

# --- Step 1: Story Analyzer ---
async def run_story_analyzer(storyboard: str, api_keys: List[str], model: str, rpm_limit: int = 5) -> StoryAnalysisResponse:
    system_instruction = (
        "You are an expert Story Analyzer. Your task is to read the storyboard text and analyze it into structured scenes. "
        "For each scene, determine the chronological order, estimate the duration in seconds (integer), identify all characters present, "
        "determine the location/background, list all props (objects) used, describe the action, and capture the dialogue. "
        "Always output in the requested JSON schema format."
    )
    
    prompt = f"Analyze this storyboard text and output the structured scene graph:\n\n{storyboard}"
    
    response_text = await generate_gemini_content(
        api_keys=api_keys,
        model=model,
        prompt=prompt,
        system_instruction=system_instruction,
        response_schema=StoryAnalysisResponse,
        rpm_limit=rpm_limit
    )
    return StoryAnalysisResponse.model_validate_json(response_text)

# --- Step 2: Assets Extractor ---
async def run_assets_extractor(
    storyboard: str,
    scenes_json: str,
    api_keys: List[str],
    model: str,
    rpm_limit: int = 5,
    chunk_size: int = 5
) -> AssetsResponse:
    # Combined step: calling Gemini once to extract characters, environments, and props.
    # This saves requests and tokens while maintaining visual style alignments.
    system_instruction = (
        "You are an expert Asset Extractor for animation production. "
        "Analyze the storyboard and scenes to identify all unique characters, environments, and props. "
        "For each character, write a detailed turnaround prompt (Pixar-quality 3D turnaround, front view, side view, 45-degree view, neutral pose, white background, no shadow, no text). "
        "For each environment, write a location reference prompt (Pixar-quality 3D, empty room, wide angle, consistent lighting, no characters, no text). "
        "For each prop, write a prop reference prompt (Pixar-quality 3D, centered, white background, reference image, no text). "
        "Return the unique assets in the requested JSON structure."
    )
    
    prompt = (
        f"Storyboard:\n{storyboard}\n\n"
        f"Analyzed Scenes:\n{scenes_json}\n\n"
        f"Extract all characters, environments, and props with reference prompts."
    )
    
    response_text = await generate_gemini_content(
        api_keys=api_keys,
        model=model,
        prompt=prompt,
        system_instruction=system_instruction,
        response_schema=AssetsResponse,
        rpm_limit=rpm_limit
    )
    return AssetsResponse.model_validate_json(response_text)


# --- Step 3: Shot Planner ---
async def run_shot_planner(
    scenes_json: str,
    characters_json: str,
    environments_json: str,
    props_json: str,
    api_keys: List[str],
    model: str,
    rpm_limit: int = 5,
    chunk_size: int = 5
) -> ShotPlannerResponse:
    # Optimized: Generate the entire shot sequence in one cohesive request.
    # This guarantees perfect story continuity, unified camera direction flow,
    # and sequential shot numbering (Shot001, Shot002...) while saving requests.
    system_instruction = (
        "You are a professional animation Shot Planner. "
        "Your task is to translate a sequence of scenes into individual camera shots. "
        "For each shot, specify: shot_id (formatted like Shot001, Shot002, etc.), scene_number, "
        "duration_seconds, actions (detailed visual character actions and events happening in this shot), "
        "characters visible, location/environment, props present, dialogue spoken in this shot, "
        "camera_movement, and shot_type (e.g., Close Up, Medium Shot, Wide Shot)."
    )
    
    prompt = (
        f"Analyzed Scenes:\n{scenes_json}\n\n"
        f"Characters Reference:\n{characters_json}\n\n"
        f"Environments Reference:\n{environments_json}\n\n"
        f"Props Reference:\n{props_json}\n\n"
        f"Generate the planned shot list for this storyboard."
    )
    
    response_text = await generate_gemini_content(
        api_keys=api_keys,
        model=model,
        prompt=prompt,
        system_instruction=system_instruction,
        response_schema=ShotPlannerResponse,
        rpm_limit=rpm_limit
    )
    return ShotPlannerResponse.model_validate_json(response_text)

# --- Step 4: Keyframe Prompt Generator ---
async def run_keyframe_prompt_generator(
    shots_json: str,
    characters_json: str,
    environments_json: str,
    props_json: str,
    api_keys: List[str],
    model: str,
    rpm_limit: int = 5,
    chunk_size: int = 5
) -> KeyframePromptResponse:
    # Keep chunking active for keyframes since it compiles detailed prompts for each shot,
    # which can get very wordy and benefit from chunk boundaries. Default chunk size: 5.
    shots = json.loads(shots_json)
    shot_chunks = [shots[i:i + chunk_size] for i in range(0, len(shots), chunk_size)]
    
    all_keyframes = []
    
    system_instruction = (
        "You are an expert Keyframe Image Prompt Generator. "
        "For each shot in the provided list, write a detailed text-to-image prompt to generate a single static keyframe reference image. "
        "Integrate details about character clothing/look (from character reference), environment (from environment reference), "
        "active props (from prop reference), camera framing (e.g., Close Up), and mood/lighting. "
        "Ensure the prompt is formatted in a Pixar-quality stylized 3D, cinematic composition, reference keyframe, "
        "no motion blur, no text, no captions."
    )
    
    for chunk in shot_chunks:
        chunk_shots_json = json.dumps(chunk, ensure_ascii=False)
        prompt = (
            f"Shots to generate keyframe prompts for:\n{chunk_shots_json}\n\n"
            f"Character Assets:\n{characters_json}\n\n"
            f"Environment Assets:\n{environments_json}\n\n"
            f"Prop Assets:\n{props_json}\n\n"
            f"Generate keyframe image prompts for this batch of shots."
        )
        
        response_text = await generate_gemini_content(
            api_keys=api_keys,
            model=model,
            prompt=prompt,
            system_instruction=system_instruction,
            response_schema=KeyframePromptResponse,
            rpm_limit=rpm_limit
        )
        chunk_data = KeyframePromptResponse.model_validate_json(response_text)
        all_keyframes.extend(chunk_data.keyframes)
        
    return KeyframePromptResponse(keyframes=all_keyframes)

# --- Step 5: Motion Prompt Generator ---
async def run_motion_prompt_generator(
    shots_json: str,
    keyframes_json: str,
    api_keys: List[str],
    model: str,
    rpm_limit: int = 5,
    chunk_size: int = 5
) -> MotionPromptResponse:
    # Keep chunking active for video motion prompts since they generate large volumes of text.
    # Default chunk size: 5.
    shots = json.loads(shots_json)
    keyframes = json.loads(keyframes_json)
    
    keyframes_by_shot = {k["shot_id"]: k for k in keyframes}
    shot_chunks = [shots[i:i + chunk_size] for i in range(0, len(shots), chunk_size)]
    
    all_motion_prompts = []
    
    system_instruction = (
        "You are an expert Motion Prompt Generator for Veo 3 (video generation).\n"
        "For each shot, you must output a structured motion prompt describing the movements, actions, dialogue animation, and idle behavior. "
        "Your generated prompt for each shot MUST strictly follow this structured format:\n\n"
        "Scene:\n[Brief setting name]\n\n"
        "Characters:\n[List of active characters]\n\n"
        "Action:\n[Step-by-step description of character movements, physical gestures, and active pointing/leaning during dialogue to make animation look natural]\n\n"
        "Dialogue:\n[Character name]: \"[Speech text]\" (Crucial: Copy the dialogue/speech text exactly word-for-word from the planned shot object. Do not paraphrase, translate, edit, or summarize the dialogue. If there is no dialogue in the shot, write 'None')\n\n"
        "Character Motion:\n- [Natural breathing, blinking, eye contact, weight shifting details]\n- [Lip-sync and body posture adjustments matching the dialog]\n"
        "  - Critical Voice & Lip Sync Instructions:\n"
        "    If the shot has dialogues, include voice references in the motion description (written in Vietnamese):\n"
        "    * If 1 character speaks: mention '[Character Name] (sử dụng giọng thứ nhất)' and append 'Cử động môi khớp hoàn toàn với lời thoại trong tệp âm thanh đính kèm.'\n"
        "    * If 2 characters speak: mention '[Character A] (sử dụng giọng thứ nhất)' and '[Character B] (sử dụng giọng thứ hai)' and append 'Cả hai tương tác tự nhiên, nhìn vào mắt nhau và cử động môi khớp hoàn toàn với lời thoại trong tệp âm thanh đính kèm.'\n\n"
        "Camera:\n- [Opening framing, e.g. Medium shot]\n- [Single camera movement description, e.g. Slow pan right or Static]\n\n"
        "Lighting:\n- [Current lighting, e.g. Warm afternoon sunlight]\n\n"
        "Environment Motion:\n- [Slight background movement, e.g. Leaves sway gently]\n\n"
        "Idle Animation:\n- [Crucial: Idle actions for characters to do after dialogue finishes until the end of the clip, e.g., both children continue smiling, looking at the box, exchange happy glances, and remain naturally animated]\n\n"
        "Style:\n- [Pixar-quality stylized 3D animation, feature-film quality, smooth motion, no subtitles, no captions, no on-screen text]\n\n"
        "Do not write narrative prose paragraphs. Keep it strictly structured as block sections as shown above. This makes the prompt clean, structured, and easy to translate across generator models."
    )
    
    for chunk in shot_chunks:
        chunk_keyframes = [keyframes_by_shot[s["shot_id"]] for s in chunk if s["shot_id"] in keyframes_by_shot]
        
        chunk_shots_json = json.dumps(chunk, ensure_ascii=False)
        chunk_keyframes_json = json.dumps(chunk_keyframes, ensure_ascii=False)
        
        prompt = (
            f"Shots:\n{chunk_shots_json}\n\n"
            f"Keyframe Prompts:\n{chunk_keyframes_json}\n\n"
            f"Generate Veo 3 motion prompts for this batch of shots."
        )
        
        response_text = await generate_gemini_content(
            api_keys=api_keys,
            model=model,
            prompt=prompt,
            system_instruction=system_instruction,
            response_schema=MotionPromptResponse,
            rpm_limit=rpm_limit
        )
        chunk_data = MotionPromptResponse.model_validate_json(response_text)
        all_motion_prompts.extend(chunk_data.motion_prompts)
        
    return MotionPromptResponse(motion_prompts=all_motion_prompts)
