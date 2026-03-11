from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Iterator, List, Tuple

import cv2
import numpy as np
import supervision as sv
from inference import get_model
from tqdm import tqdm

DEFAULT_INPUT_VIDEO = "raw_videos/game7_2016_finals.mp4"
DEFAULT_OUT_DIR = "outputs"
DEFAULT_START_SEC = 0.0
DEFAULT_DURATION_SEC = 30.0
DEFAULT_EVERY_N = 1

PLAYER_DETECTION_MODEL_ID = "basketball-player-detection-3-ycjdo/4"
PLAYER_DETECTION_MODEL_CONFIDENCE = 0.4
PLAYER_DETECTION_MODEL_IOU_THRESHOLD = 0.9
PLAYER_CLASS_IDS = np.array([3, 4, 5, 6, 7], dtype=int)

COLOR = sv.ColorPalette.from_hex(
    [
        "#ffff00",
        "#ff9b00",
        "#ff66ff",
        "#3399ff",
        "#ff66b2",
        "#ff8080",
        "#b266ff",
        "#9999ff",
        "#66ffff",
        "#33ff99",
        "#66ff66",
        "#99ff00",
    ]
)


class Detector:
    def __init__(
        self,
        model_id: str = PLAYER_DETECTION_MODEL_ID,
        confidence: float = PLAYER_DETECTION_MODEL_CONFIDENCE,
        iou_threshold: float = PLAYER_DETECTION_MODEL_IOU_THRESHOLD,
    ) -> None:
        if not os.getenv("ROBOFLOW_API_KEY"):
            raise RuntimeError(
                "ROBOFLOW_API_KEY is not set. Export it before running, e.g.:\n"
                "export ROBOFLOW_API_KEY=\"<your_key>\""
            )

        self.model = get_model(model_id=model_id)
        self.confidence = confidence
        self.iou_threshold = iou_threshold

    def infer(self, frame: np.ndarray) -> sv.Detections:
        result = self.model.infer(
            frame,
            confidence=self.confidence,
            iou_threshold=self.iou_threshold,
        )[0]
        detections = sv.Detections.from_inference(result)

        # The notebook uses both all-class and player-only views. This script
        # follows the player-focused flow and keeps player-related class IDs.
        if len(detections) > 0 and detections.class_id is not None:
            detections = detections[np.isin(detections.class_id, PLAYER_CLASS_IDS)]

        return detections


def open_video(
    input_path: Path, start_sec: float, duration_sec: float
) -> Tuple[cv2.VideoCapture, float, int, int, int, int]:
    if start_sec < 0:
        raise ValueError("--start_sec must be >= 0.")
    if duration_sec <= 0:
        raise ValueError("--duration_sec must be > 0.")

    capture = cv2.VideoCapture(str(input_path))
    if not capture.isOpened():
        raise RuntimeError(f"Could not open video: {input_path}")

    fps = float(capture.get(cv2.CAP_PROP_FPS))
    if fps <= 0:
        capture.release()
        raise RuntimeError("Could not read a valid FPS from the input video.")

    total_frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))

    start_frame = int(start_sec * fps)
    if start_frame >= total_frames:
        capture.release()
        raise ValueError(
            f"--start_sec ({start_sec}) is beyond video duration "
            f"({total_frames / fps:.2f}s)."
        )

    clip_frames = max(1, int(duration_sec * fps))
    end_frame = min(total_frames, start_frame + clip_frames)
    capture.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
    return capture, fps, width, height, start_frame, end_frame


def iter_frames(
    capture: cv2.VideoCapture, start_frame: int, end_frame: int
) -> Iterator[Tuple[int, np.ndarray]]:
    frame_index = start_frame
    while frame_index < end_frame:
        ok, frame = capture.read()
        if not ok:
            break
        yield frame_index, frame
        frame_index += 1


def draw_overlay(
    frame: np.ndarray,
    frame_index: int,
    time_sec: float,
    every_n: int,
    ran_inference: bool,
) -> np.ndarray:
    state = "infer" if ran_inference else f"reuse(last, every_n={every_n})"
    text = f"frame={frame_index} | t={time_sec:.2f}s | {state}"
    cv2.rectangle(frame, (10, 10), (700, 48), (0, 0, 0), thickness=-1)
    cv2.putText(
        frame,
        text,
        (16, 36),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.7,
        (255, 255, 255),
        2,
        cv2.LINE_AA,
    )
    return frame


def draw_detections(
    frame: np.ndarray,
    detections: sv.Detections,
    box_annotator: sv.BoxAnnotator,
    label_annotator: sv.LabelAnnotator,
) -> np.ndarray:
    annotated_frame = frame.copy()
    annotated_frame = box_annotator.annotate(
        scene=annotated_frame,
        detections=detections,
    )
    annotated_frame = label_annotator.annotate(
        scene=annotated_frame,
        detections=detections,
    )
    return annotated_frame


def to_json_detections(detections: sv.Detections) -> List[dict]:
    class_names = None
    if detections.data is not None and "class_name" in detections.data:
        class_names = detections.data["class_name"]

    records: List[dict] = []
    for i, xyxy in enumerate(detections.xyxy):
        if class_names is not None:
            label = str(class_names[i])
        elif detections.class_id is not None:
            label = str(int(detections.class_id[i]))
        else:
            label = "unknown"

        confidence = (
            float(detections.confidence[i])
            if detections.confidence is not None
            else 0.0
        )
        bbox_xyxy = [float(v) for v in xyxy.tolist()]

        records.append(
            {
                "label": label,
                "conf": confidence,
                "bbox_xyxy": bbox_xyxy,
            }
        )
    return records


def main() -> None:
    parser = argparse.ArgumentParser(description="Notebook-faithful basketball detection pipeline.")
    parser.add_argument("--input", type=str, default=DEFAULT_INPUT_VIDEO)
    parser.add_argument("--start_sec", type=float, default=DEFAULT_START_SEC)
    parser.add_argument("--duration_sec", type=float, default=DEFAULT_DURATION_SEC)
    parser.add_argument("--out_dir", type=str, default=DEFAULT_OUT_DIR)
    parser.add_argument("--every_n", type=int, default=DEFAULT_EVERY_N)
    args = parser.parse_args()

    if args.every_n < 1:
        raise ValueError("--every_n must be >= 1.")

    input_path = Path(args.input)
    if not input_path.exists():
        raise FileNotFoundError(f"Input video not found: {input_path}")

    out_dir = Path(args.out_dir)
    frames_dir = out_dir / "frames"
    out_dir.mkdir(parents=True, exist_ok=True)
    frames_dir.mkdir(parents=True, exist_ok=True)

    annotated_video_path = out_dir / f"{input_path.stem}_annotated.mp4"
    detections_jsonl_path = out_dir / "detections.jsonl"

    capture, fps, width, height, start_frame, end_frame = open_video(
        input_path=input_path,
        start_sec=args.start_sec,
        duration_sec=args.duration_sec,
    )

    clip_frame_count = max(0, end_frame - start_frame)
    sample_count = min(5, clip_frame_count)
    sample_indices = (
        set(np.linspace(0, clip_frame_count - 1, num=sample_count, dtype=int).tolist())
        if sample_count > 0
        else set()
    )

    writer = cv2.VideoWriter(
        str(annotated_video_path),
        cv2.VideoWriter_fourcc(*"mp4v"),
        fps,
        (width, height),
    )
    if not writer.isOpened():
        capture.release()
        raise RuntimeError(f"Could not open output video writer: {annotated_video_path}")

    detector = Detector()
    box_annotator = sv.BoxAnnotator(color=COLOR, thickness=2)
    label_annotator = sv.LabelAnnotator(color=COLOR, text_color=sv.Color.BLACK)

    processed_frames = 0
    inference_runs = 0
    saved_frame_paths: List[Path] = []
    last_detections: sv.Detections | None = None

    start_time = time.perf_counter()
    try:
        with detections_jsonl_path.open("w", encoding="utf-8") as jsonl_file:
            for frame_index, frame in tqdm(
                iter_frames(capture, start_frame, end_frame),
                total=clip_frame_count,
                desc="Processing video",
            ):
                relative_idx = processed_frames
                run_inference = (
                    last_detections is None or (relative_idx % args.every_n == 0)
                )

                if run_inference:
                    last_detections = detector.infer(frame)
                    inference_runs += 1

                if last_detections is None:
                    raise RuntimeError("Internal error: detections cache is empty.")
                detections = last_detections
                time_sec = frame_index / fps

                annotated_frame = draw_detections(
                    frame=frame,
                    detections=detections,
                    box_annotator=box_annotator,
                    label_annotator=label_annotator,
                )
                annotated_frame = draw_overlay(
                    frame=annotated_frame,
                    frame_index=frame_index,
                    time_sec=time_sec,
                    every_n=args.every_n,
                    ran_inference=run_inference,
                )
                writer.write(annotated_frame)

                if relative_idx in sample_indices:
                    frame_path = frames_dir / f"{input_path.stem}_frame_{frame_index:06d}.png"
                    cv2.imwrite(str(frame_path), annotated_frame)
                    saved_frame_paths.append(frame_path)

                payload = {
                    "frame_index": int(frame_index),
                    "time_sec": float(time_sec),
                    "detections": to_json_detections(detections),
                }
                jsonl_file.write(json.dumps(payload) + "\n")
                processed_frames += 1
    finally:
        capture.release()
        writer.release()

    elapsed_sec = max(time.perf_counter() - start_time, 1e-6)
    effective_fps = processed_frames / elapsed_sec

    print(f"Frames processed: {processed_frames}")
    print(f"Inference runs: {inference_runs} (every_n={args.every_n})")
    print(f"Effective FPS: {effective_fps:.2f}")
    print(f"Annotated video: {annotated_video_path}")
    print(f"Annotated frames ({len(saved_frame_paths)}): {frames_dir}")
    print(f"Detections JSONL: {detections_jsonl_path}")


if __name__ == "__main__":
    main()
