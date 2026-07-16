"use client";

import React, { useState, useEffect } from "react";

interface JsonEditorProps {
  title: string;
  data: any;
  onChangeData: (updatedData: any) => void;
  disabled?: boolean;
}

export default function JsonEditor({
  title,
  data,
  onChangeData,
  disabled = false,
}: JsonEditorProps) {
  const [textValue, setTextValue] = useState("");
  const [validationError, setValidationError] = useState<string | null>(null);
  const [copySuccess, setCopySuccess] = useState(false);

  useEffect(() => {
    if (data) {
      setTextValue(JSON.stringify(data, null, 2));
      setValidationError(null);
    } else {
      setTextValue("");
    }
  }, [data, title]); // Trigger update when data or filename tab changes

  const handleTextChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const val = e.target.value;
    setTextValue(val);
    
    if (!val.trim()) {
      setValidationError("JSON content cannot be empty.");
      return;
    }
    
    try {
      const parsed = JSON.parse(val);
      setValidationError(null);
      onChangeData(parsed); // Notify parent component with valid parsed object
    } catch (err: any) {
      setValidationError(`Syntax Error: ${err.message}`);
    }
  };

  const handleCopyToClipboard = async () => {
    try {
      await navigator.clipboard.writeText(textValue);
      setCopySuccess(true);
      setTimeout(() => setCopySuccess(false), 2000);
    } catch (err) {
      console.error("Failed to copy!", err);
    }
  };

  const handleDownload = () => {
    try {
      const blob = new Blob([textValue], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = title;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
    } catch (err) {
      console.error("Failed to download!", err);
    }
  };

  if (!data) {
    return (
      <div className="glass-panel" style={{ height: "100%", display: "flex", alignItems: "center", justifyContent: "center" }}>
        <p style={{ color: "var(--text-muted)", fontSize: "0.95rem" }}>
          No step output selected. Run a step or click on a completed step to inspect its JSON.
        </p>
      </div>
    );
  }

  return (
    <div className="glass-panel" style={{ height: "100%", display: "flex", flexDirection: "column", gap: "12px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div>
          <h3 style={{ fontSize: "1.1rem", fontFamily: "var(--font-mono)", color: "var(--accent-purple-light)", display: "flex", alignItems: "center", gap: "6px" }}>
            <span style={{ display: "inline-block", width: "8px", height: "8px", borderRadius: "50%", background: "var(--accent-purple)" }}></span>
            {title}
          </h3>
          <p style={{ fontSize: "0.75rem", color: "var(--text-secondary)" }}>
            Inspect or manually edit the raw JSON structure. Live validation enabled.
          </p>
        </div>

        <div style={{ display: "flex", gap: "8px" }}>
          <button
            type="button"
            className="btn-secondary"
            onClick={handleCopyToClipboard}
            style={{
              padding: "6px 12px",
              fontSize: "0.8rem",
              borderRadius: "var(--border-radius-sm)",
            }}
          >
            {copySuccess ? "Copied! ✓" : "Copy"}
          </button>

          <button
            type="button"
            className="btn-secondary"
            onClick={handleDownload}
            style={{
              padding: "6px 12px",
              fontSize: "0.8rem",
              borderRadius: "var(--border-radius-sm)",
            }}
          >
            Download
          </button>
        </div>
      </div>

      <div style={{ flexGrow: 1, position: "relative", minHeight: "350px" }}>
        <textarea
          value={textValue}
          onChange={handleTextChange}
          disabled={disabled}
          style={{
            width: "100%",
            height: "100%",
            background: "#05070c",
            border: `1px solid ${validationError ? "var(--danger)" : "var(--border-color)"}`,
            borderRadius: "var(--border-radius-md)",
            padding: "16px",
            color: "#e2e8f0",
            fontFamily: "var(--font-mono)",
            fontSize: "0.85rem",
            lineHeight: "1.5",
            resize: "none",
            outline: "none",
            transition: "var(--transition-smooth)",
          }}
          onFocus={(e) => {
            if (!validationError) {
              e.target.style.borderColor = "var(--accent-purple)";
            }
          }}
          onBlur={(e) => {
            if (!validationError) {
              e.target.style.borderColor = "var(--border-color)";
            }
          }}
        />
      </div>

      {validationError ? (
        <div
          style={{
            padding: "10px 14px",
            background: "var(--danger-glow)",
            border: "1px solid rgba(239, 68, 68, 0.2)",
            borderRadius: "var(--border-radius-sm)",
            color: "var(--danger)",
            fontSize: "0.8rem",
            fontFamily: "var(--font-mono)",
          }}
        >
          {validationError}
        </div>
      ) : (
        <div
          style={{
            padding: "6px 12px",
            background: "rgba(16, 185, 129, 0.05)",
            borderRadius: "var(--border-radius-sm)",
            color: "var(--success)",
            fontSize: "0.75rem",
            display: "flex",
            alignItems: "center",
            gap: "6px",
          }}
        >
          <span style={{ display: "inline-block", width: "5px", height: "5px", borderRadius: "50%", background: "var(--success)" }}></span>
          JSON syntax is valid and syncs in real-time.
        </div>
      )}
    </div>
  );
}
