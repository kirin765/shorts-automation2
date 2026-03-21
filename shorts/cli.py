from __future__ import annotations

import argparse
import shutil
import sys
import time
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from . import runner, upload


class _LazyProviders:
    def __getattr__(self, name: str):
        from . import providers as _providers

        return getattr(_providers, name)


providers = _LazyProviders()
from .config import ENV_SENTINEL, Config, load_config
from .models import (
    append_topics_text,
    load_reviewed_package,
    load_script_package,
    load_selected_topic,
    load_topic_pool,
    load_topics_text,
    slugify,
    write_render_job,
    write_reviewed_package,
    write_script_package,
    write_selected_topic,
    write_topic_pool,
)
from .output import one_line


def generate_topic_pool_to_file(
    config: Config,
    *,
    out_path: Path,
    history_path: Path,
    count: int,
    run_id: str,
) -> Path:
    existing = load_topics_text(history_path) if history_path.exists() else []
    topic_pool = providers.generate_topic_pool(
        config,
        run_id=run_id,
        count=count,
        existing_topics=existing,
    )
    write_topic_pool(out_path, topic_pool)
    return out_path


def evaluate_topic_pool_to_files(
    config: Config,
    *,
    topic_pool_path: Path,
    out_dir: Path,
    count: int,
) -> list[Path]:
    topic_pool = load_topic_pool(topic_pool_path)
    selected_topics = providers.evaluate_topic_pool(config, topic_pool, select_count=count)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for item in selected_topics:
        path = out_dir / ("selected_topic_%02d.json" % item.rank)
        write_selected_topic(path, item)
        paths.append(path)
    return paths


def generate_script_package_to_file(
    config: Config,
    *,
    selected_topic_path: Optional[Path],
    topic: Optional[str],
    out_path: Path,
    run_id: str,
) -> Path:
    if selected_topic_path is not None:
        selected_topic = load_selected_topic(selected_topic_path)
    else:
        selected_topic = providers.manual_selected_topic(config, run_id=run_id, topic=topic or "")
    script_package = providers.generate_script_package(config, selected_topic)
    write_script_package(out_path, script_package)
    return out_path


def review_script_package_to_file(
    config: Config,
    *,
    script_package_path: Path,
    out_path: Path,
) -> Path:
    script_package = load_script_package(script_package_path)
    review_feedback = providers.review_script_package(config, script_package)
    rewrite_applied = False
    if not providers.review_passes(config, script_package, review_feedback):
        script_package = providers.rewrite_script_package(config, script_package, review_feedback)
        review_feedback = providers.review_script_package(config, script_package)
        rewrite_applied = True
    if not providers.review_passes(config, script_package, review_feedback):
        detail = "; ".join(review_feedback.review_notes or review_feedback.risk_flags or review_feedback.rewrite_instructions or ["review failed"])
        raise RuntimeError("script review failed after rewrite: %s" % one_line(detail))
    reviewed = providers.build_reviewed_package(
        config,
        script_package,
        review_feedback,
        rewrite_applied=rewrite_applied,
    )
    write_reviewed_package(out_path, reviewed)
    return out_path


def package_reviewed_job_to_queue(
    config: Config,
    *,
    reviewed_package_path: Path,
    queue_dir: Path,
) -> Path:
    reviewed = load_reviewed_package(reviewed_package_path)
    render_job = providers.package_render_job(reviewed)
    queue_dir.mkdir(parents=True, exist_ok=True)
    stamp = date.today().strftime("%Y-%m-%d")
    suffix = _path_index_suffix(reviewed_package_path)
    path = queue_dir / ("%s_%s_%s.json" % (stamp, slugify(reviewed.topic)[:40], suffix))
    write_render_job(path, render_job)
    return path


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
    topics_generate.add_argument("--work-dir")
    topics_generate.add_argument("--run-id")
    topics_generate.add_argument("--count", type=int, default=8)
    topics_generate.set_defaults(func=_cmd_topics_generate)

    topics_evaluate = topics_subparsers.add_parser("evaluate")
    topics_evaluate.add_argument("--config", default=ENV_SENTINEL)
    topics_evaluate.add_argument("--topic-pool", required=True)
    topics_evaluate.add_argument("--out-dir")
    topics_evaluate.add_argument("--count", type=int, default=1)
    topics_evaluate.set_defaults(func=_cmd_topics_evaluate)

    scripts_parser = subparsers.add_parser("scripts")
    scripts_subparsers = scripts_parser.add_subparsers(dest="scripts_command")
    scripts_subparsers.required = True

    scripts_generate = scripts_subparsers.add_parser("generate")
    scripts_generate.add_argument("--config", default=ENV_SENTINEL)
    scripts_generate.add_argument("--selected-topic")
    scripts_generate.add_argument("--topic")
    scripts_generate.add_argument("--out")
    scripts_generate.add_argument("--work-dir")
    scripts_generate.add_argument("--run-id")
    scripts_generate.set_defaults(func=_cmd_scripts_generate)

    scripts_review = scripts_subparsers.add_parser("review")
    scripts_review.add_argument("--config", default=ENV_SENTINEL)
    scripts_review.add_argument("--script-package", required=True)
    scripts_review.add_argument("--out")
    scripts_review.set_defaults(func=_cmd_scripts_review)

    jobs_parser = subparsers.add_parser("jobs")
    jobs_subparsers = jobs_parser.add_subparsers(dest="jobs_command")
    jobs_subparsers.required = True

    jobs_package = jobs_subparsers.add_parser("package")
    jobs_package.add_argument("--config", default=ENV_SENTINEL)
    jobs_package.add_argument("--reviewed-package", required=True)
    jobs_package.add_argument("--queue-dir")
    jobs_package.set_defaults(func=_cmd_jobs_package)

    youtube_parser = subparsers.add_parser("youtube")
    youtube_subparsers = youtube_parser.add_subparsers(dest="youtube_command")
    youtube_subparsers.required = True
    youtube_auth = youtube_subparsers.add_parser("auth")
    youtube_auth.add_argument("--config", default=ENV_SENTINEL)
    youtube_auth.add_argument("--authorization-response")
    youtube_auth.add_argument("--force", action="store_true")
    youtube_auth.set_defaults(func=_cmd_youtube_auth)

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
    pipeline_daily.add_argument("--work-dir")
    pipeline_daily.add_argument("--history-file")
    pipeline_daily.add_argument("--queue-dir")
    pipeline_daily.add_argument("--done-dir")
    pipeline_daily.add_argument("--failed-dir")
    pipeline_daily.add_argument("--count", type=int, default=1)
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
        command = "%s.%s" % (getattr(args, "command", "unknown"), getattr(args, "%s_command" % getattr(args, "command", ""), "") or "run")
        print("ERROR %s: %s" % (type(exc).__name__, one_line(str(exc))), file=sys.stderr)
        print("RESULT status=error command=%s error=%s" % (command, one_line(str(exc))), file=sys.stderr)
        return 1


def _cmd_topics_generate(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    run_id = args.run_id or _new_run_id()
    out_path = Path(args.out) if args.out else _default_run_dir(config, args.work_dir, run_id) / "topic_pool.json"
    history_path = Path(args.history or config.app.topics_history_file)
    generate_topic_pool_to_file(
        config,
        out_path=out_path,
        history_path=history_path,
        count=max(1, args.count),
        run_id=run_id,
    )
    print("Wrote topic pool: %s" % out_path)
    print("RESULT status=ok command=topics.generate output=%s" % one_line(str(out_path)))
    return 0


def _cmd_topics_evaluate(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    topic_pool_path = Path(args.topic_pool)
    out_dir = Path(args.out_dir) if args.out_dir else topic_pool_path.parent
    paths = evaluate_topic_pool_to_files(
        config,
        topic_pool_path=topic_pool_path,
        out_dir=out_dir,
        count=max(1, args.count),
    )
    print("Selected topics:")
    for path in paths:
        print("- %s" % path)
    print("RESULT status=ok command=topics.evaluate count=%d" % len(paths))
    return 0


def _cmd_scripts_generate(args: argparse.Namespace) -> int:
    if bool(args.selected_topic) == bool(args.topic):
        raise ValueError("Use exactly one of --selected-topic or --topic.")
    config = load_config(args.config)
    run_id = args.run_id or _new_run_id()
    if args.out:
        out_path = Path(args.out)
    elif args.selected_topic:
        selected_path = Path(args.selected_topic)
        out_path = selected_path.with_name("script_package_%s.json" % _path_index_suffix(selected_path))
    else:
        out_path = _default_run_dir(config, args.work_dir, run_id) / "script_package_01.json"
    generate_script_package_to_file(
        config,
        selected_topic_path=Path(args.selected_topic) if args.selected_topic else None,
        topic=args.topic,
        out_path=out_path,
        run_id=run_id,
    )
    print("Wrote script package: %s" % out_path)
    print("RESULT status=ok command=scripts.generate output=%s" % one_line(str(out_path)))
    return 0


def _cmd_scripts_review(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    script_package_path = Path(args.script_package)
    out_path = Path(args.out) if args.out else script_package_path.with_name("reviewed_package_%s.json" % _path_index_suffix(script_package_path))
    review_script_package_to_file(config, script_package_path=script_package_path, out_path=out_path)
    print("Wrote reviewed package: %s" % out_path)
    print("RESULT status=ok command=scripts.review output=%s" % one_line(str(out_path)))
    return 0


def _cmd_jobs_package(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    queue_dir = Path(args.queue_dir or config.app.queue_dir)
    path = package_reviewed_job_to_queue(
        config,
        reviewed_package_path=Path(args.reviewed_package),
        queue_dir=queue_dir,
    )
    print("Enqueued: %s" % path)
    print("RESULT status=ok command=jobs.package output=%s" % one_line(str(path)))
    return 0


def _cmd_youtube_auth(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    token_file, mode = upload.youtube_authenticate(
        config,
        authorization_response=args.authorization_response,
        force=args.force,
    )
    print("YouTube token ready: %s" % token_file)
    print("RESULT status=ok command=youtube.auth token_file=%s mode=%s" % (one_line(str(token_file)), mode))
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
    run_id = _new_run_id()
    run_dir = _default_run_dir(config, args.work_dir, run_id)
    history_file = Path(args.history_file or config.app.topics_history_file)
    queue_dir = Path(args.queue_dir or config.app.queue_dir)
    done_dir = Path(args.done_dir or config.app.done_dir)
    failed_dir = Path(args.failed_dir or config.app.failed_dir)
    count = max(1, args.count)
    pool_path = run_dir / "topic_pool.json"
    selected_topics = []

    generate_topic_pool_to_file(
        config,
        out_path=pool_path,
        history_path=history_file,
        count=max(config.content.topic_pool_size, count * 4),
        run_id=run_id,
    )
    selected_paths = evaluate_topic_pool_to_files(
        config,
        topic_pool_path=pool_path,
        out_dir=run_dir,
        count=count,
    )

    for index, selected_path in enumerate(selected_paths, start=1):
        script_path = run_dir / ("script_package_%02d.json" % index)
        reviewed_path = run_dir / ("reviewed_package_%02d.json" % index)
        generate_script_package_to_file(
            config,
            selected_topic_path=selected_path,
            topic=None,
            out_path=script_path,
            run_id=run_id,
        )
        review_script_package_to_file(
            config,
            script_package_path=script_path,
            out_path=reviewed_path,
        )
        package_reviewed_job_to_queue(
            config,
            reviewed_package_path=reviewed_path,
            queue_dir=queue_dir,
        )
        selected_topics.append(load_reviewed_package(reviewed_path).topic)

    append_topics_text(history_file, selected_topics)
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


def _default_run_dir(config: Config, work_dir_override: Optional[str], run_id: str) -> Path:
    return Path(work_dir_override or config.app.work_dir) / run_id


def _new_run_id() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _path_index_suffix(path: Path) -> str:
    digits = "".join(ch for ch in path.stem if ch.isdigit())
    return digits[-2:] if digits else "01"
