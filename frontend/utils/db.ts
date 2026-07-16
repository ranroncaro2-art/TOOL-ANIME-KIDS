// IndexedDB Helper for AI Kids Animation Studio

const DB_NAME = "AIKidsAnimationStudioDB";
const DB_VERSION = 1;
const STORE_NAME = "projects";

export interface SavedProject {
  id: string;          // "active" or timestamp/UUID
  name: string;        // Human-readable name
  updatedAt: string;   // ISO timestamp
  storyboard: string;  // Storyboard draft text
  projectData: {
    scenes: any[];
    characters: any[];
    environments: any[];
    props: any[];
    shots: any[];
    keyframes: any[];
    motion_prompts: any[];
  };
  steps: {
    key: string;
    label: string;
    description: string;
    status: "idle" | "running" | "success" | "failed";
    error?: string;
  }[];
  model?: string;
  selectedStyle?: string;
  styleDescription?: string;
  workflowMode?: string;
}

export function initDB(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    if (typeof window === "undefined") {
      reject(new Error("IndexedDB is only available in the browser."));
      return;
    }

    const request = indexedDB.open(DB_NAME, DB_VERSION);

    request.onerror = () => {
      reject(new Error("Failed to open IndexedDB."));
    };

    request.onsuccess = (event: any) => {
      resolve(event.target.result);
    };

    request.onupgradeneeded = (event: any) => {
      const db = event.target.result;
      if (!db.objectStoreNames.contains(STORE_NAME)) {
        db.createObjectStore(STORE_NAME, { keyPath: "id" });
      }
    };
  });
}

export async function saveProject(project: SavedProject): Promise<void> {
  const db = await initDB();
  return new Promise((resolve, reject) => {
    const transaction = db.transaction([STORE_NAME], "readwrite");
    const store = transaction.objectStore(STORE_NAME);
    const request = store.put(project);

    request.onsuccess = () => {
      resolve();
    };

    request.onerror = () => {
      reject(new Error("Failed to save project to IndexedDB."));
    };
  });
}

export async function getProject(id: string): Promise<SavedProject | null> {
  const db = await initDB();
  return new Promise((resolve, reject) => {
    const transaction = db.transaction([STORE_NAME], "readonly");
    const store = transaction.objectStore(STORE_NAME);
    const request = store.get(id);

    request.onsuccess = (event: any) => {
      resolve(event.target.result || null);
    };

    request.onerror = () => {
      reject(new Error(`Failed to retrieve project "${id}" from IndexedDB.`));
    };
  });
}

export async function deleteProject(id: string): Promise<void> {
  const db = await initDB();
  return new Promise((resolve, reject) => {
    const transaction = db.transaction([STORE_NAME], "readwrite");
    const store = transaction.objectStore(STORE_NAME);
    const request = store.delete(id);

    request.onsuccess = () => {
      resolve();
    };

    request.onerror = () => {
      reject(new Error(`Failed to delete project "${id}" from IndexedDB.`));
    };
  });
}

export interface ProjectMetadata {
  id: string;
  name: string;
  updatedAt: string;
  model?: string;
}

export async function listProjects(): Promise<ProjectMetadata[]> {
  const db = await initDB();
  return new Promise((resolve, reject) => {
    const transaction = db.transaction([STORE_NAME], "readonly");
    const store = transaction.objectStore(STORE_NAME);
    const request = store.openCursor();
    const list: ProjectMetadata[] = [];

    request.onsuccess = (event: any) => {
      const cursor = event.target.result;
      if (cursor) {
        // Exclude the active workspace from list view to keep it clean
        if (cursor.value.id !== "active") {
          list.push({
            id: cursor.value.id,
            name: cursor.value.name,
            updatedAt: cursor.value.updatedAt,
            model: cursor.value.model,
          });
        }
        cursor.continue();
      } else {
        // Sort by updatedAt descending (newest first)
        list.sort((a, b) => new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime());
        resolve(list);
      }
    };

    request.onerror = () => {
      reject(new Error("Failed to list projects from IndexedDB."));
    };
  });
}
