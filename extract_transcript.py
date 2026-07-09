"""
subs/ 아래의 원본 자막 파일(.vtt, .json3)을 읽어서
관광지-형용사 분석에 쓸 수 있는 순수 텍스트로 정제해 transcripts/에 저장한다.

- .vtt (수동 자막): 타임스탬프/태그 제거 + 연속 중복 줄 제거
- .json3 (자동생성 자막): 이벤트 세그먼트를 시간 순서대로 이어붙임
  (유튜브 자동자막 특유의 "롤업(rolling)" 중복 문제가 없는 포맷)
"""
import glob
import json
import os
import re

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SUBS_DIR = os.path.join(BASE_DIR, "subs")
TRANSCRIPTS_DIR = os.path.join(BASE_DIR, "transcripts")

TAG_RE = re.compile(r"<[^>]+>")
TIMESTAMP_LINE_RE = re.compile(r"^\d{2}:\d{2}:\d{2}[.,]\d{3}\s*-->")
WHITESPACE_RE = re.compile(r"\s+")


def clean_vtt(path):
    lines_out = []
    prev_line = None
    with open(path, encoding="utf-8", errors="ignore") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            if line.startswith("WEBVTT") or line.startswith("Kind:") or line.startswith("Language:"):
                continue
            if TIMESTAMP_LINE_RE.match(line):
                continue
            if line.isdigit():
                continue
            text = TAG_RE.sub("", line).strip()
            if not text:
                continue
            if text == prev_line:
                continue
            lines_out.append(text)
            prev_line = text
    return " ".join(lines_out)


def clean_json3(path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    words = []
    for event in data.get("events", []):
        segs = event.get("segs")
        if not segs:
            continue
        for seg in segs:
            text = seg.get("utf8", "")
            if text:
                words.append(text)
    text = "".join(words)
    return WHITESPACE_RE.sub(" ", text).strip()


def extract_all(subs_dir=SUBS_DIR, transcripts_dir=TRANSCRIPTS_DIR, log=print):
    """
    subs_dir의 모든 .vtt/.json3 파일을 정제해 transcripts_dir에 저장한다.
    반환값: {video_id: word_count} (내용이 있었던 파일만)
    """
    os.makedirs(transcripts_dir, exist_ok=True)
    files = glob.glob(os.path.join(subs_dir, "*.vtt")) + glob.glob(os.path.join(subs_dir, "*.json3"))
    if not files:
        log(f"자막 파일이 없습니다. 먼저 자막을 다운로드하세요: {subs_dir}")
        return {}

    word_counts = {}
    for path in files:
        base = os.path.basename(path)
        video_id = base.split(".")[0]
        if path.endswith(".vtt"):
            text = clean_vtt(path)
        else:
            text = clean_json3(path)

        if not text:
            log(f"{base}: 내용 없음, 건너뜀")
            continue

        out_path = os.path.join(transcripts_dir, video_id + ".txt")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(text)
        word_count = len(text.split())
        word_counts[video_id] = word_count
        log(f"{base}: {word_count} 단어 -> {os.path.basename(out_path)}")

    return word_counts


def main():
    extract_all()


if __name__ == "__main__":
    main()
