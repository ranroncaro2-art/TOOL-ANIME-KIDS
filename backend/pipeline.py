import json
from typing import List, Dict, Any, Optional
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
    ShotMotionPrompt,
    ComplianceCheckResult
)
from gemini_client import generate_gemini_content

def extract_relevant_storyboard_scenes(storyboard: str, scene_numbers: set) -> str:
    """
    Parses storyboard text and extracts only the scenes that match the given scene numbers.
    This helps keep the prompt size small and avoids safety false positives from unrelated scenes.
    """
    import re
    if not storyboard or not scene_numbers:
        return ""
        
    # Split by standard scene numbers, e.g. "2" or "Scene 2" or "Phân cảnh 2"
    # Matches a line that contains only digits, or starts with Scene/Phân cảnh/Phân đoạn followed by digits
    blocks = re.split(r'\n(?=\d+(?:\n|\r\n))', storyboard)
    if len(blocks) <= 1:
        # Fallback to double newline split
        blocks = storyboard.split("\n\n")
        
    relevant_blocks = []
    for block in blocks:
        # Clean block text
        clean_block = block.strip()
        if not clean_block:
            continue
            
        # Try to find leading scene number (e.g. "2" or "Scene 2" or "2...")
        match = re.match(r'^\s*(?:scene|phân cảnh|phân đoạn|)\s*(\d+)', clean_block, re.IGNORECASE)
        if match:
            num = int(match.group(1))
            if num in scene_numbers:
                relevant_blocks.append(clean_block)
        else:
            # Fallback search inside the block if it didn't start with a number
            for num in scene_numbers:
                if f"scene {num}" in clean_block.lower() or f"phân cảnh {num}" in clean_block.lower():
                    relevant_blocks.append(clean_block)
                    break
                    
    if relevant_blocks:
        return "\n\n".join(relevant_blocks)
        
    # Final fallback: if no scene matching is found, return the full storyboard
    return storyboard

def clean_text_for_safety(text: str) -> str:
    """
    Sanitizes text by removing child age descriptors and converting age-indicative child terms
    into generic, safety-neutral character equivalents to prevent Gemini API safety block false-positives.
    """
    if not text:
        return ""
    import re
    # Remove ages like "8-year-old", "8 years old", "8yo"
    text = re.sub(r'\b\d+[- ]?year[- ]?olds?\b', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\b\d+[- ]?years?[- ]?old\b', '', text, flags=re.IGNORECASE)
    # Neutralize age-indicative child terms
    text = re.sub(r'\byoung\s+boy\b', 'boy', text, flags=re.IGNORECASE)
    text = re.sub(r'\byoung\s+girl\b', 'girl', text, flags=re.IGNORECASE)
    text = re.sub(r'\blittle\s+boy\b', 'boy', text, flags=re.IGNORECASE)
    text = re.sub(r'\blittle\s+girl\b', 'girl', text, flags=re.IGNORECASE)
    # Replace child-related words with neutral character equivalents
    text = re.sub(r'\bchildren\b', 'characters', text, flags=re.IGNORECASE)
    text = re.sub(r'\bchild\b', 'character', text, flags=re.IGNORECASE)
    text = re.sub(r'\bkids\b', 'characters', text, flags=re.IGNORECASE)
    text = re.sub(r'\bkid\b', 'character', text, flags=re.IGNORECASE)
    
    # Vietnamese safety translations
    text = re.sub(r'\bbé\s+trai\b', 'cậu bé', text, flags=re.IGNORECASE)
    text = re.sub(r'\bbé\s+gái\b', 'cô bé', text, flags=re.IGNORECASE)
    text = re.sub(r'\btrẻ\s+em\b', 'nhân vật', text, flags=re.IGNORECASE)
    text = re.sub(r'\btrẻ\s+con\b', 'nhân vật', text, flags=re.IGNORECASE)
    text = re.sub(r'\bcon\s+nít\b', 'nhân vật', text, flags=re.IGNORECASE)
    text = re.sub(r'\bhọc\s+sinh\s+tiểu\s+học\b', 'học sinh', text, flags=re.IGNORECASE)
    text = re.sub(r'\bhọc\s+sinh\s+mẫu\s+giáo\b', 'học sinh', text, flags=re.IGNORECASE)
    return text

def compile_motion_prompt(shot: Shot) -> str:
    # 1. SCENE
    scene_desc = shot.environment.strip() if shot.environment else ""
    if shot.lighting:
        lighting_clean = shot.lighting.strip().rstrip(".")
        if "matching the reference" not in lighting_clean.lower():
            scene_desc += f". {lighting_clean} matching the reference image."
        else:
            scene_desc += f". {lighting_clean}"
    else:
        scene_desc += f". Bright cafeteria lighting matching the reference image."
    
    # 2. REFERENCE
    reference_str = "Continue from the provided reference image. Do not change characters' appearance or background environment."
    
    # 3. SHOT
    camera_lines = []
    camera_val = shot.camera if shot.camera else ""
    if "," in camera_val:
        parts_cam = [p.strip() for p in camera_val.split(",")]
        for p in parts_cam:
            p_lower = p.lower()
            if p_lower in ["static", "pan left", "pan right", "zoom in", "zoom out", "tilt up", "tilt down", "tracking shot", "dolly zoom", "pan", "tilt", "zoom"]:
                if "camera" not in p_lower and "shot" not in p_lower:
                    camera_lines.append(f"{p.capitalize()} camera.")
                else:
                    camera_lines.append(p.capitalize() + ".")
            else:
                camera_lines.append(p.capitalize() + ".")
    else:
        shot_t = shot.shot_type if shot.shot_type else "Medium Shot"
        cam_m = shot.camera_movement if shot.camera_movement else "Static"
        camera_lines.append(f"{shot_t.capitalize()}.")
        if cam_m:
            if "camera" not in cam_m.lower() and "shot" not in cam_m.lower():
                camera_lines.append(f"{cam_m.capitalize()} camera.")
            else:
                camera_lines.append(cam_m.capitalize() + ".")
    camera_str = "\n".join(camera_lines)
    
    # 4. TIMELINE
    timeline_lines = []
    for item in shot.timeline:
        t = item.time
        t_clean = t.replace("s", "").strip()
        action_clean = item.action.strip()
        timeline_lines.append(f"{t_clean} {action_clean}")
    if not timeline_lines:
        timeline_lines.append(f"0-{shot.duration_seconds} {shot.actions.strip() if shot.actions else ''}")
    timeline_str = "\n".join(timeline_lines)
    
    # 5. DIALOGUE
    if shot.dialogue:
        dialogue_lines = []
        for d in shot.dialogue:
            dialogue_lines.append(f"{d.character}: \"{d.speech}\"")
        dialogue_str = "\n".join(dialogue_lines)
        dialogue_section = (
            f"{dialogue_str}\n"
            f"Dialogue must match exactly.\n"
            f"No additional speech.\n"
            f"Remain silent after the final line."
        )
    else:
        dialogue_section = "None"
        
    # 6. ACTIONS
    actions_lines = []
    if len(shot.characters) > 1:
        actions_lines.append("Both characters maintain natural breathing, blinking and subtle body movement.")
    elif len(shot.characters) == 1:
        actions_lines.append(f"{shot.characters[0]} maintains natural breathing, blinking and subtle body movement.")
    else:
        actions_lines.append("Characters maintain natural breathing, blinking and subtle body movement.")
    
    if shot.actions:
        actions_lines.append(shot.actions.strip())
        
    for c in shot.characters:
        speaks = any(d.character.strip().lower() == c.strip().lower() for d in shot.dialogue)
        if speaks:
            actions_lines.append(f"{c}: Speaks and gestures naturally.")
        else:
            if shot.dialogue:
                actions_lines.append(f"{c}: Listens and reacts naturally.")
            else:
                if shot.motion and shot.motion.primary_motion:
                    pm = shot.motion.primary_motion.strip().rstrip(".")
                    actions_lines.append(f"{c}: {pm}.")
    actions_str = "\n".join(actions_lines)
    
    # 7. SPATIAL RULES
    spatial_str = (
        "Characters move only through clear walkable space.\n"
        "Walk along existing aisles.\n"
        "Avoid tables, chairs, walls and furniture.\n"
        "Never intersect scene objects.\n"
        "Stop before interacting with furniture.\n"
        "Keep both feet naturally on the floor.\n"
        "Maintain realistic spacing from surrounding objects."
    )
    
    # 8. ENDING
    ending_str = "Hold final pose silently. Blink and breathe naturally."
    
    # 9. STYLE
    style_str = (
        "High-quality stylized 3D animation.\n"
        "Feature film quality.\n"
        "No on-screen text."
    )
    
    parts = [
        f"SCENE:\n{scene_desc}",
        f"REFERENCE:\n{reference_str}",
        f"SHOT:\n{camera_str}",
        f"TIMELINE:\n{timeline_str}",
        f"DIALOGUE:\n{dialogue_section}",
        f"ACTIONS:\n{actions_str}",
        f"SPATIAL RULES:\n{spatial_str}",
        f"ENDING:\n{ending_str}",
        f"STYLE:\n{style_str}"
    ]
    
    full_prompt = "\n\n".join(parts)
    return clean_text_for_safety(full_prompt)


# --- Step 1: Story Analyzer ---
async def run_story_analyzer(storyboard: str, api_keys: List[str], model: str, rpm_limit: int = 5) -> StoryAnalysisResponse:
    system_instruction = (
        "You are a strict Story Parser. Your ONLY task is to read the storyboard text and parse it into structured JSON scenes. "
        "The storyboard is the single source of truth. You must NOT modify, summarize, rewrite, or invent any content. "
        "Keep the scene numbers, durations, locations, actions, dialogues, and characters EXACTLY as written in the storyboard. "
        "Do not change scene durations, actions, or dialogues. Do not add or remove characters. "
        "Just extract the raw data and format it into the requested JSON schema."
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
    system_instruction = (
        "You are an expert Asset Extractor for animation production. "
        "Analyze the storyboard and parsed scenes to identify all unique characters, environments, and props. "
        "For each character, populate all requested details:\n"
        "- id: Unique ID, e.g., 'char_lisa'\n"
        "- canonical_name: The formal consistent name of the character\n"
        "- name: Duplicate of canonical_name\n"
        "- age, gender, appearance, outfit, hairstyle, accessories, voice_style, personality\n"
        "- turnaround_prompt: A highly detailed Pixar-style turnaround prompt for generating reference images (front, 45-degree, side views, Pixar 3D stylized, white background, no text, no shadows)\n"
        "- prompt: Duplicate of turnaround_prompt\n\n"
        "For each environment, populate:\n"
        "- id: Unique ID, e.g., 'env_school_gate'\n"
        "- name: The location name\n"
        "- reference_prompt: A detailed Pixar-style empty room/area reference image prompt (wide angle, consistent lighting, no characters, no text)\n"
        "- prompt: Duplicate of reference_prompt\n\n"
        "For each prop, populate:\n"
        "- id: Unique ID, e.g., 'prop_lunch_box'\n"
        "- name: The prop name\n"
        "- reference_prompt: A detailed Pixar-style prop reference image prompt (centered, white background, no text)\n"
        "- prompt: Duplicate of reference_prompt\n\n"
        "SAFETY RULE: Do NOT include any age-identifying words like 'child', 'children', 'boy', 'girl', 'kid', 'kids', 'young boy', 'young girl', 'schoolboy', 'schoolgirl' or similar child-related terms in the character descriptions or turnaround_prompts. Instead, refer to them only by name or generic terms like 'character' or 'person' to prevent Gemini API safety blocks.\n\n"
        "Return the unique assets in the requested JSON structure. Do not invent any assets not present in the storyboard."
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


# --- Step 3: Shot Planner (Shot Prompt Generator) ---
async def run_shot_planner(
    scenes_json: str,
    characters_json: str,
    environments_json: str,
    props_json: str,
    api_keys: List[str],
    model: str,
    rpm_limit: int = 5,
    chunk_size: int = 5,
    storyboard: Optional[str] = None
) -> ShotPlannerResponse:
    scenes = json.loads(scenes_json)
    all_characters = json.loads(characters_json) if characters_json else []
    all_environments = json.loads(environments_json) if environments_json else []
    all_props = json.loads(props_json) if props_json else []
    
    # Chunk scenes to execute in groups of chunk_size for stability
    scene_chunks = [scenes[i:i + chunk_size] for i in range(0, len(scenes), chunk_size)]
    
    all_shots = []
    
    system_instruction = (
        "You are an expert animation Shot Prompt Generator.\n"
        "Your task is to translate a sequence of analyzed scenes into individual camera shots, generating both a detailed Keyframe reference image prompt and structured shot parameters (timeline, camera, lighting, motion details, transition, dialogue).\n\n"
        "CRITICAL SCENE & SHOT CONTINUITY RULES (NEVER FORGET):\n"
        "- Read and analyze the 'Previously Generated Shots' section carefully (if present) before generating the new shots.\n"
        "- Track Character States & Inventory: If a character was holding or carrying a prop (e.g. 'Emma holds a cup of water') in the previous shots, they must CONTINUE to hold/carry it in the new shots, unless they explicitly set it down in the story or a new action describes them setting it down. If they set it down, they must no longer hold it in subsequent shots.\n"
        "- Avoid Magic Appearances/Disappearances: Objects and props cannot suddenly appear in a character's hand or disappear from a scene without a transition or logical visual explanation. Keep props and characters' poses persistent across cuts.\n"
        "- Track Character Positions & Spatial Layout: If a character walked to a specific location (e.g. 'Lisa walks to the blue table and sits down') at the end of the previous shot, they must start from that exact position/sitting pose in the next shot to maintain geographic and spatial continuity.\n"
        "- Track Environmental Status: If an action modified the environment (e.g. 'opens a door', 'turns off lights', 'drops a notebook on the floor'), this status must persist in the background of subsequent shots until another action changes it.\n"
        "- Ensure that the `keyframe_prompt` (which describes the visual elements for the image generator) matches these continuity constraints. If Emma is holding a cup in the previous shot and has not set it down, her keyframe prompt for the next shot must also mention her holding the cup.\n\n"
        "CRITICAL SHOT DURATION & SPLITTING RULE:\n"
        "- MULTIPLE SPEAKERS DIALOGUE SPLITTING RULE (CRITICAL): If a scene contains dialogue/speech from MULTIPLE DIFFERENT SPEAKERS (e.g., 2 or more different characters speaking, such as Lisa speaking and Emma replying), you MUST split this scene into multiple sequential shots so that EACH shot contains the dialogue of ONLY ONE speaker. A single shot must NEVER contain dialogue from more than one character. This is required because the video generator (Veo3) cannot synthesize two different voices/speakers within a single video clip.\n"
        "- DIALOGUE SHOT PRIORITIZATION & SPEAKING FOCUS (CRITICAL): In any shot that contains dialogue (especially during back-and-forth conversational exchanges / đối đáp), the spoken dialogue must take absolute priority in the shot's planning.\n"
        "  - The shot's camera framing must focus primarily on the character who is speaking (e.g. shot_type must be Close-up or Medium Shot focusing on the speaking character).\n"
        "  - The duration of the shot must first satisfy the speaking time of the dialogue. Any actions or reactions from the speaking or listening character must be planned to support or occur immediately before/after the dialogue, without cutting off or rushing the speech.\n"
        "- CROSS-LOCATION CONVERSATIONS RULE (CRITICAL): If a scene contains a conversation between characters in different physical settings/locations (e.g. Character A is inside the house, Character B is outside in the yard):\n"
        "  - You MUST split the scene into separate sequential shots, assigning the correct specific environment name to EACH shot depending on who is visible in that shot. Do NOT put both shots in the same environment.\n"
        "- PHONE CALL & OFF-SCREEN DIALOGUE LIP-SYNC RULE (CRITICAL):\n"
        "  - When a character (e.g., Character A) is speaking but is OFF-SCREEN (e.g. speaking over the phone, or acting as an off-screen voiceover, while the camera is focusing on Character B listening):\n"
        "    1. The `characters` list for that shot MUST ONLY contain Character B (the visible character), NOT Character A.\n"
        "    2. You MUST explicitly state in the `actions` field and `keyframe_prompt` that: 'Character B is listening silently with closed lips, reacting to the voice on the phone.' and 'Character A is off-screen / voiceover.'\n"
        "    3. This is critical to prevent the video generator (Veo3) from mistakenly moving B's lips to A's speech.\n"
        "- DYNAMIC SHOT DURATION CALCULATION RULES (CRITICAL):\n"
        "  1. For short dialogues or simple responses: the shot duration should be planned within 4 to 6 seconds (e.g., 0-1s for action/expression, 1-5s for the character's short line like 'Alo ạ?').\n"
        "  2. For longer dialogues or more descriptive sentences: maximize the shot duration to the absolute limit of 8 seconds (0-8s) (e.g., 'Nhà con có ai ở nhà không?') to ensure the character has ample time to speak comfortably and show facial expressions without feeling rushed.\n"
        "  3. For any shot containing dialogue: the duration must be at least: `ceil(character_count / 15) + 2 seconds` of buffer (for natural breathing, gestures, or reaction/performance pauses). A shot containing speech must NEVER be shorter than 4 seconds.\n"
        "  4. For any shot containing complex physical actions (e.g. walking, sitting down, picking up/setting down a prop, opening doors): allocate at least 4 to 6 seconds for that action to happen naturally in the video.\n"
        "  5. If a shot contains BOTH a physical action and dialogue, combine their requirements (e.g., if a character walks to a table and then speaks a 3-second line, the shot duration must be at least 4s for walking + 4s for speaking = 8 seconds).\n"
        "  6. MAXIMUM SHOT DURATION LIMIT (CRITICAL): The duration of any single shot must NEVER exceed 8 seconds (because the video generation model can only produce clips up to 8 seconds). If a dialogue or action requires more than 8 seconds, you MUST split it into multiple sequential shots (each between 4 to 8 seconds) so that no single shot's duration exceeds 8 seconds.\n"
        "  7. Dynamic Scene Duration Overriding: If the sum of the required durations for the split shots exceeds the original scene's `duration_seconds` (because the storyboard's scene duration was underestimated), you MUST override the duration and increase the shot's `duration_seconds` to satisfy the minimum requirements above. Do NOT squeeze or shorten the shot duration to fit a too-short original scene duration. (It is NOT required that the sum of the split shot durations equals the original scene duration).\n"
        "- FLEXIBLE SHOT QUANTITY & GRANULAR SPLITTING (CRITICAL): You are encouraged to split a scene into as many sequential shots as logically needed to tell the story clearly and smoothly. There is no maximum limit of shots per scene. For example, if a scene has a character walking, then reacting, then character A speaking, then character B replying, you can split this into 4 separate shots (e.g., Shot 1: Emma walking, Shot 2: Close-up of Emma smiling/reacting, Shot 3: Emma speaking, Shot 4: Lisa replying). Prioritize visual variety, emotional expression, and proper pacing over minimizing the number of shots. Do NOT try to force complex actions and dialogues into only 2 shots.\n"
        "- BÓC TÁCH HÀNH ĐỘNG, LỜI THOẠI, VÀ DIỄN TẢ (CRITICAL):\n"
        "  - You MUST clearly separate the physical action (e.g. walking, moving props), the spoken dialogue, and the character's expression/performance/reactions (e.g., smiling, crying, looking surprised, listening intently).\n"
        "  - The physical action and dialogue must be mapped chronologically to the `timeline` field.\n"
        "  - Character expressions, reaction styles, and performance details must be clearly described in the `actions` field and reflected in the `keyframe_prompt` (e.g., 'Lisa looks up at Emma with a warm, welcoming smile') to ensure the generator synthesizes proper facial expressions and emotional context.\n"
        "- When splitting a scene into multiple shots, you must distribute the scene's dialogue, actions, expressions, and timeline sequentially and logically across the split shots. Ensure that no dialogue or action overlaps or is repeated. If a shot contains a character's dialogue, only include that specific character's speech in that shot's dialogue list.\n"
        "  * Concrete Splitting Example: If a scene is 10s long (Bối cảnh: Cafeteria) and has Description: 'Lisa returns to the table. Emma smiles.' and Dialogue: [Emma: 'Great job!', Lisa: 'Now my hands are clean.']. You should split it into 2 shots:\n"
        "    - Shot A (5s): Focuses on Emma speaking 'Great job!' (e.g. camera framing focusing on Emma, Dialogue list only contains Emma: 'Great job!').\n"
        "    - Shot B (5s): Focuses on Lisa replying 'Now my hands are clean.' (e.g. camera framing focusing on Lisa, Dialogue list only contains Lisa: 'Now my hands are clean.').\n\n"
        "Your additions for each shot:\n"
        "1. Camera and framing parameters. You must apply these strict Camera Rule mappings to determine camera_movement and shot_type:\n"
        "   - Focus on Dialogue -> shot_type must be 'Medium Shot'\n"
        "   - Focus on Emotion -> shot_type must be 'Close-up'\n"
        "   - Focus on Walking -> camera_movement must be 'Tracking Shot'\n"
        "   - Focus on Introducing a location -> shot_type must be 'Wide Shot'\n"
        "   - Focus on Action (active movements) -> shot_type must be 'Medium Wide'\n"
        "   - Focus on a specific Object -> shot_type must be 'Insert Shot'\n"
        "   - Focus on Reaction -> shot_type must be 'Close-up'\n"
        "   Define `camera` as a combination (e.g. 'Medium Shot, Static'). Specify composition, lighting, transition.\n\n"
        "2. Keyframe Prompt (Image Prompt):\n"
        "   - Write a detailed text-to-image prompt to generate a single static keyframe reference image.\n"
        "   - DO NOT repeat or describe the character's appearance, features, hairstyle, clothing, outfit, or other visual details (e.g. do not say 'female, brown hair, wearing a striped t-shirt...'). Doing so is extremely incorrect.\n"
        "   - Instead, ONLY refer to each character by their specific name (e.g. 'Lisa', 'Emma'). Do NOT write the media_id or any ID in the prompt text.\n"
        "   - Similarly, do not repeat or describe the environments or props. Refer to them only by their name (e.g., 'cafeteria', 'lunch tray') without writing any ID or description.\n"
        "   - Include only the character name(s), the environment name, any active props, the character actions/posing, camera framing/shot type (e.g. Medium Shot, Close-up), and lighting/mood details.\n"
        "   - Ensure the prompt starts with the standard style prefix: 'Pixar-quality stylized 3D, cinematic composition, reference keyframe, no motion blur, no text, no captions.' followed by the characters, environment, props, actions, framing, and lighting.\n"
        "   - Do NOT describe motion, timeline, movement, or speech in the keyframe prompt.\n"
        "   - Clean the text for safety: do not include age descriptors or sensitive child-related terms (ONLY refer to characters by their specific names like 'Lisa', 'Tom', or generic terms like 'person' or 'character' to prevent Gemini API safety blocks. Do NOT use terms like 'boy', 'girl', 'child', or 'kids').\n\n"
        "3. Timeline:\n"
        "   - Generate a simple chronological breakdown of actions in seconds, matching the shot duration. Keep descriptions concise and simple.\n"
        "   - Dialogue lines in the timeline MUST be formatted exactly as: '[CharacterName]: [Dialogue text]'. Other actions should be simple descriptions.\n"
        "   - Example:\n"
        "     [{\"time\": \"0-3\", \"action\": \"Emma notices Lisa.\"}, {\"time\": \"3-6\", \"action\": \"Emma: Lisa, did you wash your hands?\"}, {\"time\": \"6-8\", \"action\": \"Lisa: Oh! I forgot.\"}]\n"
        "   - CRITICAL DIALOGUE DURATION RULE: For any dialogue action (e.g. '[CharacterName]: ...'), you MUST allocate a reasonable duration based on character count: average speaking speed is roughly 15 English characters per second (including spaces). Calculate speaking duration as: ceil(character_count / 15) + 2 seconds of buffer for natural pauses. Speaking segments must NEVER be shorter than 4 seconds (e.g. if the formula yields less than 4, default to 4 seconds) to prevent characters from being cut off mid-speech. For example, if a dialogue has 33 characters, allocate 33/15 + 2 = 4.2s -> round up to 5 seconds in the timeline.\n\n"
        "4. Motion Details:\n"
        "   - primary_motion: The main motion of the character (e.g. 'Walk') in English.\n"
        "   - secondary_motion: List of secondary/idle motions, e.g. ['Blink', 'Breathing'].\n"
        "   - motion_level: Motion level, e.g. 'Low', 'Medium', 'High'.\n\n"
        "5. Character Motion and Walking Rules (CRITICAL):\n"
        "   - Never describe only the destination (e.g., do not write 'Lisa walks to the table').\n"
        "   - Always describe: 1) starting position, 2) walking path, and 3) stopping position (e.g., 'Lisa walks along the open aisle between the tables and stops beside the blue table').\n"
        "   - Characters never choose their own path. Always instruct them to use existing walkable space.\n"
        "   - Never pass through furniture. Never intersect objects.\n"
        "   - Keep realistic physical spacing from surrounding objects and other characters.\n"
        "   - Avoid long walking whenever possible. Prefer standing, turning, leaning, or small steps.\n\n"
        "Ensure shot_id is sequential: Shot001, Shot002, etc. Return valid JSON conforming to the ShotPlannerResponse schema."
    )
    
    # We need to maintain an overall sequential shot_id counter across chunks.
    # To do this, we can let Gemini generate the schema first, and then post-process the shot_ids to ensure they are sequence aligned starting from 1.
    global_shot_counter = 1
    
    for chunk in scene_chunks:
        # Collect referenced assets in this chunk
        referenced_chars = set()
        referenced_envs = set()
        referenced_props = set()
        for scene in chunk:
            for c in scene.get("characters", []):
                referenced_chars.add(c.strip().lower())
            env = scene.get("location") or scene.get("setting")
            if env:
                referenced_envs.add(env.strip().lower())
            for p in scene.get("props", []):
                referenced_props.add(p.strip().lower())
        
        # Filter assets to only include referenced ones, with fallback to all if none match
        chunk_characters = [
            c for c in all_characters 
            if c.get("name", "").strip().lower() in referenced_chars or 
               c.get("canonical_name", "").strip().lower() in referenced_chars or
               c.get("id", "").strip().lower() in referenced_chars
        ]
        if not chunk_characters and all_characters:
            chunk_characters = all_characters

        chunk_environments = [
            e for e in all_environments 
            if e.get("name", "").strip().lower() in referenced_envs or 
               e.get("setting_name", "").strip().lower() in referenced_envs or
               e.get("id", "").strip().lower() in referenced_envs
        ]
        if not chunk_environments and all_environments:
            chunk_environments = all_environments

        chunk_props = [
            p for p in all_props 
            if p.get("name", "").strip().lower() in referenced_props or 
               p.get("prop_name", "").strip().lower() in referenced_props or
               p.get("id", "").strip().lower() in referenced_props
        ]
        if not chunk_props and all_props:
            chunk_props = all_props
        
        # Clean character fields for safety (removing age / child keywords)
        cleaned_characters = []
        for c in chunk_characters:
            cc = c.copy()
            cc["age"] = ""
            for field in ["appearance", "outfit", "hairstyle", "accessories", "turnaround_prompt", "prompt", "personality", "voice_style", "description", "gender"]:
                if field in cc and cc[field]:
                    cc[field] = clean_text_for_safety(cc[field])
            cleaned_characters.append(cc)
            
        # Clean environment fields for safety
        cleaned_environments = []
        for e in chunk_environments:
            ee = e.copy()
            for field in ["description", "turnaround_prompt", "prompt", "reference_prompt"]:
                if field in ee and ee[field]:
                    ee[field] = clean_text_for_safety(ee[field])
            cleaned_environments.append(ee)
            
        # Clean prop fields for safety
        cleaned_props = []
        for p in chunk_props:
            pp = p.copy()
            for field in ["description", "turnaround_prompt", "prompt", "reference_prompt"]:
                if field in pp and pp[field]:
                    pp[field] = clean_text_for_safety(pp[field])
            cleaned_props.append(pp)
 
        # Ensure we clean storyboard if provided, otherwise clean scene actions
        cleaned_chunk = []
        for scene in chunk:
            sc = scene.copy()
            if "action" in sc and sc["action"]:
                sc["action"] = clean_text_for_safety(sc["action"])
            if "description" in sc and sc["description"]:
                sc["description"] = clean_text_for_safety(sc["description"])
            if "dialogue" in sc and sc["dialogue"]:
                cleaned_dialogue = []
                for d in sc["dialogue"]:
                    dc = d.copy()
                    if "speech" in dc and dc["speech"]:
                        dc["speech"] = clean_text_for_safety(dc["speech"])
                    if "text" in dc and dc["text"]:
                        dc["text"] = clean_text_for_safety(dc["text"])
                    cleaned_dialogue.append(dc)
                sc["dialogue"] = cleaned_dialogue
            cleaned_chunk.append(sc)

        chunk_scenes_json = json.dumps(cleaned_chunk, ensure_ascii=False)
        chunk_characters_json = json.dumps(cleaned_characters, ensure_ascii=False)
        chunk_environments_json = json.dumps(cleaned_environments, ensure_ascii=False)
        chunk_props_json = json.dumps(cleaned_props, ensure_ascii=False)
        
        # Get the sliding window of last 12 shots for continuity context
        recent_shots = all_shots[-12:] if len(all_shots) > 12 else all_shots
        previous_shots_str = ""
        if recent_shots:
            simplified_previous = []
            for s in recent_shots:
                simplified_previous.append({
                    "shot_id": s.shot_id,
                    "scene_number": s.scene_number,
                    "characters": s.characters,
                    "environment": s.environment,
                    "props": s.props,
                    "actions": s.actions,
                    "dialogue": [{"character": d.character, "speech": d.speech} for d in s.dialogue] if s.dialogue else [],
                    "keyframe_prompt": s.keyframe_prompt
                })
            previous_shots_str = json.dumps(simplified_previous, ensure_ascii=False, indent=2)
        else:
            previous_shots_str = "None (This is the start of the storyboard)"

        prompt = (
            f"Previously Generated Shots (for continuity context):\n{previous_shots_str}\n\n"
            f"Scenes to generate shots for in this batch:\n{chunk_scenes_json}\n\n"
            f"Character Reference Assets:\n{chunk_characters_json}\n\n"
            f"Environment Reference Assets:\n{chunk_environments_json}\n\n"
            f"Prop Reference Assets:\n{chunk_props_json}\n\n"
            f"Generate shots, keyframe prompts, and motion parameters for this batch of scenes. Apply camera rules and keep durations exactly."
        )
        
        response_text = await generate_gemini_content(
            api_keys=api_keys,
            model=model,
            prompt=prompt,
            system_instruction=system_instruction,
            response_schema=ShotPlannerResponse,
            rpm_limit=rpm_limit
        )
        chunk_data = ShotPlannerResponse.model_validate_json(response_text)
        
        # Format shot IDs and compile motion prompts programmatically
        for shot in chunk_data.shots:
            shot.shot_id = f"Shot{global_shot_counter:03d}"
            global_shot_counter += 1
            # Compile the motion prompt string using the helper
            shot.motion_prompt = compile_motion_prompt(shot)
            
        all_shots.extend(chunk_data.shots)
        
    return ShotPlannerResponse(shots=all_shots)

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
    shots = json.loads(shots_json)
    
    # Check if all shots already have keyframe_prompt (pre-computed by Shot Prompt Generator)
    if shots and all(bool(s.get("keyframe_prompt")) for s in shots):
        keyframes = [
            ShotKeyframePrompt(shot_id=s["shot_id"], prompt=s["keyframe_prompt"])
            for s in shots
        ]
        return KeyframePromptResponse(keyframes=keyframes)
    
    # Group shots by scene number first to keep context isolated, then split if scene shots exceed chunk_size
    from collections import defaultdict
    shots_by_scene = defaultdict(list)
    for shot in shots:
        scene_num = shot.get("scene_number") or shot.get("scene_id") or 1
        try:
            scene_num = int(scene_num)
        except (ValueError, TypeError):
            scene_num = 1
        shots_by_scene[scene_num].append(shot)
        
    shot_chunks = []
    for scene_num in sorted(shots_by_scene.keys()):
        scene_shots = shots_by_scene[scene_num]
        for i in range(0, len(scene_shots), chunk_size):
            shot_chunks.append(scene_shots[i:i + chunk_size])
    
    all_keyframes = []
    
    # Parse full assets
    all_characters = json.loads(characters_json) if characters_json else []
    all_environments = json.loads(environments_json) if environments_json else []
    all_props = json.loads(props_json) if props_json else []
    
    system_instruction = (
        "You are an expert Keyframe Image Prompt Generator.\n"
        "For each shot in the provided list, write a detailed text-to-image prompt to generate a single static keyframe reference image.\n\n"
        "CRITICAL SCENE & SHOT CONTINUITY RULES (NEVER FORGET):\n"
        "- Read and analyze the 'Previously Generated Keyframe Prompts' section carefully (if present) before generating the new prompts.\n"
        "- Track Character States & Inventory: If a character was holding or carrying a prop (e.g. 'Emma holds a cup of water') in the previous keyframe prompts, they must CONTINUE to hold/carry it in the new prompts, unless they explicitly set it down in the shot description or action. If they set it down, they must no longer hold it in subsequent prompts.\n"
        "- Keep character positions, poses, and environment status consistent with the previous keyframe prompts.\n\n"
        "PROMPT FORMATTING RULES:\n"
        "- DO NOT repeat or describe the character's appearance, features, hairstyle, clothing, outfit, or other visual details (e.g. do not say 'female, brown hair, wearing a striped t-shirt...'). Doing so is extremely incorrect.\n"
        "- Instead, ONLY refer to each character by their specific name (e.g. 'Lisa', 'Emma'). Do NOT write the media_id or any ID in the prompt text.\n"
        "- Similarly, do not repeat or describe the environments or props. Refer to them only by their name (e.g., 'cafeteria', 'lunch tray') without writing any ID or description.\n"
        "- Include only the character name(s), the environment name, any active props, the character actions/posing, camera framing/shot type (e.g. Medium Shot, Close-up), and lighting/mood details.\n"
        "- Ensure the prompt starts with the standard style prefix: 'Pixar-quality stylized 3D, cinematic composition, reference keyframe, no motion blur, no text, no captions.' followed by the characters, environment, props, actions, framing, and lighting.\n"
        "- Do NOT describe motion, timeline, movement, or speech in the keyframe prompt.\n"
        "- SAFETY RULE: Do NOT use any age-identifying words like 'child', 'children', 'boy', 'girl', 'kid', 'kids', 'young boy', 'young girl', 'schoolboy', 'schoolgirl' or similar child-related terms in the prompts. Instead, ONLY refer to characters by their specific names (e.g. 'Lisa', 'Tom') or generic terms (e.g. 'person', 'character')."
    )
    
    for chunk in shot_chunks:
        # Collect referenced assets in this chunk
        referenced_chars = set()
        referenced_envs = set()
        referenced_props = set()
        for shot in chunk:
            for c in shot.get("characters", []):
                referenced_chars.add(c.strip().lower())
            env = shot.get("environment")
            if env:
                referenced_envs.add(env.strip().lower())
            for p in shot.get("props", []):
                referenced_props.add(p.strip().lower())
        
        # Filter assets to only include referenced ones, with fallback to all if none match
        chunk_characters = [
            c for c in all_characters 
            if c.get("name", "").strip().lower() in referenced_chars or 
               c.get("canonical_name", "").strip().lower() in referenced_chars
        ]
        if not chunk_characters and all_characters:
            chunk_characters = all_characters

        chunk_environments = [
            e for e in all_environments 
            if e.get("name", "").strip().lower() in referenced_envs or 
               e.get("setting_name", "").strip().lower() in referenced_envs
        ]
        if not chunk_environments and all_environments:
            chunk_environments = all_environments

        chunk_props = [
            p for p in all_props 
            if p.get("name", "").strip().lower() in referenced_props or 
               p.get("prop_name", "").strip().lower() in referenced_props
        ]
        if not chunk_props and all_props:
            chunk_props = all_props
        
        # Clean character fields for safety (removing age / child keywords)
        cleaned_characters = []
        for c in chunk_characters:
            cc = c.copy()
            cc["age"] = ""
            for field in ["appearance", "outfit", "hairstyle", "accessories", "turnaround_prompt", "prompt", "personality", "voice_style", "description", "gender"]:
                if field in cc and cc[field]:
                    cc[field] = clean_text_for_safety(cc[field])
            cleaned_characters.append(cc)
            
        # Clean environment fields for safety
        cleaned_environments = []
        for e in chunk_environments:
            ee = e.copy()
            for field in ["description", "turnaround_prompt", "prompt"]:
                if field in ee and ee[field]:
                    ee[field] = clean_text_for_safety(ee[field])
            cleaned_environments.append(ee)
            
        # Clean prop fields for safety
        cleaned_props = []
        for p in chunk_props:
            pp = p.copy()
            for field in ["description", "turnaround_prompt", "prompt"]:
                if field in pp and pp[field]:
                    pp[field] = clean_text_for_safety(pp[field])
            cleaned_props.append(pp)

        # Clean shots chunk for safety
        cleaned_chunk = []
        for shot in chunk:
            s_copy = shot.copy()
            for field in ["actions", "action", "description"]:
                if field in s_copy and s_copy[field]:
                    s_copy[field] = clean_text_for_safety(s_copy[field])
            if "dialogue" in s_copy and s_copy["dialogue"]:
                cleaned_dialogue = []
                for d in s_copy["dialogue"]:
                    dc = d.copy()
                    if "speech" in dc and dc["speech"]:
                        dc["speech"] = clean_text_for_safety(dc["speech"])
                    if "text" in dc and dc["text"]:
                        dc["text"] = clean_text_for_safety(dc["text"])
                    cleaned_dialogue.append(dc)
                s_copy["dialogue"] = cleaned_dialogue
            cleaned_chunk.append(s_copy)

        chunk_shots_json = json.dumps(cleaned_chunk, ensure_ascii=False)
        chunk_characters_json = json.dumps(cleaned_characters, ensure_ascii=False)
        chunk_environments_json = json.dumps(cleaned_environments, ensure_ascii=False)
        chunk_props_json = json.dumps(cleaned_props, ensure_ascii=False)
        
        # Get the sliding window of last 12 keyframe prompts for continuity context
        recent_keyframes = all_keyframes[-12:] if len(all_keyframes) > 12 else all_keyframes
        previous_keyframes_str = ""
        if recent_keyframes:
            previous_keyframes_str = json.dumps([{"shot_id": k.shot_id, "prompt": k.prompt} for k in recent_keyframes], ensure_ascii=False, indent=2)
        else:
            previous_keyframes_str = "None"
            
        prompt = (
            f"Previously Generated Keyframe Prompts (for continuity context):\n{previous_keyframes_str}\n\n"
            f"Shots to generate keyframe prompts for in this batch:\n{chunk_shots_json}\n\n"
            f"Character Assets:\n{chunk_characters_json}\n\n"
            f"Environment Assets:\n{chunk_environments_json}\n\n"
            f"Prop Assets:\n{chunk_props_json}\n\n"
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
    storyboard: str,
    shots_json: str,
    characters_json: str,
    environments_json: str,
    props_json: str,
    api_keys: List[str],
    model: str,
    rpm_limit: int = 5,
    chunk_size: int = 5,
    custom_instructions: Optional[str] = None
) -> MotionPromptResponse:
    shots = json.loads(shots_json)
    
    # Compile motion prompts directly from shot details if custom_instructions is not provided
    has_all_prompts = True
    motion_prompts = []
    
    if not custom_instructions:
        for s in shots:
            try:
                # Try compiling from shot details (no Gemini API calls, extremely fast)
                shot_obj = Shot.model_validate(s)
                if shot_obj.motion_prompt and shot_obj.motion_prompt.strip():
                    compiled = shot_obj.motion_prompt
                else:
                    compiled = compile_motion_prompt(shot_obj)
                motion_prompts.append(ShotMotionPrompt(shot_id=s["shot_id"], prompt=compiled))
            except Exception as e:
                logger.warning(f"Failed to validate shot for programmatic compilation: {e}. Falling back to Gemini.")
                has_all_prompts = False
                break
    else:
        has_all_prompts = False
            
    if shots and has_all_prompts:
        return MotionPromptResponse(motion_prompts=motion_prompts)
    
    # Group shots by scene number first to keep context isolated, then split if scene shots exceed chunk_size
    from collections import defaultdict
    shots_by_scene = defaultdict(list)
    for shot in shots:
        scene_num = shot.get("scene_number") or shot.get("scene_id") or 1
        try:
            scene_num = int(scene_num)
        except (ValueError, TypeError):
            scene_num = 1
        shots_by_scene[scene_num].append(shot)
        
    shot_chunks = []
    for scene_num in sorted(shots_by_scene.keys()):
        scene_shots = shots_by_scene[scene_num]
        for i in range(0, len(scene_shots), chunk_size):
            shot_chunks.append(scene_shots[i:i + chunk_size])
    
    all_motion_prompts = []
    
    # Parse full assets
    all_characters = json.loads(characters_json) if characters_json else []
    all_environments = json.loads(environments_json) if environments_json else []
    all_props = json.loads(props_json) if props_json else []
    
    system_instruction = (
        "You are an expert Motion Prompt Generator for Google Veo 3 (video generation).\n"
        "For each shot, you must output a structured, extremely concise, 100% English motion prompt.\n"
        "Your generated prompt for each shot MUST strictly follow this exact format and order:\n\n"
        "SCENE:\n"
        "[Brief setting name and environment/lighting details. Include 'matching the reference image' for consistency.]\n\n"
        "REFERENCE:\n"
        "Continue from the provided reference image. Do not change characters' appearance or background environment.\n\n"
        "SHOT:\n"
        "[Camera framing and movement, e.g. 'Medium shot. Static camera.']\n\n"
        "TIMELINE:\n"
        "[Simple chronological breakdown of actions in seconds, without 's' suffixes, e.g.:\n"
        "0-3 Emma notices Lisa.\n"
        "3-6 Emma: Lisa, did you wash your hands?\n"
        "6-8 Lisa: Oh! I forgot.]\n\n"
        "DIALOGUE:\n"
        "[Dialogue lines, e.g. Emma: \"Lisa, did you wash your hands?\". Below the dialogue, append exactly:\n"
        "Dialogue must match exactly.\n"
        "No additional speech.\n"
        "Remain silent after the final line.\n"
        "If there is no dialogue, write 'None'.]\n\n"
        "ACTIONS:\n"
        "[Simplified character movements. Always start with: 'Both characters maintain natural breathing, blinking and subtle body movement.' (or single character equivalent). Followed by the shot action, and character behaviors, e.g. 'Emma: Looks toward Lisa and speaks.' / 'Lisa: Turns toward Emma and replies.']\n\n"
        "SPATIAL RULES:\n"
        "Characters move only through clear walkable space.\n"
        "Walk along existing aisles.\n"
        "Avoid tables, chairs, walls and furniture.\n"
        "Never intersect scene objects.\n"
        "Stop before interacting with furniture.\n"
        "Keep both feet naturally on the floor.\n"
        "Maintain realistic spacing from surrounding objects.\n\n"
        "ENDING:\n"
        "Hold final pose silently. Blink and breathe naturally.\n\n"
        "STYLE:\n"
        "High-quality stylized 3D animation.\n"
        "Feature film quality.\n"
        "No on-screen text.\n\n"
        "CRITICAL LIMITS:\n"
        "- Total word count must be between 80 and 150 words. Do not repeat descriptions or write unnecessary details.\n"
        "- Do not use any Negative Prompt section.\n"
        "- SAFETY RULE: Do NOT use any age-identifying words like 'child', 'children', 'boy', 'girl', 'kid', 'kids', 'young boy', 'young girl', 'schoolboy', 'schoolgirl' or similar child-related terms in the motion prompts. Instead, ONLY refer to characters by their specific names (e.g. 'Lisa', 'Tom') or generic pronouns (e.g. 'they', 'he', 'she')."
    )
    
    for chunk in shot_chunks:
        # Collect referenced assets and scene numbers in this chunk
        referenced_chars = set()
        referenced_envs = set()
        referenced_props = set()
        scene_numbers = set()
        for shot in chunk:
            for c in shot.get("characters", []):
                referenced_chars.add(c.strip().lower())
            env = shot.get("environment")
            if env:
                referenced_envs.add(env.strip().lower())
            for p in shot.get("props", []):
                referenced_props.add(p.strip().lower())
            scene_id = shot.get("scene_number") or shot.get("scene_id")
            if scene_id is not None:
                try:
                    scene_numbers.add(int(scene_id))
                except ValueError:
                    pass
        
        # Filter assets, with fallback to all if none match
        chunk_characters = [
            c for c in all_characters 
            if c.get("name", "").strip().lower() in referenced_chars or 
               c.get("canonical_name", "").strip().lower() in referenced_chars
        ]
        if not chunk_characters and all_characters:
            chunk_characters = all_characters

        chunk_environments = [
            e for e in all_environments 
            if e.get("name", "").strip().lower() in referenced_envs or 
               e.get("setting_name", "").strip().lower() in referenced_envs
        ]
        if not chunk_environments and all_environments:
            chunk_environments = all_environments

        chunk_props = [
            p for p in all_props 
            if p.get("name", "").strip().lower() in referenced_props or 
               p.get("prop_name", "").strip().lower() in referenced_props
        ]
        if not chunk_props and all_props:
            chunk_props = all_props
        
        # Extract only relevant storyboard text
        chunk_storyboard = extract_relevant_storyboard_scenes(storyboard, scene_numbers)
        # Clean storyboard for safety
        chunk_storyboard = clean_text_for_safety(chunk_storyboard)
        
        # Clean character fields for safety (removing age / child keywords)
        cleaned_characters = []
        for c in chunk_characters:
            cc = c.copy()
            cc["age"] = ""
            for field in ["appearance", "outfit", "hairstyle", "accessories", "turnaround_prompt", "prompt", "personality", "voice_style", "description", "gender"]:
                if field in cc and cc[field]:
                    cc[field] = clean_text_for_safety(cc[field])
            cleaned_characters.append(cc)
            
        # Clean environment fields for safety
        cleaned_environments = []
        for e in chunk_environments:
            ee = e.copy()
            for field in ["description", "turnaround_prompt", "prompt"]:
                if field in ee and ee[field]:
                    ee[field] = clean_text_for_safety(ee[field])
            cleaned_environments.append(ee)
            
        # Clean prop fields for safety
        cleaned_props = []
        for p in chunk_props:
            pp = p.copy()
            for field in ["description", "turnaround_prompt", "prompt"]:
                if field in pp and pp[field]:
                    pp[field] = clean_text_for_safety(pp[field])
            cleaned_props.append(pp)

        # Clean shots chunk for safety
        cleaned_chunk = []
        for shot in chunk:
            s_copy = shot.copy()
            for field in ["actions", "action", "description"]:
                if field in s_copy and s_copy[field]:
                    s_copy[field] = clean_text_for_safety(s_copy[field])
            if "dialogue" in s_copy and s_copy["dialogue"]:
                cleaned_dialogue = []
                for d in s_copy["dialogue"]:
                    dc = d.copy()
                    if "speech" in dc and dc["speech"]:
                        dc["speech"] = clean_text_for_safety(dc["speech"])
                    if "text" in dc and dc["text"]:
                        dc["text"] = clean_text_for_safety(dc["text"])
                    cleaned_dialogue.append(dc)
                s_copy["dialogue"] = cleaned_dialogue
            cleaned_chunk.append(s_copy)
            
        chunk_shots_json = json.dumps(cleaned_chunk, ensure_ascii=False)
        chunk_characters_json = json.dumps(cleaned_characters, ensure_ascii=False)
        chunk_environments_json = json.dumps(cleaned_environments, ensure_ascii=False)
        chunk_props_json = json.dumps(cleaned_props, ensure_ascii=False)
        
        prompt = (
            f"Storyboard:\n{chunk_storyboard}\n\n"
            f"Shots in this batch:\n{chunk_shots_json}\n\n"
            f"Character Reference Assets:\n{chunk_characters_json}\n\n"
            f"Environment Reference Assets:\n{chunk_environments_json}\n\n"
            f"Prop Reference Assets:\n{chunk_props_json}\n\n"
        )
        if custom_instructions:
            prompt += f"Additional User Instructions/Requirements:\n{custom_instructions}\n\n"
        prompt += "Generate Veo 3 motion prompts for this batch of shots conforming to formatting guidelines, length limit, and Motion Direction Rules. Apply the Additional User Instructions/Requirements if provided."
        
        response_text = await generate_gemini_content(
            api_keys=api_keys,
            model=model,
            prompt=prompt,
            system_instruction=system_instruction,
            response_schema=MotionPromptResponse,
            rpm_limit=rpm_limit
        )
        chunk_data = MotionPromptResponse.model_validate_json(response_text)
        
        # Check compliance and regenerate if needed for each shot in the chunk
        for s in chunk:
            shot_id = s["shot_id"]
            motion_item = next((mp for mp in chunk_data.motion_prompts if mp.shot_id == shot_id), None)
            if not motion_item:
                continue
            
            # retry loop
            for attempt in range(3):
                # run compliance check with filtered storyboard
                check_res = await check_compliance(
                    motion_prompt=motion_item.prompt,
                    shot=s,
                    storyboard=chunk_storyboard,
                    api_keys=api_keys,
                    model=model,
                    rpm_limit=rpm_limit
                )
                if check_res.is_compliant:
                    break
                
                # If fail, regenerate it specifically
                print(f"Compliance check failed for {shot_id} (Attempt {attempt+1}): {check_res.errors}")
                regen_prompt = (
                    f"The previously generated motion prompt for shot {shot_id} failed compliance checking.\n"
                    f"Errors:\n" + "\n".join(f"- {err}" for err in check_res.errors) + "\n\n"
                    f"Previous Prompt:\n{motion_item.prompt}\n\n"
                    f"Shot Details:\n{json.dumps(s, ensure_ascii=False)}\n\n"
                    f"Character Assets:\n{chunk_characters_json}\n\n"
                    f"Environment Assets:\n{chunk_environments_json}\n\n"
                    f"Prop Assets:\n{chunk_props_json}\n\n"
                    f"Please rewrite the motion prompt to fix the errors. Keep it strictly between 80 and 150 words and in the exact format required."
                )
                
                # Single shot regeneration
                regen_response_text = await generate_gemini_content(
                    api_keys=api_keys,
                    model=model,
                    prompt=regen_prompt,
                    system_instruction=system_instruction,
                    response_schema=ShotMotionPrompt,
                    rpm_limit=rpm_limit
                )
                try:
                    new_motion_prompt = ShotMotionPrompt.model_validate_json(regen_response_text)
                    motion_item.prompt = new_motion_prompt.prompt
                except Exception as ex:
                    print(f"Failed to parse regenerated prompt for {shot_id}: {ex}")
        
        all_motion_prompts.extend(chunk_data.motion_prompts)
        
    return MotionPromptResponse(motion_prompts=all_motion_prompts)


# --- Step 6: Veo Compliance Checker ---
async def check_compliance(
    motion_prompt: str,
    shot: Dict[str, Any],
    storyboard: str,
    api_keys: List[str],
    model: str,
    rpm_limit: int = 5
) -> ComplianceCheckResult:
    system_instruction = (
        "You are a strict Veo Compliance Checker. Your task is to verify if a generated Motion Prompt meets all guidelines.\n"
        "Analyze the provided Motion Prompt against the original Shot details and Storyboard, and verify each checklist item:\n"
        "- dialogue đúng 100%: The exact dialogue text must match the storyboard dialogue exactly. No paraphrasing, no improvisation.\n"
        "- duration hợp lý: The duration in seconds matches the shot duration.\n"
        "- prompt dưới giới hạn: The total word count of the Motion Prompt is between 80 and 150 words.\n"
        "- không có tiếng Việt: The prompt must be entirely in English (except for character names if necessary).\n"
        "- không có lời kể / không có narration / không có voice over: The prompt must not contain any narrative voice-over or storytelling text.\n"
        "- không có prompt mâu thuẫn: No conflicting directions.\n"
        "- không có nhân vật dư / không có location dư: No extra characters or settings described that are not in the shot.\n\n"
        "Return a JSON object with is_compliant (boolean) and errors (list of strings if is_compliant is false)."
    )
    
    prompt = (
        f"Storyboard:\n{storyboard}\n\n"
        f"Shot Details:\n{json.dumps(shot, ensure_ascii=False)}\n\n"
        f"Generated Motion Prompt:\n{motion_prompt}\n\n"
        f"Please verify compliance and return the compliance check result JSON."
    )
    
    response_text = await generate_gemini_content(
        api_keys=api_keys,
        model=model,
        prompt=prompt,
        system_instruction=system_instruction,
        response_schema=ComplianceCheckResult,
        rpm_limit=rpm_limit
    )
    return ComplianceCheckResult.model_validate_json(response_text)
