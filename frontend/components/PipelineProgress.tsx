"use client";

import React from "react";

export type StepKey =
  | "story_analyzer"
  | "character_extractor"
  | "environment_extractor"
  | "prop_extractor"
  | "shot_planner"
  | "keyframe_generator"
  | "motion_generator";

export interface PipelineStep {
  key: StepKey;
  label: string;
  description: string;
  status: "idle" | "running" | "success" | "failed";
  error?: string;
}

interface PipelineProgressProps {
  steps: PipelineStep[];
  activeStep: StepKey | null;
  onRunStep: (stepKey: StepKey) => void;
  onViewStepResult: (stepKey: StepKey) => void;
  selectedStep: StepKey | null;
  disabled?: boolean;
}

export default function PipelineProgress({
  steps,
  activeStep,
  onRunStep,
  onViewStepResult,
  selectedStep,
  disabled = false,
}: PipelineProgressProps) {
  
  const getStatusColor = (status: PipelineStep["status"]) => {
    switch (status) {
      case "running":
        return "var(--accent-cyan)";
      case "success":
        return "var(--success)";
      case "failed":
        return "var(--danger)";
      default:
        return "var(--text-muted)";
    }
  };

  const getStatusLabel = (status: PipelineStep["status"]) => {
    switch (status) {
      case "running":
        return "Processing...";
      case "success":
        return "Complete";
      case "failed":
        return "Failed";
      default:
        return "Idle";
    }
  };

  return (
    <div className="glass-panel" style={{ height: "100%", display: "flex", flexDirection: "column", gap: "16px" }}>
      <div>
        <h3 style={{ fontSize: "1.2rem", marginBottom: "4px", display: "flex", alignItems: "center", gap: "8px" }}>
          <span style={{ display: "inline-block", width: "10px", height: "10px", borderRadius: "50%", background: "linear-gradient(135deg, var(--accent-purple), var(--accent-cyan))" }}></span>
          Pipeline Progress Flow
        </h3>
        <p style={{ fontSize: "0.85rem", color: "var(--text-secondary)" }}>
          Run steps sequentially or click them to inspect their intermediate data structures.
        </p>
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: "12px", flexGrow: 1, overflowY: "auto", paddingRight: "4px" }}>
        {steps.map((step, index) => {
          const isSelected = selectedStep === step.key;
          const isCurrentActive = activeStep === step.key;
          const statusColor = getStatusColor(step.status);
          
          return (
            <div
              key={step.key}
              onClick={() => {
                if (step.status === "success" || step.status === "failed") {
                  onViewStepResult(step.key);
                }
              }}
              style={{
                display: "flex",
                flexDirection: "column",
                gap: "8px",
                padding: "12px 16px",
                borderRadius: "var(--border-radius-md)",
                background: isSelected
                  ? "rgba(139, 92, 246, 0.08)"
                  : "rgba(255, 255, 255, 0.02)",
                border: isSelected
                  ? "1px solid var(--accent-purple)"
                  : isCurrentActive
                  ? "1px solid var(--accent-cyan)"
                  : "1px solid var(--border-color)",
                cursor: step.status === "success" || step.status === "failed" ? "pointer" : "default",
                transition: "var(--transition-smooth)",
                boxShadow: isCurrentActive ? "0 0 15px rgba(6, 182, 212, 0.15)" : "none",
                position: "relative",
              }}
            >
              {/* Connecting line between cards */}
              {index < steps.length - 1 && (
                <div
                  style={{
                    position: "absolute",
                    left: "24px",
                    bottom: "-14px",
                    width: "2px",
                    height: "14px",
                    background: step.status === "success" ? "var(--success)" : "var(--border-color)",
                    zIndex: 1,
                  }}
                />
              )}

              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "12px" }}>
                <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                  <div
                    style={{
                      width: "24px",
                      height: "24px",
                      borderRadius: "50%",
                      background: step.status === "success" ? "var(--success-glow)" : "rgba(255, 255, 255, 0.05)",
                      border: `1px solid ${statusColor}`,
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      fontSize: "0.75rem",
                      fontWeight: "bold",
                      color: step.status === "success" ? "var(--success)" : statusColor,
                    }}
                  >
                    {step.status === "success" ? "✓" : index + 1}
                  </div>

                  <div>
                    <h4 style={{ fontSize: "0.95rem", fontWeight: 600 }}>{step.label}</h4>
                    <p style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>{step.description}</p>
                  </div>
                </div>

                <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                  <span
                    style={{
                      fontSize: "0.75rem",
                      padding: "4px 8px",
                      borderRadius: "10px",
                      background:
                        step.status === "running"
                          ? "var(--accent-cyan-glow)"
                          : step.status === "success"
                          ? "rgba(16, 185, 129, 0.1)"
                          : step.status === "failed"
                          ? "rgba(239, 68, 68, 0.1)"
                          : "rgba(255,255,255,0.04)",
                      color: statusColor,
                      fontWeight: 600,
                    }}
                  >
                    {getStatusLabel(step.status)}
                  </span>

                  <button
                    type="button"
                    className="btn-secondary"
                    onClick={(e) => {
                      e.stopPropagation(); // Avoid selecting card
                      onRunStep(step.key);
                    }}
                    disabled={disabled || activeStep !== null}
                    style={{
                      padding: "4px 10px",
                      fontSize: "0.75rem",
                      borderRadius: "4px",
                      background: "var(--bg-tertiary)",
                    }}
                  >
                    Run
                  </button>
                </div>
              </div>

              {step.error && (
                <div
                  style={{
                    marginTop: "4px",
                    padding: "8px 12px",
                    background: "var(--danger-glow)",
                    border: "1px solid rgba(239, 68, 68, 0.2)",
                    borderRadius: "4px",
                    fontSize: "0.75rem",
                    color: "var(--danger)",
                    wordBreak: "break-word",
                  }}
                >
                  <strong>Error:</strong> {step.error}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
