#!/usr/bin/env python3
"""
baserate.py — 리그 경기결과 CSV에서 베이스레이트를 직접 계산한다.
표준 라이브러리만 사용. Python 3.8+

왜 필요한가
-----------
"이 리그 무승부 비율은 대충 25%쯤" 같은 기억에 의존한 값이 오차의 출발점이다.
홈 어드밴티지는 리그마다 다르고 시즌마다 변한다(특히 2020년 이후 하락 추세).
reference/리그별_베이스레이트.md의 표는 어디까지나 시드값이고,
시즌마다 이 스크립트로 실제 데이터에서 다시 뽑아 덮어써야 한다.

입력 CSV (FBref·football-data.co.uk 등에서 받은 결과표)
  필수 열: home_goals, away_goals   (또는 FTHG, FTAG)
  선택 열: league(Div), date(Date), home(HomeTeam), away(AwayTeam)

사용 예
-------
  python3 tools/baserate.py results.csv
  python3 tools/baserate.py results.csv --by league
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

HOME_KEYS = ("home_goals", "FTHG", "home_score", "hg")
AWAY_KEYS = ("away_goals", "FTAG", "away_score", "ag")
LEAGUE_KEYS = ("league", "Div", "competition", "comp")


def _pick(row: Dict[str, str], keys) -> Optional[str]:
    for k in keys:
        if k in row and str(row[k]).strip() != "":
            return str(row[k]).strip()
    return None


def load(path: str) -> List[Tuple[str, int, int]]:
    out = []
    with open(path, newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            h, a = _pick(row, HOME_KEYS), _pick(row, AWAY_KEYS)
            if h is None or a is None:
                continue
            try:
                hg, ag = int(float(h)), int(float(a))
            except ValueError:
                continue
            out.append((_pick(row, LEAGUE_KEYS) or "ALL", hg, ag))
    return out


def summarize(games: List[Tuple[str, int, int]]) -> Dict[str, float]:
    n = len(games)
    hw = sum(1 for _, h, a in games if h > a)
    dr = sum(1 for _, h, a in games if h == a)
    aw = n - hw - dr
    hg = sum(h for _, h, _ in games)
    ag = sum(a for _, _, a in games)
    btts = sum(1 for _, h, a in games if h > 0 and a > 0)
    o25 = sum(1 for _, h, a in games if h + a > 2.5)
    o35 = sum(1 for _, h, a in games if h + a > 3.5)
    cs_h = sum(1 for _, _, a in games if a == 0)
    cs_a = sum(1 for _, h, _ in games if h == 0)
    return {
        "n": n,
        "home_win": hw / n * 100,
        "draw": dr / n * 100,
        "away_win": aw / n * 100,
        "avg_home_goals": hg / n,
        "avg_away_goals": ag / n,
        "avg_total": (hg + ag) / n,
        "home_adv": (hg - ag) / n,
        "btts": btts / n * 100,
        "over25": o25 / n * 100,
        "over35": o35 / n * 100,
        "cs_home": cs_h / n * 100,
        "cs_away": cs_a / n * 100,
    }


def show(name: str, s: Dict[str, float]) -> None:
    print(f"\n[{name}]  표본 {s['n']:.0f}경기")
    if s["n"] < 100:
        print("  ※ 100경기 미만은 참고용에 불과하다.")
    print(f"  홈승 {s['home_win']:5.1f}%   무 {s['draw']:5.1f}%   원정승 {s['away_win']:5.1f}%")
    print(f"  평균득점  홈 {s['avg_home_goals']:.2f} / 원정 {s['avg_away_goals']:.2f} "
          f"/ 합계 {s['avg_total']:.2f}   홈 어드밴티지 {s['home_adv']:+.2f}골")
    print(f"  BTTS {s['btts']:5.1f}%   오버2.5 {s['over25']:5.1f}%   오버3.5 {s['over35']:5.1f}%")
    print(f"  무실점  홈 {s['cs_home']:5.1f}%   원정 {s['cs_away']:5.1f}%")
    print(f"  → 프리뷰 시 무승부 확률의 출발점: {s['draw']:.0f}% 부근")


def main() -> None:
    ap = argparse.ArgumentParser(description="결과 CSV → 리그 베이스레이트")
    ap.add_argument("csv")
    ap.add_argument("--by", choices=["league"], help="리그별로 분리 집계")
    args = ap.parse_args()

    try:
        games = load(args.csv)
    except FileNotFoundError:
        sys.exit(f"파일을 찾을 수 없다: {args.csv}")
    if not games:
        sys.exit("득점 열을 찾지 못했다. home_goals/away_goals 또는 FTHG/FTAG 열이 필요하다.")

    show("전체", summarize(games))
    if args.by == "league":
        groups = defaultdict(list)
        for g in games:
            groups[g[0]].append(g)
        for k in sorted(groups):
            show(k, summarize(groups[k]))


if __name__ == "__main__":
    main()
