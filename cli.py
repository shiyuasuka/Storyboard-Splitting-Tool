from __future__ import annotations

import argparse
import json
from pathlib import Path

import httpx


def main() -> None:
    parser = argparse.ArgumentParser(description="CLI for Auto Quasi-Storyboard Manga Drama Platform")
    parser.add_argument("--host", default="http://127.0.0.1:8000")
    sub = parser.add_subparsers(dest="command", required=True)

    ingest_text = sub.add_parser("ingest-text", help="ingest novel raw text")
    ingest_text.add_argument("--title", default="未命名小说")
    ingest_text.add_argument("--content", required=True)
    ingest_text.add_argument("--project-id")

    ingest_file = sub.add_parser("ingest-file", help="ingest novel from txt/md file")
    ingest_file.add_argument("--file", required=True)
    ingest_file.add_argument("--title")
    ingest_file.add_argument("--project-id")

    gen = sub.add_parser("generate", help="generate batch samples")
    gen.add_argument("--topic")
    gen.add_argument("--project-id", required=True)
    gen.add_argument("--genre", default="都市悬疑")
    gen.add_argument("--emotion", default="紧张")
    gen.add_argument("--conflict-level", type=int, default=8)
    gen.add_argument("--rhythm-speed", type=int, default=7)
    gen.add_argument("--episodes", type=int, default=5)
    gen.add_argument("--episode-duration", type=int, default=120)
    gen.add_argument("--curve-style", default="递进")
    gen.add_argument("--batch-size", type=int, default=5)

    exp = sub.add_parser("export", help="export project")
    exp.add_argument("--project-id", required=True)
    exp.add_argument("--format", choices=["bundle", "internal_json", "arena_txt", "json", "markdown"], default="bundle")

    args = parser.parse_args()

    if args.command == "ingest-text":
        payload = {
            "project_id": args.project_id,
            "title": args.title,
            "content": args.content,
        }
        response = httpx.post(f"{args.host}/novel/ingest_text", json=payload, timeout=120)
        response.raise_for_status()
        print(json.dumps(response.json(), ensure_ascii=False, indent=2))
        return

    if args.command == "ingest-file":
        fp = Path(args.file)
        text = ""
        raw = fp.read_bytes()
        for enc in ("utf-8", "utf-8-sig", "gbk"):
            try:
                text = raw.decode(enc)
                break
            except Exception:
                continue
        if not text:
            raise RuntimeError("file decode failed; use utf-8/gbk txt or md")

        payload = {
            "project_id": args.project_id,
            "title": args.title or fp.stem,
            "content": text,
        }
        response = httpx.post(f"{args.host}/novel/ingest_text", json=payload, timeout=120)
        response.raise_for_status()
        print(json.dumps(response.json(), ensure_ascii=False, indent=2))
        return

    if args.command == "generate":
        payload = {
            "topic": args.topic,
            "project_id": args.project_id,
            "constraints": {
                "genre": args.genre,
                "emotion": args.emotion,
                "conflict_level": args.conflict_level,
                "rhythm_speed": args.rhythm_speed,
                "episodes": args.episodes,
                "episode_duration": args.episode_duration,
                "intensity_curve_style": args.curve_style,
            },
            "batch_size": args.batch_size,
            "use_llm": True,
            "prompt_version": "v1.0.0",
            "strategy_version": "v1.0.0",
        }
        response = httpx.post(f"{args.host}/generate_batch", json=payload, timeout=240)
        response.raise_for_status()
        print(json.dumps(response.json(), ensure_ascii=False, indent=2))
        return

    if args.command == "export":
        response = httpx.get(f"{args.host}/export/{args.project_id}", params={"format": args.format}, timeout=120)
        response.raise_for_status()
        print(json.dumps(response.json(), ensure_ascii=False, indent=2))
        return


if __name__ == "__main__":
    main()
