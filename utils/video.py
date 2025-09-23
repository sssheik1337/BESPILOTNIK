import asyncio
import logging
import os
import subprocess
from pathlib import Path
from time import perf_counter
from typing import Optional

import ffmpeg


logger = logging.getLogger(__name__)


class _FFmpegExecutionError(RuntimeError):
    """Обёртка для ошибок запуска ffmpeg."""


def _null_sink() -> str:
    return "NUL" if os.name == "nt" else "/dev/null"


async def _probe_duration(path: Path) -> Optional[float]:
    """Возвращает длительность ролика в секундах."""

    def _probe() -> Optional[float]:
        try:
            info = ffmpeg.probe(str(path))
        except ffmpeg.Error as exc:  # pragma: no cover - ffprobe сообщает stderr
            logger.error(
                "Не удалось получить длительность %s: %s",
                path,
                exc.stderr.decode(errors="ignore") if exc.stderr else exc,
            )
            return None
        duration = info.get("format", {}).get("duration")
        try:
            return float(duration) if duration is not None else None
        except (TypeError, ValueError):
            logger.error("Некорректная длительность %s: %s", path, duration)
            return None

    return await asyncio.to_thread(_probe)


async def _run_ffmpeg_cmd(args: list[str], description: str) -> None:
    """Запускает ffmpeg с указанными аргументами и логирует результат."""

    def _execute() -> tuple[float, str, str, int]:
        start = perf_counter()
        try:
            completed = subprocess.run(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
        except FileNotFoundError as exc:  # pragma: no cover - зависит от окружения
            raise FileNotFoundError("Исполняемый файл ffmpeg не найден") from exc

        duration = perf_counter() - start
        stdout_text = completed.stdout.decode(errors="ignore")
        stderr_text = completed.stderr.decode(errors="ignore")
        return duration, stdout_text, stderr_text, completed.returncode

    duration, stdout_text, stderr_text, returncode = await asyncio.to_thread(_execute)

    if returncode != 0:
        logger.error(
            "FFmpeg завершился с кодом %s (%s) за %.2f с: %s",
            returncode,
            description,
            duration,
            stderr_text,
        )
        raise _FFmpegExecutionError(stderr_text or description)

    logger.debug(
        "FFmpeg завершил %s за %.2f с: stdout=%s, stderr=%s",
        description,
        duration,
        stdout_text,
        stderr_text,
    )


def _cleanup_pass_logs(passlog: Path) -> None:
    prefix = passlog.name
    parent = passlog.parent
    for artifact in parent.glob(f"{prefix}*"):
        artifact.unlink(missing_ok=True)


async def compress_video(
    input_file: str,
    target_size_mb: int = 75,
    audio_bitrate_kbps: int = 96,
    preset: str = "slow",
) -> str:
    """Сжимает видео до заданного размера (≈target_size_mb) и возвращает итоговый путь."""

    source_path = Path(input_file)
    if not source_path.exists():
        logger.warning("Файл для сжатия не найден: %s", input_file)
        return input_file

    target_bytes = target_size_mb * 1024 * 1024
    original_size = source_path.stat().st_size
    if original_size <= target_bytes:
        logger.debug(
            "Файл %s уже меньше или равен целевому размеру (%.2f МБ <= %s МБ), "
            "сжатие не требуется",
            input_file,
            original_size / (1024 * 1024),
            target_size_mb,
        )
        return input_file

    logger.info(
        "Начинаем двухпроходное сжатие %s (%.2f МБ) до ~%s МБ",
        input_file,
        original_size / (1024 * 1024),
        target_size_mb,
    )

    duration = await _probe_duration(source_path)
    if not duration or duration <= 0:
        logger.warning("Не удалось определить длительность %s. Используем исходный файл", input_file)
        return input_file

    # Расчёт битрейта
    reserve_ratio = 0.96
    audio_bitrate = max(audio_bitrate_kbps, 32) * 1000
    total_bits_budget = target_bytes * 8 * reserve_ratio
    video_bits = total_bits_budget - audio_bitrate * duration
    min_video_bitrate_kbps = 300
    if video_bits <= 0:
        logger.warning(
            "Недостаточно бюджета битрейта для %s, используем минимальный уровень",
            input_file,
        )
        video_bitrate_kbps = min_video_bitrate_kbps
    else:
        video_bitrate_kbps = max(int(video_bits / duration / 1000), min_video_bitrate_kbps)

    maxrate_kbps = int(video_bitrate_kbps * 1.45)
    bufsize_kbps = int(video_bitrate_kbps * 3)

    logger.info(
        "Битрейты для %s: видео ~%s kbps, макс %s kbps, буфер %s kbps, аудио %s kbps",
        input_file,
        video_bitrate_kbps,
        maxrate_kbps,
        bufsize_kbps,
        audio_bitrate_kbps,
    )

    temp_output = source_path.with_name(f"{source_path.stem}_compressed.mp4")
    passlog = source_path.with_name(f"{source_path.stem}_passlog")
    null_output = _null_sink()

    base_args = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(source_path),
        "-c:v",
        "libx264",
        "-b:v",
        f"{video_bitrate_kbps}k",
        "-maxrate",
        f"{maxrate_kbps}k",
        "-bufsize",
        f"{bufsize_kbps}k",
        "-preset",
        preset,
        "-vf",
        "scale='min(1280,iw)':-2",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        "-passlogfile",
        str(passlog),
    ]

    start_time = perf_counter()

    try:
        logger.info("FFmpeg pass 1 для %s", input_file)
        pass1_args = base_args + ["-an", "-pass", "1", "-f", "mp4", null_output]
        await _run_ffmpeg_cmd(pass1_args, f"pass1 {source_path.name}")

        logger.info("FFmpeg pass 2 для %s", input_file)
        pass2_args = base_args + [
            "-c:a",
            "aac",
            "-b:a",
            f"{audio_bitrate_kbps}k",
            "-pass",
            "2",
            str(temp_output),
        ]
        await _run_ffmpeg_cmd(pass2_args, f"pass2 {source_path.name}")
    except FileNotFoundError:
        logger.error(
            "Исполняемый файл ffmpeg не найден. Проверьте, что он установлен в системе."
        )
        temp_output.unlink(missing_ok=True)
        return input_file
    except _FFmpegExecutionError:
        temp_output.unlink(missing_ok=True)
        return input_file
    finally:
        _cleanup_pass_logs(passlog)

    if not temp_output.exists():
        logger.warning("FFmpeg не создал выходной файл для %s", input_file)
        return input_file

    final_size_mb = temp_output.stat().st_size / (1024 * 1024)
    logger.info(
        "Видео %s сжато до %.2f МБ за %.2f с",
        input_file,
        final_size_mb,
        perf_counter() - start_time,
    )

    final_path = (
        source_path
        if source_path.suffix.lower() == ".mp4"
        else source_path.with_suffix(".mp4")
    )

    try:
        source_path.unlink(missing_ok=True)
        temp_output.replace(final_path)
        return str(final_path)
    except Exception:  # pragma: no cover - защитный блок
        logger.exception("Не удалось заменить исходный файл %s", input_file)
        temp_output.unlink(missing_ok=True)
        return input_file
