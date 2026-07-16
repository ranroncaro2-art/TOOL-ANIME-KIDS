from pydantic import BaseModel, Field
from typing import List, Optional

# --- Shared & Base Schemas ---

class DialogueItem(BaseModel):
    character: str = Field(description="The name of the character speaking.")
    speech: str = Field(description="The dialogue text spoken by the character.")

# --- Step 1: Story Analyzer ---

class SceneAnalysis(BaseModel):
    scene_number: int = Field(description="The sequential number of the scene.")
    duration_seconds: int = Field(description="Estimated duration of the scene in seconds.")
    characters: List[str] = Field(description="List of characters appearing in this scene.")
    location: str = Field(description="The location or background environment where this scene takes place.")
    props: List[str] = Field(description="List of physical objects/props used in this scene.")
    action: str = Field(description="Description of the visual actions and events in this scene.")
    dialogue: List[DialogueItem] = Field(description="Chronological dialogue exchange in this scene.")

class StoryAnalysisResponse(BaseModel):
    scenes: List[SceneAnalysis] = Field(description="List of analyzed scenes in chronological order.")

# --- Steps 3, 4, 5: Asset Extractors ---

class CharacterAsset(BaseModel):
    name: str = Field(description="The name of the character.")
    description: str = Field(description="Short description of the character based on the storyboard (e.g., age, clothing, personality).")
    prompt: str = Field(description="A highly detailed Pixar-style turnaround prompt for generating reference images. Must specify: turnarounds (front, 45-degree, side views), Pixar 3D stylized style, white background, no text, no shadows.")

class CharacterExtractorResponse(BaseModel):
    characters: List[CharacterAsset] = Field(description="List of all unique characters extracted from the storyboard with reference prompts.")

class EnvironmentAsset(BaseModel):
    name: str = Field(description="The name or description of the location.")
    prompt: str = Field(description="A highly detailed Pixar-style reference image prompt. Must specify: empty room/area, wide angle, Pixar 3D stylized, consistent lighting, no characters, no text.")

class EnvironmentExtractorResponse(BaseModel):
    environments: List[EnvironmentAsset] = Field(description="List of all unique environment environments extracted from the storyboard with reference prompts.")

class PropAsset(BaseModel):
    name: str = Field(description="The name of the prop object.")
    prompt: str = Field(description="A detailed Pixar-style reference image prompt for this prop. Must specify: centered, closed/open state, Pixar 3D stylized, white background, reference image, no text.")

class PropExtractorResponse(BaseModel):
    props: List[PropAsset] = Field(description="List of all unique props extracted from the storyboard with reference prompts.")

# --- Step 6: Shot Planner ---

class Shot(BaseModel):
    shot_id: str = Field(description="Identifier for the shot, formatted like Shot001, Shot002, etc.")
    scene_number: int = Field(description="The scene number this shot belongs to.")
    duration_seconds: int = Field(description="Duration of this shot in seconds.")
    actions: str = Field(default="", description="The specific character actions, movements, or visual events happening in this shot.")
    characters: List[str] = Field(description="Characters visible in this shot.")
    environment: str = Field(description="The environment/location for this shot.")
    props: List[str] = Field(description="Props present in this shot.")
    dialogue: List[DialogueItem] = Field(description="Dialogue spoken during this shot.")
    camera_movement: str = Field(description="Camera movement description (e.g., Static, Pan Left, Zoom In, Tilt Up).")
    shot_type: str = Field(description="Shot type composition (e.g., Close Up, Medium Shot, Wide Shot, Extreme Close Up).")

class ShotPlannerResponse(BaseModel):
    shots: List[Shot] = Field(description="List of planned shots for the episode.")

# --- Step 7: Keyframe Prompt Generator ---

class ShotKeyframePrompt(BaseModel):
    shot_id: str = Field(description="The ID of the shot (e.g. Shot001).")
    prompt: str = Field(description="A detailed image-to-video keyframe reference prompt combining characters, environments, props, cameras, and actions. Pixar-quality stylized 3D, cinematic composition, reference keyframe, no motion blur, no text.")

class KeyframePromptResponse(BaseModel):
    keyframes: List[ShotKeyframePrompt] = Field(description="Keyframe reference image generation prompts for all shots.")

# --- Step 8: Motion Prompt Generator ---

class ShotMotionPrompt(BaseModel):
    shot_id: str = Field(description="The ID of the shot (e.g. Shot001).")
    prompt: str = Field(description="Veo 3 motion prompt. Incorporate shot action, dialog, natural facial expression, English lip-sync, blinking, breathing, body language, camera description, lighting and style, no subtitles, no text.")

class MotionPromptResponse(BaseModel):
    motion_prompts: List[ShotMotionPrompt] = Field(description="Veo 3 motion and video prompts for all shots.")

class AssetsResponse(BaseModel):
    characters: List[CharacterAsset] = Field(description="Unique list of characters with details and turnaround prompts.")
    environments: List[EnvironmentAsset] = Field(description="Unique list of locations with reference prompts.")
    props: List[PropAsset] = Field(description="Unique list of prop objects with reference prompts.")

# --- API Request/Response schemas ---

class PipelineRequest(BaseModel):
    storyboard: str = Field(description="The raw text storyboard input.")
    api_keys: List[str] = Field(description="List of Gemini API keys for processing.")
    model: str = Field(default="gemini-2.5-flash", description="The Gemini model to use.")
    rpm_limit: int = Field(default=5, description="Requests per minute rate limit.")
    chunk_size: int = Field(default=3, description="Chunk size for list splitting.")
