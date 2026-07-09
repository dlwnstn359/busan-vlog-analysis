"""
로컬 웹앱: 브라우저에서 유튜브 브이로그 링크를 입력하면
yt-dlp로 영어 자막을 받아 관광지별 형용사 빈도를 분석해 보여준다.

실행:
    python webapp/app.py
그 다음 브라우저에서 http://127.0.0.1:5000 접속.
"""
import os
import sys
import uuid

from flask import Flask, abort, redirect, render_template, request, send_file, url_for

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # busan_vlog_analysis/
sys.path.insert(0, BASE_DIR)

import analyze          # noqa: E402
import download_subs    # noqa: E402
import extract_transcript  # noqa: E402

RUNS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "runs")
MAX_URLS = 15

app = Flask(__name__)
os.makedirs(RUNS_DIR, exist_ok=True)

# run_id -> results_dir (CSV 다운로드용, 프로세스 메모리에만 유지되는 간단한 로컬 저장소)
RUN_RESULTS = {}


def parse_urls(raw_text):
    urls = []
    for line in raw_text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        urls.append(line)
    return urls


@app.route("/")
def index():
    return render_template("index.html", max_urls=MAX_URLS)


@app.route("/analyze", methods=["POST"])
def analyze_route():
    urls = parse_urls(request.form.get("urls", ""))
    if not urls:
        return render_template("index.html", max_urls=MAX_URLS, error="유튜브 링크를 최소 1개 입력하세요.")
    if len(urls) > MAX_URLS:
        return render_template(
            "index.html", max_urls=MAX_URLS,
            error=f"한 번에 최대 {MAX_URLS}개까지 분석할 수 있습니다. ({len(urls)}개 입력됨)",
        )

    run_id = uuid.uuid4().hex[:12]
    run_dir = os.path.join(RUNS_DIR, run_id)
    subs_dir = os.path.join(run_dir, "subs")
    transcripts_dir = os.path.join(run_dir, "transcripts")
    results_dir = os.path.join(run_dir, "results")

    logs = []
    log = logs.append

    downloads = download_subs.download_urls(urls, subs_dir, log=log)
    extract_transcript.extract_all(subs_dir, transcripts_dir, log=log)
    result = analyze.analyze(transcripts_dir, results_dir, log=log)

    attractions = []
    if result is not None:
        place_adjs, place_mentions, place_videos = result
        for place in sorted(place_mentions, key=lambda p: -place_mentions[p]):
            attractions.append({
                "name": place,
                "mentions": place_mentions[place],
                "video_count": len(place_videos[place]),
                "adjectives": place_adjs[place].most_common(15),
            })
        RUN_RESULTS[run_id] = results_dir

    return render_template(
        "results.html",
        run_id=run_id,
        downloads=downloads,
        attractions=attractions,
        has_csv=run_id in RUN_RESULTS,
        log_text="\n".join(logs),
    )


@app.route("/download/<run_id>")
def download_csv(run_id):
    results_dir = RUN_RESULTS.get(run_id)
    if not results_dir:
        abort(404)
    csv_path = os.path.join(results_dir, "attraction_adjectives.csv")
    if not os.path.isfile(csv_path):
        abort(404)
    return send_file(csv_path, as_attachment=True, download_name=f"busan_attraction_adjectives_{run_id}.csv")


if __name__ == "__main__":
    print("spaCy 모델을 미리 로딩합니다...")
    analyze.get_nlp()
    print("준비 완료. http://127.0.0.1:5000 에서 접속하세요.")
    app.run(debug=False, port=5000)
