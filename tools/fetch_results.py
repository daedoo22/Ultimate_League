#!/usr/bin/env python3
"""
fetch_results.py — football-data.co.uk에서 리그 결과 CSV를 받아 합친다.
표준 라이브러리만 사용. Python 3.8+

football-data.co.uk는 회원가입도 API 키도 없이 CSV를 그냥 준다.
득점·슈팅·카드·배당이 들어 있어 베이스레이트 산출에는 이것으로 충분하다.

  다만 xG는 없다. λ 조립에 쓸 팀별 xG는 FBref나 Understat에서 따로 받아야 한다.
  이 스크립트로 받는 건 어디까지나 reference/리그별_베이스레이트.md 갱신용이다.

URL 구조
--------
  5대 리그 등 주요 리그 (시즌별 파일)
    https://www.football-data.co.uk/mmz4281/{시즌}/{코드}.csv
    예) .../mmz4281/2526/E0.csv  →  2025/26 EPL

  그 외 국가 (한 파일에 전 시즌이 들어 있다)
    https://www.football-data.co.uk/new/{국가코드}.csv
    예) .../new/KOR.csv

사용 예
-------
  # EPL·라리가·분데스·세리에A·리그앙, 최근 3시즌
  python3 tools/fetch_results.py --div E0 SP1 D1 I1 F1 --seasons 2425 2526 2627 -o results.csv

  # K리그 (전 시즌 한 파일)
  python3 tools/fetch_results.py --extra KOR -o kleague.csv

  # 받은 뒤 바로 베이스레이트
  python3 tools/baserate.py results.csv --by league
"""

from __future__ import annotations

import argparse
import csv
import io
import os
import sys
import urllib.error
import urllib.request

BASE_MAIN = "https://www.football-data.co.uk/mmz4281/{season}/{div}.csv"
BASE_EXTRA = "https://www.football-data.co.uk/new/{code}.csv"

# 주요 리그 코드. 사이트의 Data 페이지에서 언제든 확인할 수 있다.
DIVS = {
    "E0": "잉글랜드 프리미어리그",
    "E1": "잉글랜드 챔피언십",
    "SP1": "스페인 라리가",
    "SP2": "스페인 세군다",
    "D1": "독일 분데스리가",
    "D2": "독일 2.분데스리가",
    "I1": "이탈리아 세리에A",
    "I2": "이탈리아 세리에B",
    "F1": "프랑스 리그앙",
    "F2": "프랑스 리그2",
    "N1": "네덜란드 에레디비시",
    "P1": "포르투갈 프리메이라리가",
    "B1": "벨기에 주필러",
    "T1": "튀르키예 쉬페르리그",
    "SC0": "스코틀랜드 프리미어십",
    "G1": "그리스 수페르리가",
}

# /new/ 경로의 국가 파일. 한 파일에 여러 시즌이 들어 있다.
EXTRAS = {
    "KOR": "대한민국 K리그",
    "JPN": "일본 J리그",
    "USA": "미국 MLS",
    "BRA": "브라질 세리에A",
    "ARG": "아르헨티나 프리메라",
    "MEX": "멕시코 리가MX",
    "CHN": "중국 슈퍼리그",
    "AUT": "오스트리아 분데스리가",
    "SWZ": "스위스 슈퍼리그",
    "DNK": "덴마크 수페르리가",
    "NOR": "노르웨이 엘리테세리엔",
    "SWE": "스웨덴 알스벤스칸",
    "POL": "폴란드 엑스트라클라사",
    "RUS": "러시아 프리미어리그",
}

UA = "Mozilla/5.0 (compatible; ultimate-league/1.0)"
TIMEOUT = 60


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        raw = r.read()
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def parse(text: str, source: str):
    """CSV 텍스트 → dict 목록. 뒤쪽 빈 행은 버린다."""
    rows = []
    for row in csv.DictReader(io.StringIO(text)):
        if not any((v or "").strip() for v in row.values()):
            continue
        row["_source"] = source
        rows.append(row)
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description="football-data.co.uk 결과 CSV 다운로드")
    ap.add_argument("--div", nargs="*", default=[], metavar="코드",
                    help=f"주요 리그 코드. 가능: {', '.join(DIVS)}")
    ap.add_argument("--seasons", nargs="*", default=[], metavar="YYZZ",
                    help="시즌 코드. 2526 = 2025/26. --div와 함께 쓴다")
    ap.add_argument("--extra", nargs="*", default=[], metavar="국가",
                    help=f"국가 코드(전 시즌 한 파일). 가능: {', '.join(EXTRAS)}")
    ap.add_argument("-o", "--out", default="results.csv", help="저장 경로")
    ap.add_argument("--list", action="store_true", help="코드 목록만 보고 끝낸다")
    args = ap.parse_args()

    if args.list:
        print("[주요 리그 — --div 로 지정, --seasons 필요]")
        for k, v in DIVS.items():
            print(f"  {k:<5} {v}")
        print("\n[그 외 국가 — --extra 로 지정, 한 파일에 전 시즌]")
        for k, v in EXTRAS.items():
            print(f"  {k:<5} {v}")
        print("\n시즌 코드: 2425 = 2024/25, 2526 = 2025/26, 2627 = 2026/27")
        return

    if not args.div and not args.extra:
        sys.exit("--div 또는 --extra 중 하나는 지정해야 한다. 목록은 --list")
    if args.div and not args.seasons:
        sys.exit("--div 를 쓰면 --seasons 도 지정해야 한다 (예: --seasons 2425 2526)")

    targets = []
    for d in args.div:
        if d not in DIVS:
            print(f"경고: 알 수 없는 리그 코드 {d} — 그대로 시도한다", file=sys.stderr)
        for s in args.seasons:
            targets.append((BASE_MAIN.format(season=s, div=d), f"{d}-{s}"))
    for e in args.extra:
        if e not in EXTRAS:
            print(f"경고: 알 수 없는 국가 코드 {e} — 그대로 시도한다", file=sys.stderr)
        targets.append((BASE_EXTRA.format(code=e), e))

    all_rows, cols, failed = [], [], []
    for url, label in targets:
        try:
            rows = parse(fetch(url), label)
        except urllib.error.HTTPError as ex:
            failed.append((label, f"HTTP {ex.code}"))
            print(f"  실패 {label:<10} HTTP {ex.code}  {url}", file=sys.stderr)
            continue
        except Exception as ex:                       # 네트워크·프록시·타임아웃
            failed.append((label, type(ex).__name__))
            print(f"  실패 {label:<10} {type(ex).__name__}: {ex}", file=sys.stderr)
            continue
        for r in rows:
            for k in r:
                if k not in cols:
                    cols.append(k)
        all_rows.extend(rows)
        print(f"  받음 {label:<10} {len(rows):>5}경기")

    if not all_rows:
        print("\n받은 데이터가 없다.", file=sys.stderr)
        if failed:
            print("원인 후보:", file=sys.stderr)
            print("  - 해당 시즌 파일이 아직 없다 (시즌 개막 전)", file=sys.stderr)
            print("  - 리그/국가 코드가 틀렸다 (--list 로 확인)", file=sys.stderr)
            print("  - 네트워크가 막혀 있다 (사내망·프록시)", file=sys.stderr)
            print("\n브라우저로 https://www.football-data.co.uk/data.php 에서", file=sys.stderr)
            print("직접 받아도 결과는 같다. baserate.py는 어느 쪽이든 읽는다.", file=sys.stderr)
        sys.exit(1)

    out = os.path.abspath(args.out)
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(all_rows)

    print(f"\n총 {len(all_rows)}경기 → {out}")
    if failed:
        print(f"실패 {len(failed)}건: " + ", ".join(f"{a}({b})" for a, b in failed))
    print(f"\n다음 단계:\n  python3 tools/baserate.py {args.out} --by league")


if __name__ == "__main__":
    main()
