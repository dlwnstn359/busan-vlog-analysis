# 부산 여행 브이로그 관광지별 영어 형용사 빈도 분석

외국인 유튜버의 부산 여행 브이로그 영어 자막을 받아서, 언급된 관광지(지명)마다
그 주변에서 쓰인 영어 형용사의 빈도를 집계합니다.

## 동작 방식

1. `download_subs.py` — `urls.txt`의 영상들에서 영어 자막을 내려받음
   - 사람이 올린 수동 자막이 있으면 그것을 우선 사용 (`.vtt`)
   - 없으면 유튜브 자동생성 자막을 사용 (`.json3` — 롤업 자막 특유의 줄 중복 문제가 없는 포맷)
2. `extract_transcript.py` — 원본 자막 파일을 타임스탬프/태그 없는 순수 텍스트로 정제
3. `analyze.py` — spaCy NER로 지명(관광지)을 자동 감지하고, 그 앞뒤 12토큰 안에 등장한
   형용사를 관광지별로 집계해 `results/`에 저장

## 설치

```
pip install -r requirements.txt
python -m spacy download en_core_web_sm
```

## 사용법 A — 웹페이지 (권장)

1. 서버 실행:
   ```
   python webapp/app.py
   ```
2. 브라우저에서 `http://127.0.0.1:5000` 접속
3. 텍스트박스에 유튜브 브이로그 링크를 한 줄에 하나씩 붙여넣고(최대 15개) "분석 시작" 클릭
4. 자막 확보 현황, 관광지별 형용사 태그가 화면에 바로 표시되고 CSV로도 다운로드 가능

내부적으로는 요청마다 `webapp/runs/<임의ID>/` 아래에 자막·텍스트·결과 파일을 저장한다.
로컬 전용이며 별도 배포 설정은 없다.

## 사용법 B — 커맨드라인

1. `urls.txt`를 열어 분석하고 싶은 부산 여행 브이로그 유튜브 URL을 한 줄에 하나씩 입력
2. 순서대로 실행:
   ```
   python download_subs.py
   python extract_transcript.py
   python analyze.py
   ```
3. 결과 확인:
   - `results/attraction_adjectives.csv` — attraction, adjective, count, mentions, videos 컬럼 (엑셀에서 바로 열림)
   - `results/summary.txt` — 관광지별 상위 형용사 요약, 콘솔에도 상위 10개 관광지 요약 출력

## 참고 / 한계

- 관광지 이름은 **미리 정의된 목록 없이** 자막에서 spaCy NER로 자동 감지합니다.
  소형 모델(`en_core_web_sm`)은 "Jagalchi Market" 같은 한국 고유 지명을 PERSON/ORG로
  잘못 태깅하는 경우가 있어, `analyze.py`에 Beach/Market/Village/Temple 등 지명 접미어
  기반 보정 규칙을 넣어 구제합니다. 그래도 완전히 새로운 지명(접미어 없는 고유명사만,
  예: "Taejongdae")은 놓칠 수 있습니다 — 이 경우 `results/attraction_adjectives.csv`를
  보고 필요하면 `analyze.py`의 `PLACE_SUFFIXES`에 단어를 추가하세요.
- 자동생성 자막은 문장부호가 부실해 문장 경계를 신뢰할 수 없어서, "지명과 같은 문장"이
  아니라 "지명 앞뒤 12토큰 이내"를 기준으로 형용사를 묶습니다 (`analyze.py`의 `WINDOW`
  값으로 조절 가능). 문맥이 좁은 영상에서는 형용사가 옆 관광지로 살짝 새어 들어갈 수
  있습니다.
- `en_core_web_sm`보다 정확도가 필요하면 `en_core_web_lg`(용량 큼)로 교체해 볼 수
  있습니다: `python -m spacy download en_core_web_lg` 후 `analyze.py`의
  `spacy.load("en_core_web_sm")`를 `en_core_web_lg`로 변경.
- 자막이 아예 없는 영상(수동/자동 모두 없음)은 자동으로 건너뜁니다.
