"""
transcripts/ 안의 정제된 자막 텍스트에서
- spaCy NER로 관광지(지명) 자동 감지 (GPE / LOC / FAC)
- 그 지명 주변(전후 WINDOW 토큰)에 등장한 형용사(ADJ)를 집계
해서 관광지별 영어 형용사 사용 빈도를 뽑는다.

CLI로 직접 실행하면 transcripts/ -> results/ 로 파일을 저장하고,
webapp/app.py는 compute_place_adjectives() / write_results()를 함수로 임포트해서 재사용한다.
"""
import csv
import glob
import os
import re
from collections import Counter, defaultdict

import spacy

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TRANSCRIPTS_DIR = os.path.join(BASE_DIR, "transcripts")
RESULTS_DIR = os.path.join(BASE_DIR, "results")

PLACE_LABELS = {"GPE", "LOC", "FAC"}
# 소형 spaCy 모델은 한국 고유 지명(자갈치, 감천 등)을 PERSON/ORG로 잘못 태깅하는 경우가
# 많다. 관광지 이름에 흔히 붙는 접미어가 있으면 PERSON/ORG/NORP도 지명 후보로 구제한다.
RESCUABLE_LABELS = {"PERSON", "ORG", "NORP"}
PLACE_SUFFIXES = {
    "beach", "market", "village", "temple", "tower", "bridge", "park",
    "island", "museum", "street", "fortress", "palace", "observatory",
    "skywalk", "square", "district", "alley", "falls", "mountain", "land",
    "zoo", "aquarium", "culture", "cultural", "town", "harbor", "harbour",
    "pier", "cape", "cave", "valley", "garden", "gardens", "hill", "hills",
    "stream", "river", "lake", "forest", "trail", "promenade", "gate",
}
WINDOW = 12          # 지명 앞뒤로 몇 토큰까지를 "같은 문맥"으로 볼지
TOP_N_SUMMARY = 15   # 요약 파일/화면에 관광지별로 보여줄 형용사 개수
MIN_MENTIONS = 2     # 이 횟수 미만으로 언급된 지명은 요약에서 제외 (노이즈 제거)

LEADING_ARTICLE_RE = re.compile(r"^(the|a|an)\s+", re.IGNORECASE)
PUNCT_STRIP_RE = re.compile(r"[\"'.,!?;:]+$")

_NLP = None


def get_nlp():
    """spaCy 모델을 프로세스당 한 번만 로딩해서 재사용한다 (웹앱에서 요청마다 새로 로딩하면 느림)."""
    global _NLP
    if _NLP is None:
        _NLP = spacy.load("en_core_web_sm")
    return _NLP


def normalize_place(text):
    text = text.strip()
    text = LEADING_ARTICLE_RE.sub("", text)
    text = PUNCT_STRIP_RE.sub("", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def is_place_entity(ent, doc):
    if ent.label_ in PLACE_LABELS:
        return True
    if ent.label_ not in RESCUABLE_LABELS:
        return False
    if any(word.lower() in PLACE_SUFFIXES for word in ent.text.split()):
        return True
    if ent.end < len(doc) and doc[ent.end].text.lower() in PLACE_SUFFIXES:
        return True
    return False


def load_transcripts(transcripts_dir=TRANSCRIPTS_DIR):
    texts = {}
    for path in glob.glob(os.path.join(transcripts_dir, "*.txt")):
        video_id = os.path.splitext(os.path.basename(path))[0]
        with open(path, encoding="utf-8") as f:
            content = f.read().strip()
        if content:
            texts[video_id] = content
    return texts


def compute_place_adjectives(texts, log=print):
    """
    texts: {video_id: transcript_text}
    반환값: (place_adjs, place_mentions, place_videos)
      place_adjs     : {attraction: Counter(adjective -> count)}
      place_mentions : Counter(attraction -> 총 언급 횟수)
      place_videos   : {attraction: {video_id, ...}}
    """
    nlp = get_nlp()

    place_adjs = defaultdict(Counter)
    place_mentions = Counter()
    place_videos = defaultdict(set)

    for video_id, text in texts.items():
        log(f"분석 중: {video_id} ({len(text.split())} 단어)")
        doc = nlp(text)

        adj_positions = [
            (tok.i, tok.lemma_.lower())
            for tok in doc
            if tok.pos_ == "ADJ" and tok.is_alpha
        ]

        for ent in doc.ents:
            if not is_place_entity(ent, doc):
                continue
            place = normalize_place(ent.text)
            if len(place) < 2:
                continue

            place_mentions[place] += 1
            place_videos[place].add(video_id)

            lo, hi = ent.start - WINDOW, ent.end + WINDOW
            for i, lemma in adj_positions:
                if lo <= i < hi:
                    place_adjs[place][lemma] += 1

    return place_adjs, place_mentions, place_videos


def write_results(place_adjs, place_mentions, place_videos, results_dir=RESULTS_DIR, log=print):
    os.makedirs(results_dir, exist_ok=True)

    csv_path = os.path.join(results_dir, "attraction_adjectives.csv")
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["attraction", "adjective", "count", "mentions", "videos"])
        for place in sorted(place_adjs, key=lambda p: -place_mentions[p]):
            for adj, count in place_adjs[place].most_common():
                writer.writerow([place, adj, count, place_mentions[place], len(place_videos[place])])
    log(f"\nCSV 저장: {csv_path}")

    summary_path = os.path.join(results_dir, "summary.txt")
    ranked_places = sorted(place_mentions, key=lambda p: -place_mentions[p])
    with open(summary_path, "w", encoding="utf-8") as f:
        for place in ranked_places:
            if place_mentions[place] < MIN_MENTIONS:
                continue
            f.write(f"[{place}] 언급 {place_mentions[place]}회, 영상 {len(place_videos[place])}개\n")
            top = place_adjs[place].most_common(TOP_N_SUMMARY)
            if not top:
                f.write("  (주변에서 감지된 형용사 없음)\n\n")
                continue
            for adj, count in top:
                f.write(f"  {adj}: {count}\n")
            f.write("\n")
    log(f"요약 저장: {summary_path}")
    return csv_path, summary_path


def analyze(transcripts_dir=TRANSCRIPTS_DIR, results_dir=RESULTS_DIR, log=print):
    texts = load_transcripts(transcripts_dir)
    if not texts:
        log(f"분석할 자막 텍스트가 없습니다. extract_transcript.py를 먼저 실행하세요: {transcripts_dir}")
        return None

    log("spaCy 모델 로딩 중...")
    place_adjs, place_mentions, place_videos = compute_place_adjectives(texts, log=log)
    write_results(place_adjs, place_mentions, place_videos, results_dir=results_dir, log=log)

    ranked_places = sorted(place_mentions, key=lambda p: -place_mentions[p])
    log("\n=== 상위 관광지 (언급 횟수 기준) ===")
    for place in ranked_places[:10]:
        top_adj = ", ".join(f"{a}({c})" for a, c in place_adjs[place].most_common(5))
        log(f"  {place} [{place_mentions[place]}회] -> {top_adj}")

    return place_adjs, place_mentions, place_videos


if __name__ == "__main__":
    analyze()
