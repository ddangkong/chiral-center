"""
crawler.py — YouTube 자막 + 뉴스/웹 크롤러.

외부 인물의 발언, 인터뷰, 기사를 수집해 텍스트 청크로 변환합니다.
"""

import asyncio
import re
from typing import Optional
from utils.logger import log


async def fetch_youtube_transcript(video_url: str, lang: str = "ko") -> list[dict]:
    """YouTube 영상 자막을 텍스트 청크로 반환.

    Returns: [{"text": "...", "source": "youtube:VIDEO_ID", "timestamp": "0:00"}]
    """
    from youtube_transcript_api import YouTubeTranscriptApi

    video_id = _extract_video_id(video_url)
    if not video_id:
        raise ValueError(f"유효하지 않은 YouTube URL: {video_url}")

    log.info("youtube_crawl_start", video_id=video_id)

    loop = asyncio.get_event_loop()

    def _fetch():
        ytt_api = YouTubeTranscriptApi()
        # Try requested language first, fallback to any available
        try:
            transcript = ytt_api.fetch(video_id, languages=[lang, "en"])
        except Exception:
            transcript = ytt_api.fetch(video_id)
        return transcript

    transcript = await loop.run_in_executor(None, _fetch)

    # Group transcript segments into ~500 char chunks
    chunks = []
    current_text = ""
    current_start = 0.0

    for entry in transcript:
        text = entry.text.strip()
        if not text:
            continue

        if len(current_text) + len(text) > 500:
            if current_text:
                chunks.append({
                    "text": current_text.strip(),
                    "source": f"youtube:{video_id}",
                    "timestamp": _format_time(current_start),
                })
            current_text = text
            current_start = entry.start
        else:
            if not current_text:
                current_start = entry.start
            current_text += " " + text

    if current_text.strip():
        chunks.append({
            "text": current_text.strip(),
            "source": f"youtube:{video_id}",
            "timestamp": _format_time(current_start),
        })

    log.info("youtube_crawl_done", video_id=video_id, chunks=len(chunks))
    return chunks


async def fetch_web_article(url: str) -> list[dict]:
    """웹 기사/페이지 본문을 텍스트 청크로 반환.

    Returns: [{"text": "...", "source": "web:URL", "title": "..."}]
    """
    import trafilatura

    log.info("web_crawl_start", url=url)

    loop = asyncio.get_event_loop()

    def _fetch():
        downloaded = trafilatura.fetch_url(url)
        if not downloaded:
            return None, None
        text = trafilatura.extract(downloaded, include_comments=False, include_tables=True)
        metadata = trafilatura.extract(downloaded, output_format="json", include_comments=False)
        return text, metadata

    text, metadata_raw = await loop.run_in_executor(None, _fetch)

    if not text:
        raise ValueError(f"본문을 추출할 수 없습니다: {url}")

    # Parse title from metadata
    title = ""
    if metadata_raw:
        import json
        try:
            meta = json.loads(metadata_raw)
            title = meta.get("title", "")
        except Exception:
            pass

    # Split into paragraph chunks
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]

    # Merge small paragraphs into ~500 char chunks
    chunks = []
    current = ""
    for para in paragraphs:
        if len(current) + len(para) > 500:
            if current:
                chunks.append({
                    "text": current.strip(),
                    "source": f"web:{url}",
                    "title": title,
                })
            current = para
        else:
            current = (current + "\n\n" + para).strip()

    if current.strip():
        chunks.append({
            "text": current.strip(),
            "source": f"web:{url}",
            "title": title,
        })

    log.info("web_crawl_done", url=url, title=title, chunks=len(chunks))
    return chunks


async def fetch_multiple_urls(urls: list[str]) -> list[dict]:
    """여러 URL (YouTube + 웹) 동시 크롤링."""
    tasks = []
    for url in urls:
        if _is_youtube_url(url):
            tasks.append(fetch_youtube_transcript(url))
        else:
            tasks.append(fetch_web_article(url))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    all_chunks = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            log.warning("crawl_error", url=urls[i], error=str(result))
            continue
        all_chunks.extend(result)

    return all_chunks


# ── Helpers ──

def _extract_video_id(url: str) -> Optional[str]:
    """YouTube URL에서 video ID 추출."""
    patterns = [
        r'(?:v=|/v/|youtu\.be/)([a-zA-Z0-9_-]{11})',
        r'(?:embed/)([a-zA-Z0-9_-]{11})',
        r'^([a-zA-Z0-9_-]{11})$',  # bare ID
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def _is_youtube_url(url: str) -> bool:
    return bool(re.search(r'youtube\.com|youtu\.be', url))


def _format_time(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"
