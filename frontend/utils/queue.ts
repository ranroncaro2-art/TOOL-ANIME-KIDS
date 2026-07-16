import { StepKey, PipelineStep } from "../components/PipelineProgress";
import { SavedProject, saveProject } from "./db";

const BACKEND_URL = "http://127.0.0.1:8000";

export interface ProjectTaskState {
  projectId: string;
  status: "idle" | "running" | "success" | "failed";
  activeStep: StepKey | null;
  isRunningAll: boolean;
  error?: string;
}

export interface SystemLog {
  timestamp: string;
  type: "info" | "success" | "error" | "running";
  message: string;
  projectId?: string;
}

type TaskListener = (projectId: string, state: ProjectTaskState, projectData?: any, steps?: any) => void;
type LogListener = (logs: SystemLog[]) => void;

class BackgroundQueueManager {
  private tasks: Map<string, ProjectTaskState> = new Map();
  private listeners: Set<TaskListener> = new Set();
  private activePromises: Map<string, Promise<any>> = new Map();
  private systemLogs: SystemLog[] = [];
  private logListeners: Set<LogListener> = new Set();

  subscribe(listener: TaskListener) {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  }

  private notify(projectId: string, state: ProjectTaskState, projectData?: any, steps?: any) {
    this.listeners.forEach(listener => {
      try {
        listener(projectId, state, projectData, steps);
      } catch (err) {
        console.error("Error in queue listener:", err);
      }
    });
  }

  subscribeLogs(listener: LogListener) {
    this.logListeners.add(listener);
    // Send current logs immediately
    listener(this.systemLogs);
    return () => {
      this.logListeners.delete(listener);
    };
  }

  private notifyLogs() {
    this.logListeners.forEach(listener => {
      try {
        listener([...this.systemLogs]);
      } catch (err) {
        console.error("Error in log listener:", err);
      }
    });
  }

  addLog(message: string, type: "info" | "success" | "error" | "running" = "info", projectId?: string) {
    const timestamp = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    const logEntry: SystemLog = { timestamp, type, message, projectId };
    this.systemLogs.push(logEntry);
    if (this.systemLogs.length > 200) {
      this.systemLogs.shift();
    }
    this.notifyLogs();
  }

  clearLogs() {
    this.systemLogs = [];
    this.notifyLogs();
  }

  getLogs(): SystemLog[] {
    return this.systemLogs;
  }

  getTaskState(projectId: string): ProjectTaskState {
    return this.tasks.get(projectId) || {
      projectId,
      status: "idle",
      activeStep: null,
      isRunningAll: false,
    };
  }

  isTaskRunning(projectId: string): boolean {
    const state = this.getTaskState(projectId);
    return state.status === "running";
  }

  // Run a single step in the background
  async runStep(params: {
    projectId: string;
    projectName: string;
    stepKey: StepKey;
    storyboard: string;
    projectData: any;
    steps: PipelineStep[];
    apiKeys: string[];
    selectedModel: string;
    rpmLimit: number;
    chunkSize: number;
  }) {
    const { projectId, stepKey } = params;
    const taskKey = `${projectId}_${stepKey}`;

    if (this.activePromises.has(taskKey)) {
      return; // Already running this step
    }

    const taskState: ProjectTaskState = {
      projectId,
      status: "running",
      activeStep: stepKey,
      isRunningAll: false,
    };
    this.tasks.set(projectId, taskState);
    this.notify(projectId, taskState);
    this.addLog(`Bắt đầu chạy bước "${stepKey}"...`, "running", projectId);

    const promise = this.executeStepApi(params)
      .then(async (updatedData) => {
        const updatedSteps = params.steps.map((s) =>
          s.key === stepKey ? { ...s, status: "success" as const, error: undefined } : s
        );

        // Save progress to IndexedDB
        const savedProj: SavedProject = {
          id: projectId,
          name: params.projectName,
          updatedAt: new Date().toISOString(),
          storyboard: params.storyboard,
          projectData: updatedData,
          steps: updatedSteps,
          model: params.selectedModel,
        };
        await saveProject(savedProj);
        this.addLog(`Bước "${stepKey}" hoàn thành thành công!`, "success", projectId);

        const finalState: ProjectTaskState = {
          projectId,
          status: "success",
          activeStep: null,
          isRunningAll: false,
        };
        this.tasks.delete(projectId);
        this.notify(projectId, finalState, updatedData, updatedSteps);
      })
      .catch(async (err: any) => {
        const updatedSteps = params.steps.map((s) =>
          s.key === stepKey ? { ...s, status: "failed" as const, error: err.message } : s
        );

        const savedProj: SavedProject = {
          id: projectId,
          name: params.projectName,
          updatedAt: new Date().toISOString(),
          storyboard: params.storyboard,
          projectData: params.projectData,
          steps: updatedSteps,
          model: params.selectedModel,
        };
        await saveProject(savedProj);
        this.addLog(`Bước "${stepKey}" thất bại: ${err.message}`, "error", projectId);

        const finalState: ProjectTaskState = {
          projectId,
          status: "failed",
          activeStep: null,
          isRunningAll: false,
          error: err.message,
        };
        this.tasks.set(projectId, finalState);
        this.notify(projectId, finalState, params.projectData, updatedSteps);
      })
      .finally(() => {
        this.activePromises.delete(taskKey);
      });

    this.activePromises.set(taskKey, promise);
  }

  // Run Combo 1 steps sequentially in the background (Story -> Shot Planner -> Keyframe Generator)
  async runCombo1(params: {
    projectId: string;
    projectName: string;
    storyboard: string;
    apiKeys: string[];
    selectedModel: string;
    rpmLimit: number;
    chunkSize: number;
    initialSteps: PipelineStep[];
    projectData: any;
  }) {
    const { projectId } = params;
    const taskKey = `${projectId}_combo1`;

    if (this.activePromises.has(taskKey)) {
      return; // Already running combo 1
    }

    const taskState: ProjectTaskState = {
      projectId,
      status: "running",
      activeStep: "story_analyzer",
      isRunningAll: false,
    };
    this.tasks.set(projectId, taskState);
    this.notify(projectId, taskState);
    this.addLog(`Bắt đầu chạy Combo 1 (Tạo Prompt) cho dự án "${params.projectName}"...`, "running", projectId);

    const promise = (async () => {
      let currentData = { ...params.projectData };
      let currentSteps = [...params.initialSteps];

      const runAndSave = async (stepKey: StepKey) => {
        this.tasks.set(projectId, {
          projectId,
          status: "running",
          activeStep: stepKey,
          isRunningAll: false,
        });
        currentSteps = currentSteps.map(s => s.key === stepKey ? { ...s, status: "running" as const } : s);
        this.notify(projectId, this.getTaskState(projectId), currentData, currentSteps);
        this.addLog(`Combo 1: Đang chạy bước "${stepKey}"...`, "running", projectId);

        const updatedData = await this.executeStepApi({
          ...params,
          stepKey,
          projectData: currentData,
          steps: currentSteps,
        });

        currentData = updatedData;
        if (stepKey === "character_extractor") {
          currentSteps = currentSteps.map(s => 
            ["character_extractor", "environment_extractor", "prop_extractor"].includes(s.key) 
              ? { ...s, status: "success" as const } 
              : s
          );
        } else {
          currentSteps = currentSteps.map(s => s.key === stepKey ? { ...s, status: "success" as const } : s);
        }
        this.addLog(`Combo 1: Bước "${stepKey}" hoàn thành thành công!`, "success", projectId);

        // Save progress to IndexedDB
        const savedProj: SavedProject = {
          id: projectId,
          name: params.projectName,
          updatedAt: new Date().toISOString(),
          storyboard: params.storyboard,
          projectData: currentData,
          steps: currentSteps,
          model: params.selectedModel,
        };
        await saveProject(savedProj);
      };

      try {
        await runAndSave("story_analyzer");
        await runAndSave("character_extractor");
        await runAndSave("shot_planner");
        await runAndSave("keyframe_generator");
        await runAndSave("motion_generator");

        const finalState: ProjectTaskState = {
          projectId,
          status: "success",
          activeStep: null,
          isRunningAll: false,
        };
        this.tasks.delete(projectId);
        this.notify(projectId, finalState, currentData, currentSteps);
        this.addLog(`Combo 1 hoàn thành toàn bộ các bước thành công!`, "success", projectId);
      } catch (err: any) {
        const runningStep = this.getTaskState(projectId).activeStep;
        if (runningStep) {
          currentSteps = currentSteps.map(s => s.key === runningStep ? { ...s, status: "failed" as const, error: err.message } : s);
        }

        const savedProj: SavedProject = {
          id: projectId,
          name: params.projectName,
          updatedAt: new Date().toISOString(),
          storyboard: params.storyboard,
          projectData: currentData,
          steps: currentSteps,
          model: params.selectedModel,
        };
        await saveProject(savedProj);

        const finalState: ProjectTaskState = {
          projectId,
          status: "failed",
          activeStep: null,
          isRunningAll: false,
          error: err.message,
        };
        this.tasks.set(projectId, finalState);
        this.notify(projectId, finalState, currentData, currentSteps);
        this.addLog(`Combo 1 thất bại tại bước "${runningStep || 'unknown'}": ${err.message}`, "error", projectId);
      }
    })().finally(() => {
      this.activePromises.delete(taskKey);
    });

    this.activePromises.set(taskKey, promise);
  }

  // Run Combo 2 steps sequentially in the background
  async runCombo2(params: {
    projectId: string;
    projectName: string;
    storyboard: string;
    apiKeys: string[];
    selectedModel: string;
    rpmLimit: number;
    chunkSize: number;
    initialSteps: PipelineStep[];
    projectData: any;
  }) {
    const { projectId } = params;
    const taskKey = `${projectId}_combo2`;

    if (this.activePromises.has(taskKey)) {
      return; // Already running combo 2
    }

    const taskState: ProjectTaskState = {
      projectId,
      status: "running",
      activeStep: "character_extractor",
      isRunningAll: false,
    };
    this.tasks.set(projectId, taskState);
    this.notify(projectId, taskState);
    this.addLog(`Bắt đầu chạy Combo 2 (Prompt + Ảnh tham chiếu) cho dự án "${params.projectName}"...`, "running", projectId);

    const promise = (async () => {
      let currentData = { ...params.projectData };
      let currentSteps = [...params.initialSteps];

      const runAndSave = async (stepKey: StepKey) => {
        this.tasks.set(projectId, {
          projectId,
          status: "running",
          activeStep: stepKey,
          isRunningAll: false,
        });
        currentSteps = currentSteps.map(s => s.key === stepKey ? { ...s, status: "running" as const } : s);
        this.notify(projectId, this.getTaskState(projectId), currentData, currentSteps);
        this.addLog(`Combo 2: Đang chạy bước "${stepKey}"...`, "running", projectId);

        const updatedData = await this.executeStepApi({
          ...params,
          stepKey,
          projectData: currentData,
          steps: currentSteps,
        });

        currentData = updatedData;
        currentSteps = currentSteps.map(s => s.key === stepKey ? { ...s, status: "success" as const } : s);
        this.addLog(`Combo 2: Bước "${stepKey}" hoàn thành thành công!`, "success", projectId);

        // Save progress to IndexedDB
        const savedProj: SavedProject = {
          id: projectId,
          name: params.projectName,
          updatedAt: new Date().toISOString(),
          storyboard: params.storyboard,
          projectData: currentData,
          steps: currentSteps,
          model: params.selectedModel,
        };
        await saveProject(savedProj);
      };

      try {
        // If story_analyzer has not run yet, run it first!
        if (currentData.scenes.length === 0) {
          await runAndSave("story_analyzer");
        }
        await runAndSave("character_extractor");
        await runAndSave("environment_extractor");
        await runAndSave("prop_extractor");

        const finalState: ProjectTaskState = {
          projectId,
          status: "success",
          activeStep: null,
          isRunningAll: false,
        };
        this.tasks.delete(projectId);
        this.notify(projectId, finalState, currentData, currentSteps);
        this.addLog(`Combo 2 hoàn thành toàn bộ các bước thành công!`, "success", projectId);
      } catch (err: any) {
        const runningStep = this.getTaskState(projectId).activeStep;
        if (runningStep) {
          currentSteps = currentSteps.map(s => s.key === runningStep ? { ...s, status: "failed" as const, error: err.message } : s);
        }

        const savedProj: SavedProject = {
          id: projectId,
          name: params.projectName,
          updatedAt: new Date().toISOString(),
          storyboard: params.storyboard,
          projectData: currentData,
          steps: currentSteps,
          model: params.selectedModel,
        };
        await saveProject(savedProj);

        const finalState: ProjectTaskState = {
          projectId,
          status: "failed",
          activeStep: null,
          isRunningAll: false,
          error: err.message,
        };
        this.tasks.set(projectId, finalState);
        this.notify(projectId, finalState, currentData, currentSteps);
        this.addLog(`Combo 2 thất bại tại bước "${runningStep || 'unknown'}": ${err.message}`, "error", projectId);
      }
    })().finally(() => {
      this.activePromises.delete(taskKey);
    });

    this.activePromises.set(taskKey, promise);
  }

  // Run all pipeline steps in sequence
  async runAllPipeline(params: {
    projectId: string;
    projectName: string;
    storyboard: string;
    apiKeys: string[];
    selectedModel: string;
    rpmLimit: number;
    chunkSize: number;
    initialSteps: PipelineStep[];
  }) {
    const { projectId } = params;
    const taskKey = `${projectId}_all`;

    if (this.activePromises.has(taskKey)) {
      return; // Already running full pipeline
    }

    const taskState: ProjectTaskState = {
      projectId,
      status: "running",
      activeStep: "story_analyzer",
      isRunningAll: true,
    };
    this.tasks.set(projectId, taskState);
    this.notify(projectId, taskState);
    this.addLog(`Bắt đầu chạy Combo 3 (Tự động toàn bộ) cho dự án "${params.projectName}"...`, "running", projectId);

    const promise = (async () => {
      let currentData = {
        scenes: [],
        characters: [],
        environments: [],
        props: [],
        shots: [],
        keyframes: [],
        motion_prompts: [],
      };
      
      let currentSteps: PipelineStep[] = params.initialSteps.map(s => ({ ...s, status: "idle" as const, error: undefined }));

      const runAndSave = async (stepKey: StepKey) => {
        // Update task state with active step
        this.tasks.set(projectId, {
          projectId,
          status: "running",
          activeStep: stepKey,
          isRunningAll: true,
        });
        currentSteps = currentSteps.map(s => s.key === stepKey ? { ...s, status: "running" as const } : s);
        this.notify(projectId, this.getTaskState(projectId), currentData, currentSteps);
        this.addLog(`Combo 3: Đang chạy bước "${stepKey}"...`, "running", projectId);

        const updatedData = await this.executeStepApi({
          ...params,
          stepKey,
          projectData: currentData,
          steps: currentSteps,
        });

        currentData = updatedData;
        currentSteps = currentSteps.map(s => s.key === stepKey ? { ...s, status: "success" as const } : s);
        this.addLog(`Combo 3: Bước "${stepKey}" hoàn thành thành công!`, "success", projectId);

        // Save progress to IndexedDB
        const savedProj: SavedProject = {
          id: projectId,
          name: params.projectName,
          updatedAt: new Date().toISOString(),
          storyboard: params.storyboard,
          projectData: currentData,
          steps: currentSteps,
          model: params.selectedModel,
        };
        await saveProject(savedProj);
      };

      try {
        // Step 1: Analyze Story
        await runAndSave("story_analyzer");
        // Step 2: Extract Characters
        await runAndSave("character_extractor");
        // Step 3: Extract Environments
        await runAndSave("environment_extractor");
        // Step 4: Extract Props
        await runAndSave("prop_extractor");
        // Step 5: Plan Shots
        await runAndSave("shot_planner");
        // Step 6: Generate Keyframes
        await runAndSave("keyframe_generator");
        // Step 7: Generate Motion Prompts
        await runAndSave("motion_generator");

        const finalState: ProjectTaskState = {
          projectId,
          status: "success",
          activeStep: null,
          isRunningAll: false,
        };
        this.tasks.delete(projectId);
        this.notify(projectId, finalState, currentData, currentSteps);
        this.addLog(`Combo 3 (Tự động toàn bộ) hoàn thành toàn bộ các bước thành công!`, "success", projectId);
      } catch (err: any) {
        const runningStep = this.getTaskState(projectId).activeStep;
        if (runningStep) {
          currentSteps = currentSteps.map(s => s.key === runningStep ? { ...s, status: "failed" as const, error: err.message } : s);
        }

        const savedProj: SavedProject = {
          id: projectId,
          name: params.projectName,
          updatedAt: new Date().toISOString(),
          storyboard: params.storyboard,
          projectData: currentData,
          steps: currentSteps,
          model: params.selectedModel,
        };
        await saveProject(savedProj);

        const finalState: ProjectTaskState = {
          projectId,
          status: "failed",
          activeStep: null,
          isRunningAll: false,
          error: err.message,
        };
        this.tasks.set(projectId, finalState);
        this.notify(projectId, finalState, currentData, currentSteps);
        this.addLog(`Combo 3 thất bại tại bước "${runningStep || 'unknown'}": ${err.message}`, "error", projectId);
      }
    })().finally(() => {
      this.activePromises.delete(taskKey);
    });

    this.activePromises.set(taskKey, promise);
  }

  private async executeStepApi(params: {
    stepKey: StepKey;
    storyboard: string;
    projectData: any;
    apiKeys: string[];
    selectedModel: string;
    rpmLimit: number;
    chunkSize: number;
    [key: string]: any;
  }) {
    const { stepKey, storyboard, projectData, apiKeys, selectedModel, rpmLimit, chunkSize } = params;
    
    let url = "";
    let bodyPayload: any = {};

    // Helper to map scenes to backend format
    const mapScenesToBackend = (scenesList: any[]) => {
      return (scenesList || []).map((scene: any) => ({
        scene_number: Number(scene.scene_id || 0),
        duration_seconds: Number(scene.duration_seconds || 5),
        characters: scene.characters || [],
        location: scene.setting || "",
        props: scene.props || [],
        action: scene.description || "",
        dialogue: (scene.dialogues || []).map((d: any) => ({
          character: d.character || "",
          speech: d.text || ""
        }))
      }));
    };

    // Helper to map characters to backend format
    const mapCharactersToBackend = (charList: any[]) => {
      return (charList || []).map((char: any) => ({
        name: char.name || "",
        description: char.description || "",
        prompt: char.turnaround_prompt || ""
      }));
    };

    // Helper to map environments to backend format
    const mapEnvironmentsToBackend = (envList: any[]) => {
      return (envList || []).map((env: any) => ({
        name: env.setting_name || "",
        prompt: env.reference_prompt || ""
      }));
    };

    // Helper to map props to backend format
    const mapPropsToBackend = (propList: any[]) => {
      return (propList || []).map((prop: any) => ({
        name: prop.prop_name || "",
        prompt: prop.reference_prompt || ""
      }));
    };

    // Helper to map shots to backend format
    const mapShotsToBackend = (shotList: any[]) => {
      return (shotList || []).map((shot: any) => ({
        shot_id: shot.shot_id || "",
        scene_number: Number(shot.scene_number || shot.scene_id || 0),
        duration_seconds: Number(shot.duration_seconds || 5),
        actions: shot.actions || "",
        characters: shot.characters || [],
        environment: shot.setting || shot.environment || "",
        props: shot.props || [],
        dialogue: (shot.dialogue || []).map((d: any) => ({
          character: d.character || "",
          speech: d.text || ""
        })),
        camera_movement: shot.camera_movement || "",
        shot_type: shot.framing || ""
      }));
    };

    // Helper to map keyframes to backend format
    const mapKeyframesToBackend = (keyframeList: any[]) => {
      return (keyframeList || []).map((k: any) => ({
        shot_id: k.shot_id || "",
        prompt: k.keyframe_image_prompt || ""
      }));
    };

    switch (stepKey) {
      case "story_analyzer":
        url = `${BACKEND_URL}/api/analyze-story`;
        bodyPayload = {
          storyboard,
          api_keys: apiKeys,
          model: selectedModel,
          rpm_limit: rpmLimit,
        };
        break;
      
      case "character_extractor":
      case "environment_extractor":
      case "prop_extractor":
        url = `${BACKEND_URL}/api/extract-assets`;
        bodyPayload = {
          storyboard,
          scenes: mapScenesToBackend(projectData.scenes),
          api_keys: apiKeys,
          model: selectedModel,
          rpm_limit: rpmLimit,
          chunk_size: chunkSize,
        };
        break;

      case "shot_planner":
        url = `${BACKEND_URL}/api/plan-shots`;
        bodyPayload = {
          scenes: mapScenesToBackend(projectData.scenes),
          characters: mapCharactersToBackend(projectData.characters),
          environments: mapEnvironmentsToBackend(projectData.environments),
          props: mapPropsToBackend(projectData.props),
          api_keys: apiKeys,
          model: selectedModel,
          rpm_limit: rpmLimit,
          chunk_size: chunkSize,
        };
        break;

      case "keyframe_generator":
        url = `${BACKEND_URL}/api/generate-keyframes`;
        bodyPayload = {
          shots: mapShotsToBackend(projectData.shots),
          characters: mapCharactersToBackend(projectData.characters),
          environments: mapEnvironmentsToBackend(projectData.environments),
          props: mapPropsToBackend(projectData.props),
          api_keys: apiKeys,
          model: selectedModel,
          rpm_limit: rpmLimit,
          chunk_size: chunkSize,
        };
        break;

      case "motion_generator":
        url = `${BACKEND_URL}/api/generate-motion`;
        bodyPayload = {
          shots: mapShotsToBackend(projectData.shots),
          keyframes: mapKeyframesToBackend(projectData.keyframes),
          api_keys: apiKeys,
          model: selectedModel,
          rpm_limit: rpmLimit,
          chunk_size: chunkSize,
        };
        break;
    }

    const response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(bodyPayload),
    });

    if (!response.ok) {
      const errorData = await response.json();
      let errorMsg = "";
      if (Array.isArray(errorData.detail)) {
        errorMsg = errorData.detail.map((err: any) => {
          const locStr = err.loc ? err.loc.join(" -> ") : "unknown";
          return `[${locStr}] ${err.msg}`;
        }).join("\n");
      } else {
        errorMsg = errorData.detail || `Request failed with status ${response.status}`;
      }
      throw new Error(errorMsg);
    }

    const responseData = await response.json();
    const updatedData = { ...projectData };

    switch (stepKey) {
      case "story_analyzer":
        updatedData.scenes = (responseData.scenes || []).map((scene: any) => ({
          scene_id: scene.scene_number,
          duration_seconds: scene.duration_seconds,
          characters: scene.characters,
          setting: scene.location,
          props: scene.props,
          description: scene.action,
          dialogues: scene.dialogue ? scene.dialogue.map((d: any) => ({
            character: d.character,
            text: d.speech
          })) : []
        }));
        break;

      case "character_extractor":
      case "environment_extractor":
      case "prop_extractor":
        updatedData.characters = (responseData.characters || []).map((char: any) => ({
          name: char.name,
          description: char.description,
          turnaround_prompt: char.prompt || char.turnaround_prompt || ""
        }));
        updatedData.environments = (responseData.environments || []).map((env: any) => ({
          setting_name: env.name || env.setting_name || "",
          reference_prompt: env.prompt || env.reference_prompt || ""
        }));
        updatedData.props = (responseData.props || []).map((prop: any) => ({
          prop_name: prop.name || prop.prop_name || "",
          reference_prompt: prop.prompt || prop.reference_prompt || ""
        }));
        break;

      case "shot_planner":
        updatedData.shots = (responseData.shots || []).map((shot: any) => ({
          shot_id: shot.shot_id,
          scene_id: shot.scene_number || shot.scene_id,
          scene_number: shot.scene_number || shot.scene_id,
          duration_seconds: shot.duration_seconds,
          actions: shot.actions || shot.action || "",
          characters: shot.characters || [],
          environment: shot.environment || "",
          props: shot.props || [],
          dialogue: shot.dialogue ? shot.dialogue.map((d: any) => ({
            character: d.character,
            text: d.speech
          })) : [],
          camera_movement: shot.camera_movement || "",
          framing: shot.shot_type || shot.framing || ""
        }));
        break;

      case "keyframe_generator":
        updatedData.keyframes = (responseData.keyframes || []).map((k: any) => ({
          shot_id: k.shot_id,
          keyframe_image_prompt: k.prompt || k.keyframe_image_prompt || ""
        }));
        break;

      case "motion_generator":
        updatedData.motion_prompts = (responseData.motion_prompts || []).map((m: any) => ({
          shot_id: m.shot_id,
          motion_description: m.prompt || m.motion_description || ""
        }));
        break;
    }

    return updatedData;
  }
}

export const queueManager = new BackgroundQueueManager();
