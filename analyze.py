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
from spacy.matcher import PhraseMatcher
from spacy.tokens import Span
from spacy.util import filter_spans

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

# 관광지가 아니라 배경 지명(여행지 자체, 출발/경유 도시, 국가·국적)이라서 분석 대상에서 제외한다.
# 브이로거의 출신 국가가 어디든 "나라 이름 자체"는 관광지가 아니므로 흔한 국가/국적을 폭넓게 걸러낸다.
EXCLUDED_PLACES = {
    "korea", "south korea", "north korea", "korean", "koreans", "seoul", "busan", "asia",
    "canada", "canadian", "usa", "u.s.", "u.s.a.", "united states", "america", "american",
    "uk", "united kingdom", "britain", "england", "british", "scotland", "ireland", "irish",
    "australia", "australian", "new zealand", "japan", "japanese", "china", "chinese",
    "taiwan", "hong kong", "singapore", "malaysia", "thailand", "vietnam", "philippines",
    "indonesia", "india", "germany", "german", "france", "french", "italy", "italian",
    "spain", "spanish", "russia", "russian", "mexico", "mexican", "brazil", "europe",
}

# 자동생성 자막은 대문자 표기가 없어 spaCy NER이 잘 아는 국가/대도시 이름(seoul, korea 등)만
# 잡아내고 정작 "haeundae beach" 같은 실제 명소는 놓치는 경우가 많다. 그래서 부산 명소는
# 별칭 목록으로 직접 매칭해 소문자 자막에서도 확실히 잡는다.
BUSAN_ATTRACTIONS = {
    "Haeundae Beach": ["haeundae beach", "haeundae"],
    "Gwangalli Beach": ["gwangalli beach", "gwangalli"],
    "Jagalchi Market": ["jagalchi market", "jagalchi fish market", "jagalchi"],
    "Gamcheon Culture Village": ["gamcheon culture village", "gamcheon village", "gamcheon"],
    "Taejongdae": ["taejongdae"],
    "Yongdusan Park": ["yongdusan park"],
    "Busan Tower": ["busan tower"],
    "Dongbaek Island": ["dongbaek island", "apec house"],
    "Songjeong Beach": ["songjeong beach"],
    "Songdo Beach": ["songdo beach"],
    "Dadaepo Beach": ["dadaepo beach"],
    "Haedong Yonggungsa Temple": ["haedong yonggungsa", "yonggungsa temple", "yonggungsa"],
    "Beomeosa Temple": ["beomeosa temple", "beomeosa"],
    "Oryukdo": ["oryukdo"],
    "Igidae": ["igidae", "igidae park"],
    "BIFF Square": ["biff square"],
    "Nampo-dong": ["nampo-dong", "nampodong"],
    "Seomyeon": ["seomyeon"],
    "Centum City": ["centum city"],
    "Gukje Market": ["gukje market", "international market"],
    "Bupyeong Kkangtong Market": ["bupyeong market", "kkangtong market", "bupyeong kkangtong market"],
    "Songdo Cable Car": ["songdo cable car", "songdo skywalk"],
    "Haeundae Blueline Park": ["blueline park", "haeundae sky capsule"],
    "Ibagu-gil": ["ibagu-gil", "ibagu gil", "168 steps"],
}
# NER 루프와 매처 루프가 같은 명소를 중복 집계하지 않도록, 별칭에 해당하는 표현은 NER 쪽에서 제외한다.
GAZETTEER_ALIASES = {alias for aliases in BUSAN_ATTRACTIONS.values() for alias in aliases} | {
    name.lower() for name in BUSAN_ATTRACTIONS
}

_NLP = None
_MATCHER = None


def get_nlp():
    """spaCy 모델을 프로세스당 한 번만 로딩해서 재사용한다 (웹앱에서 요청마다 새로 로딩하면 느림)."""
    global _NLP
    if _NLP is None:
        _NLP = spacy.load("en_core_web_sm")
    return _NLP


def get_matcher():
    """부산 명소 별칭 매처도 프로세스당 한 번만 만들어서 재사용한다."""
    global _MATCHER
    if _MATCHER is None:
        nlp = get_nlp()
        matcher = PhraseMatcher(nlp.vocab, attr="LOWER")
        for canonical, aliases in BUSAN_ATTRACTIONS.items():
            matcher.add(canonical, [nlp.make_doc(alias) for alias in aliases])
        _MATCHER = matcher
    return _MATCHER


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
    matcher = get_matcher()

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

        def collect(place, start, end):
            place_mentions[place] += 1
            place_videos[place].add(video_id)
            lo, hi = start - WINDOW, end + WINDOW
            for i, lemma in adj_positions:
                if lo <= i < hi:
                    place_adjs[place][lemma] += 1

        for ent in doc.ents:
            if not is_place_entity(ent, doc):
                continue
            place = normalize_place(ent.text)
            if len(place) < 2:
                continue
            if place.lower() in EXCLUDED_PLACES or place.lower() in GAZETTEER_ALIASES:
                continue
            collect(place, ent.start, ent.end)

        gazetteer_spans = [Span(doc, s, e, label=mid) for mid, s, e in matcher(doc)]
        for span in filter_spans(gazetteer_spans):
            collect(nlp.vocab.strings[span.label], span.start, span.end)

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
