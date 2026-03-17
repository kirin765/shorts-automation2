from __future__ import annotations

import argparse
import shutil
import sys
import time
from datetime import date
from pathlib import Path
from typing import Optional

from . import providers, runner
from .config import ENV_SENTINEL, Config, load_config
from .models import DraftJob, RenderJob, load_draft_job, load_topics_text, make_draft_jobs, slugify, write_render_job
from .output import one_line


def generate_topics_to_file(
    config: Config,
    *,
    out_path: Path,
    history_path: Path,
    count: int,
    language: str,
    niche: str,
    style: str,
) -> list[str]:
    existing = []
    if history_path.exists():
        existing = load_topics_text(history_path)
    topics = providers.generate_topics(
        config,
        count=count,
        language=language,
        niche=niche,
        style=style,
        existing_topics=existing,
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    history_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(topics) + "\n", encoding="utf-8")
    with history_path.open("a", encoding="utf-8") as handle:
        for topic in topics:
            handle.write(topic + "\n")
    print("Wrote %d topics to %s" % (len(topics), out_path))
    return topics


def draft_jobs_to_queue(
    config: Config,
    *,
    draft_jobs: list[DraftJob],
    queue_dir: Path,
) -> list[Path]:
    queue_dir.mkdir(parents=True, exist_ok=True)
    today = date.today().strftime("%Y-%m-%d")
    created = []
    for index, draft_job in enumerate(draft_jobs, start=1):
        render_job = providers.generate_render_job(config, draft_job)
        path = queue_dir / ("%s_%s_%02d.json" % (today, slugify(draft_job.topic)[:40], index))
        write_render_job(path, render_job)
        created.append(path)
    print("Enqueued:")
    for path in created:
        print("- %s" % path)
    return created


def run_queue(
    config: Config,
    *,
    queue_dir: Path,
    done_dir: Path,
    failed_dir: Path,
    retries: int,
    sleep_s: float,
    no_upload: bool,
    force_upload: bool,
) -> int:
    queue_dir.mkdir(parents=True, exist_ok=True)
    done_dir.mkdir(parents=True, exist_ok=True)
    failed_dir.mkdir(parents=True, exist_ok=True)
    jobs = sorted(queue_dir.glob("*.json"))
    if not jobs:
        print("No jobs in %s" % queue_dir)
        return 0

    failed = 0
    last_result_line = ""
    for job_path in jobs:
        success = False
        for attempt in range(1, retries + 1):
            print("=== JOB %s (attempt %d/%d) ===" % (job_path.name, attempt, retries))
            outcome = runner.run_render_job_file(
                config,
                job_path,
                no_upload=no_upload,
                force_upload=force_upload,
                traceback=False,
            )
            if outcome.result_line:
                last_result_line = outcome.result_line
            if outcome.status == "ok":
                print("=== OK  %s ===" % job_path.name)
                print(outcome.result_line)
                shutil.move(str(job_path), str(done_dir / job_path.name))
                success = True
                break
            print("=== FAIL %s ===" % job_path.name)
            print(outcome.result_line)
            if attempt < retries:
                time.sleep(sleep_s)

        if not success:
            shutil.move(str(job_path), str(failed_dir / job_path.name))
            failed += 1
        print()

    if failed:
        print("Run finished with failures: %d" % failed)
        if last_result_line:
            print(last_result_line)
        return 1

    print("Run finished: all ok")
    if last_result_line:
        print(last_result_line)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m shorts", description="Shorts automation CLI")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.required = True

    topics_parser = subparsers.add_parser("topics")
    topics_subparsers = topics_parser.add_subparsers(dest="topics_command")
    topics_subparsers.required = True
    topics_generate = topics_subparsers.add_parser("generate")
    topics_generate.add_argument("--config", default=ENV_SENTINEL)
    topics_generate.add_argument("--out")
    topics_generate.add_argument("--history")
    topics_generate.add_argument("--count", type=int, default=10)
    topics_generate.add_argument("--language")
    topics_generate.add_argument("--niche", default="테크/AI/인터넷 트렌드")
    topics_generate.add_argument("--style", default="테크 뉴스, 한 문장 짧게")
    topics_generate.set_defaults(func=_cmd_topics_generate)

    jobs_parser = subparsers.add_parser("jobs")
    jobs_subparsers = jobs_parser.add_subparsers(dest="jobs_command")
    jobs_subparsers.required = True
    jobs_draft = jobs_subparsers.add_parser("draft")
    jobs_draft.add_argument("--config", default=ENV_SENTINEL)
    jobs_draft.add_argument("--queue-dir")
    jobs_draft.add_argument("--draft-job", action="append")
    jobs_draft.add_argument("--topics-file")
    jobs_draft.add_argument("--topic", action="append")
    jobs_draft.add_argument("--count", type=int, default=1)
    jobs_draft.add_argument("--target-seconds", type=int)
    jobs_draft.add_argument("--style")
    jobs_draft.add_argument("--tone")
    jobs_draft.set_defaults(func=_cmd_jobs_draft)

    render_parser = subparsers.add_parser("render")
    render_parser.add_argument("--config", default=ENV_SENTINEL)
    render_parser.add_argument("--job", required=True)
    render_parser.add_argument("--no-upload", action="store_true")
    render_parser.add_argument("--force-upload", action="store_true")
    render_parser.add_argument("--audio")
    render_parser.add_argument("--traceback", action="store_true")
    render_parser.set_defaults(func=_cmd_render)

    queue_parser = subparsers.add_parser("queue")
    queue_subparsers = queue_parser.add_subparsers(dest="queue_command")
    queue_subparsers.required = True
    queue_run = queue_subparsers.add_parser("run")
    queue_run.add_argument("--config", default=ENV_SENTINEL)
    queue_run.add_argument("--queue-dir")
    queue_run.add_argument("--done-dir")
    queue_run.add_argument("--failed-dir")
    queue_run.add_argument("--retries", type=int, default=3)
    queue_run.add_argument("--sleep", type=float, default=3.0)
    queue_run.add_argument("--no-upload", action="store_true")
    queue_run.add_argument("--force-upload", action="store_true")
    queue_run.set_defaults(func=_cmd_queue_run)

    pipeline_parser = subparsers.add_parser("pipeline")
    pipeline_subparsers = pipeline_parser.add_subparsers(dest="pipeline_command")
    pipeline_subparsers.required = True
    pipeline_daily = pipeline_subparsers.add_parser("daily")
    pipeline_daily.add_argument("--config", default=ENV_SENTINEL)
    pipeline_daily.add_argument("--topics-file")
    pipeline_daily.add_argument("--history-file")
    pipeline_daily.add_argument("--queue-dir")
    pipeline_daily.add_argument("--done-dir")
    pipeline_daily.add_argument("--failed-dir")
    pipeline_daily.add_argument("--count", type=int, default=1)
    pipeline_daily.add_argument("--target-seconds", type=int)
    pipeline_daily.add_argument("--style", default="테크 뉴스, 한 문장 짧게")
    pipeline_daily.add_argument("--tone", default="빠르고 자신있게")
    pipeline_daily.add_argument("--niche", default="테크/AI/인터넷 트렌드")
    pipeline_daily.add_argument("--language")
    pipeline_daily.add_argument("--no-upload", action="store_true")
    pipeline_daily.add_argument("--force-upload", action="store_true")
    pipeline_daily.set_defaults(func=_cmd_pipeline_daily)
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except Exception as exc:
        if getattr(args, "traceback", False):
            raise
        print("ERROR %s: %s" % (type(exc).__name__, one_line(str(exc))), file=sys.stderr)
        return 1


def _cmd_topics_generate(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    out_path = Path(args.out or config.app.topics_file)
    history_path = Path(args.history or config.app.topics_history_file)
    language = args.language or config.content.openai_language or config.app.default_language
    generate_topics_to_file(
        config,
        out_path=out_path,
        history_path=history_path,
        count=args.count,
        language=language,
        niche=args.niche,
        style=args.style,
    )
    return 0


def _cmd_jobs_draft(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    draft_jobs = _collect_draft_jobs(args, config)
    if not draft_jobs:
        raise ValueError("No draft jobs. Use --draft-job, --topic, or --topics-file.")
    count = min(max(1, args.count), len(draft_jobs))
    queue_dir = Path(args.queue_dir or config.app.queue_dir)
    draft_jobs_to_queue(config, draft_jobs=draft_jobs[:count], queue_dir=queue_dir)
    return 0


def _cmd_render(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    outcome = runner.run_render_job_file(
        config,
        Path(args.job),
        no_upload=args.no_upload,
        force_upload=args.force_upload,
        audio_path=args.audio,
        traceback=args.traceback,
    )
    return 0 if outcome.status == "ok" else 1


def _cmd_queue_run(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    return run_queue(
        config,
        queue_dir=Path(args.queue_dir or config.app.queue_dir),
        done_dir=Path(args.done_dir or config.app.done_dir),
        failed_dir=Path(args.failed_dir or config.app.failed_dir),
        retries=max(1, args.retries),
        sleep_s=max(0.0, args.sleep),
        no_upload=args.no_upload,
        force_upload=args.force_upload,
    )


def _cmd_pipeline_daily(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    topics_file = Path(args.topics_file or config.app.topics_file)
    history_file = Path(args.history_file or config.app.topics_history_file)
    queue_dir = Path(args.queue_dir or config.app.queue_dir)
    done_dir = Path(args.done_dir or config.app.done_dir)
    failed_dir = Path(args.failed_dir or config.app.failed_dir)
    language = args.language or config.content.openai_language or config.app.default_language

    topics = generate_topics_to_file(
        config,
        out_path=topics_file,
        history_path=history_file,
        count=args.count,
        language=language,
        niche=args.niche,
        style=args.style,
    )
    draft_jobs = make_draft_jobs(
        topics=topics,
        style=args.style,
        tone=args.tone,
        target_seconds=args.target_seconds or config.app.shorts_target_seconds,
    )
    draft_jobs_to_queue(config, draft_jobs=draft_jobs, queue_dir=queue_dir)
    return run_queue(
        config,
        queue_dir=queue_dir,
        done_dir=done_dir,
        failed_dir=failed_dir,
        retries=1,
        sleep_s=0.0,
        no_upload=args.no_upload,
        force_upload=args.force_upload,
    )


def _collect_draft_jobs(args: argparse.Namespace, config: Config) -> list[DraftJob]:
    draft_jobs = []
    for path in args.draft_job or []:
        draft = load_draft_job(Path(path))
        draft_jobs.append(
            DraftJob(
                topic=draft.topic,
                style=args.style or draft.style,
                tone=args.tone or draft.tone,
                target_seconds=args.target_seconds or draft.target_seconds,
            )
        )

    topics = []
    if args.topics_file:
        topics.extend(load_topics_text(Path(args.topics_file)))
    if args.topic:
        topics.extend([item for item in args.topic if item and item.strip()])
    if topics:
        draft_jobs.extend(
            make_draft_jobs(
                topics=topics,
                style=args.style,
                tone=args.tone,
                target_seconds=args.target_seconds or config.app.shorts_target_seconds,
            )
        )
    return draft_jobs
