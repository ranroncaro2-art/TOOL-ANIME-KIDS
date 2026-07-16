"use client";

import React from "react";

interface StoryboardInputProps {
  storyboard: string;
  onChangeStoryboard: (text: string) => void;
  onClear: () => void;
  disabled?: boolean;
}

const SAMPLE_STORYBOARD = `Scene 1 (6s)

Lisa đang đứng trước cổng trường.
Cô bé mỉm cười và vẫy tay.

Lisa:
"Hello everyone! My name is Lisa."

------------------------------------------------

Scene 2 (8s)

Tom chạy tới.

Tom:
"Hi Lisa!"

Lisa:
"Let's go to school!"

------------------------------------------------

Scene 3 (5s)

Hai bạn cùng đi vào trường.

------------------------------------------------

Scene 4 (8s)

Lisa nhìn thấy một bạn nhỏ đánh rơi hộp cơm.

Lisa:
"You dropped your lunch box."

Boy:
"Thank you!"`;

export default function StoryboardInput({
  storyboard,
  onChangeStoryboard,
  onClear,
  disabled = false,
}: StoryboardInputProps) {
  
  const handleLoadSample = () => {
    onChangeStoryboard(SAMPLE_STORYBOARD);
  };

  return (
    <div className="glass-panel" style={{ height: "100%", display: "flex", flexDirection: "column", gap: "16px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div>
          <h3 style={{ fontSize: "1.2rem", marginBottom: "4px", display: "flex", alignItems: "center", gap: "8px" }}>
            <span style={{ display: "inline-block", width: "10px", height: "10px", borderRadius: "50%", background: "var(--accent-cyan)" }}></span>
            Storyboard Text
          </h3>
          <p style={{ fontSize: "0.85rem", color: "var(--text-secondary)" }}>
            Write or paste your story sequence below.
          </p>
        </div>
        
        <div style={{ display: "flex", gap: "8px" }}>
          <button
            type="button"
            className="btn-secondary"
            onClick={handleLoadSample}
            disabled={disabled}
            style={{
              padding: "6px 12px",
              fontSize: "0.8rem",
              borderRadius: "var(--border-radius-sm)",
            }}
          >
            Load Sample
          </button>
          
          <button
            type="button"
            className="btn-secondary"
            onClick={onClear}
            disabled={disabled}
            style={{
              padding: "6px 12px",
              fontSize: "0.8rem",
              borderRadius: "var(--border-radius-sm)",
              color: "var(--danger)",
              borderColor: "rgba(239, 68, 68, 0.2)",
            }}
          >
            Clear
          </button>
        </div>
      </div>

      <div style={{ flexGrow: 1, position: "relative" }}>
        <textarea
          value={storyboard}
          onChange={(e) => onChangeStoryboard(e.target.value)}
          disabled={disabled}
          placeholder="Write your story here...
Example:
Scene 1 (6s)
Lisa is waving..."
          style={{
            width: "100%",
            height: "100%",
            minHeight: "300px",
            background: "var(--bg-secondary)",
            border: "1px solid var(--border-color)",
            borderRadius: "var(--border-radius-md)",
            padding: "16px",
            color: "var(--text-primary)",
            fontFamily: "var(--font-sans)",
            fontSize: "0.95rem",
            lineHeight: "1.6",
            resize: "none",
            outline: "none",
            transition: "var(--transition-smooth)",
          }}
          onFocus={(e) => (e.target.style.borderColor = "var(--accent-cyan)")}
          onBlur={(e) => (e.target.style.borderColor = "var(--border-color)")}
        />
      </div>
    </div>
  );
}
