"""
유튜브 영상들의 영어 자막을 내려받는다.
- 수동(사람이 올린) 영어 자막이 있으면 그것을 우선 사용 (vtt)
- 없으면 유튜브 자동생성 영어 자막을 사용 (json3 - 롤업 자막 중복 문제가 없는 포맷)

CLI로 직접 실행하면 urls.txt를 읽어 처리하고, webapp/app.py는
download_urls()를 함수로 임포트해서 재사용한다.
"""
import glob
import os
import sys

import yt_dlp

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
URLS_FILE = os.path.join(BASE_DIR, "urls.txt")
SUBS_DIR = os.path.join(BASE_DIR, "subs")

# en-orig 등 변형 코드를 포함해 최대한 넓게 영어 자막을 잡는다
LANGS = ["en", "en-US", "en-GB", "en-orig", "en.*"]

# 클라우드 서버 IP는 유튜브 봇 탐지에 걸리는 경우가 많아, 로그인 쿠키 파일이 있으면 함께 사용한다.
# Render의 Secret Files 기능으로 올리면 /etc/secrets/<파일명> 경로에 마운트된다.
COOKIES_FILE = os.environ.get("YTDLP_COOKIES_FILE", "/etc/secrets/cookies.txt")


def _cookie_opts():
    if COOKIES_FILE and os.path.isfile(COOKIES_FILE):
        return {"cookiefile": COOKIES_FILE}
    return {}


def read_urls(urls_file=URLS_FILE):
    urls = []
    with open(urls_file, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            urls.append(line)
    return urls


def has_sub_file(video_id, subs_dir):
    pattern = os.path.join(subs_dir, f"{video_id}.*")
    return [p for p in glob.glob(pattern) if p.endswith((".vtt", ".json3"))]


def download(url, subs_dir, auto):
    opts = {
        "skip_download": True,
        "writesubtitles": not auto,
        "writeautomaticsub": auto,
        "subtitleslangs": LANGS,
        "subtitlesformat": "json3" if auto else "vtt",
        "outtmpl": os.path.join(subs_dir, "%(id)s.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
        "ignoreerrors": True,
        **_cookie_opts(),
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.extract_info(url, download=True)


def download_urls(urls, subs_dir, log=print):
    """
    각 url에 대해 자막을 내려받는다.
    반환값: [{"url", "video_id", "title", "status", "files"}, ...]
    status는 "manual" | "auto" | "no_captions" | "error" 중 하나.
    """
    os.makedirs(subs_dir, exist_ok=True)
    results = []

    for url in urls:
        log(f"\n=== {url} ===")
        try:
            with yt_dlp.YoutubeDL({"quiet": True, "skip_download": True, "no_warnings": True, **_cookie_opts()}) as probe:
                info = probe.extract_info(url, download=False)
            video_id = info["id"]
            title = info.get("title", "")
        except Exception as e:
            log(f"  정보 조회 실패, 건너뜀: {e}")
            results.append({"url": url, "video_id": None, "title": None, "status": "error", "files": [], "error": str(e)})
            continue

        log(f"  제목: {title}")

        existing = has_sub_file(video_id, subs_dir)
        if existing:
            log(f"  이미 자막 있음, 건너뜀: {video_id}")
            status = "manual" if any(p.endswith(".vtt") for p in existing) else "auto"
            results.append({"url": url, "video_id": video_id, "title": title, "status": status, "files": existing})
            continue

        try:
            download(url, subs_dir, auto=False)
        except Exception as e:
            log(f"  수동 자막 다운로드 오류: {e}")

        existing = has_sub_file(video_id, subs_dir)
        if existing:
            log(f"  수동 영어 자막 확보: {[os.path.basename(p) for p in existing]}")
            results.append({"url": url, "video_id": video_id, "title": title, "status": "manual", "files": existing})
            continue

        try:
            download(url, subs_dir, auto=True)
        except Exception as e:
            log(f"  자동 자막 다운로드 오류: {e}")

        existing = has_sub_file(video_id, subs_dir)
        if existing:
            log(f"  자동생성 영어 자막 확보: {[os.path.basename(p) for p in existing]}")
            results.append({"url": url, "video_id": video_id, "title": title, "status": "auto", "files": existing})
        else:
            log(f"  영어 자막을 찾을 수 없음, 분석에서 제외됨: {video_id}")
            results.append({"url": url, "video_id": video_id, "title": title, "status": "no_captions", "files": []})

    return results


def main():
    urls = read_urls()
    if not urls:
        print(f"urls.txt에 분석할 유튜브 URL을 한 줄에 하나씩 추가하세요: {URLS_FILE}")
        sys.exit(1)
    download_urls(urls, SUBS_DIR)


if __name__ == "__main__":
    main()
