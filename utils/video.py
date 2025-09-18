import asyncio
import logging
from pathlib import Path
from typing import Iterable, Optional

import ffmpeg


logger = logging.getLogger(__name__)


async def _run_ffmpeg(
    input_path: Path,
    output_path: Path,
    crf: int,
    preset: str = "medium",
) -> Optional[Path]:
    """Запускает перекодирование видео и возвращает путь к сжатому файлу."""

    def _encode() -> tuple[bytes, bytes]:
        stream = (
            ffmpeg.input(str(input_path))
            .output(
                str(output_path),
                vcodec="libx264",
                preset=preset,
                crf=crf,
                acodec="aac",
                audio_bitrate="128k",
                vf="scale='min(1280,iw)':-2",
            )
            .overwrite_output()
        )
        return stream.run(capture_stdout=True, capture_stderr=True)

    try:
        stdout, stderr = await asyncio.to_thread(_encode)
        logger.debug(
            "FFmpeg завершил перекодирование %s (CRF=%s): stdout=%s, stderr=%s",
            input_path,
            crf,
            stdout.decode(errors="ignore"),
            stderr.decode(errors="ignore"),
        )
    except ffmpeg.Error as exc:
        logger.error(
            "Ошибка ffmpeg при перекодировании %s (CRF=%s): %s",
            input_path,
            crf,
            exc.stderr.decode(errors="ignore") if exc.stderr else exc,
        )
        if output_path.exists():
            output_path.unlink(missing_ok=True)
        return None
    except FileNotFoundError:
        logger.error(
            "Исполняемый файл ffmpeg не найден. Проверьте, что он установлен в системе."
        )
        if output_path.exists():
            output_path.unlink(missing_ok=True)
        return None
    except Exception:  # pragma: no cover - защитный блок
        logger.exception("Неизвестная ошибка ffmpeg при обработке %s", input_path)
        if output_path.exists():
            output_path.unlink(missing_ok=True)
        return None

    return output_path if output_path.exists() else None


async def compress_video(
    input_file: str,
    target_size_mb: int = 100,
    crf_levels: Iterable[int] = (28, 32, 36),
) -> str:
    """Сжимает видео до целевого размера и возвращает путь к итоговому файлу."""

    source_path = Path(input_file)
    if not source_path.exists():
        logger.warning("Файл для сжатия не найден: %s", input_file)
        return input_file

    original_size = source_path.stat().st_size
    best_output: Optional[Path] = None
    temp_outputs: set[Path] = set()

    for crf in crf_levels:
        temp_output = source_path.with_name(f"{source_path.stem}_compressed_{crf}.mp4")
        temp_outputs.add(temp_output)
        compressed = await _run_ffmpeg(source_path, temp_output, crf=crf)
        if not compressed or not compressed.exists():
            continue

        size_mb = compressed.stat().st_size / (1024 * 1024)
        logger.debug(
            "Получен файл %s размером %.2f МБ для %s при CRF=%s",
            compressed,
            size_mb,
            input_file,
            crf,
        )

        if compressed.stat().st_size < original_size:
            if best_output and best_output != compressed and best_output.exists():
                best_output.unlink(missing_ok=True)
            best_output = compressed
        else:
            logger.debug(
                "Сжатый файл не меньше исходного: %s >= %s",
                compressed.stat().st_size,
                original_size,
            )
            compressed.unlink(missing_ok=True)
            continue

        if size_mb <= target_size_mb:
            logger.info(
                "Видео %s сжато до %.2f МБ при CRF=%s", input_file, size_mb, crf
            )
            break
        logger.info(
            "После CRF=%s размер %.2f МБ превышает лимит %s МБ, пробуем ниже качество",
            crf,
            size_mb,
            target_size_mb,
        )
        best_output = compressed

    if not best_output:
        for artifact in temp_outputs:
            if artifact.exists():
                artifact.unlink(missing_ok=True)
        logger.warning(
            "Не удалось сжать видео %s, используется исходный файл.", input_file
        )
        return input_file

    final_path = (
        source_path
        if source_path.suffix.lower() == ".mp4"
        else source_path.with_suffix(".mp4")
    )

    try:
        source_path.unlink(missing_ok=True)
        best_output.replace(final_path)
        logger.info(
            "Видео %s успешно сжато и сохранено как %s (%.2f МБ)",
            input_file,
            final_path,
            final_path.stat().st_size / (1024 * 1024),
        )
        return str(final_path)
    except Exception:
        logger.exception("Ошибка при замене файла %s на сжатый вариант", input_file)
        # В случае ошибки откатываемся к исходному пути
        best_output.unlink(missing_ok=True)
        return input_file
    finally:
        for artifact in temp_outputs:
            if artifact.exists() and artifact != final_path:
                artifact.unlink(missing_ok=True)
