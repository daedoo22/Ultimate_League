#!/usr/bin/env python3
"""
calibrate.py — 픽 기록에서 정확도를 실제로 측정한다.
표준 라이브러리만 사용. Python 3.8+

왜 필요한가
-----------
"맨날 틀린다"는 느낌이지 측정이 아니다. 측정 없이는 개선도 없다.
이 스크립트는 세 가지를 분리해서 보여준다.

  1) 확률이 잘 맞춰져 있는가        → Brier score, 로그손실, 캘리브레이션 구간
  2) 판단이 시장보다 나았는가        → CLV(클로징 라인 대비 우위)
  3) 돈이 됐는가                    → ROI

이 셋은 다르다. 적중률이 낮아도 CLV가 양수면 판단은 옳고 표본이 부족한 것이고,
적중률이 높아도 CLV가 음수면 운이다. 개선 방향이 정반대로 갈리므로
반드시 나눠서 봐야 한다.

사용 예
-------
  python3 tools/calibrate.py logs/picks.csv
  python3 tools/calibrate.py logs/picks.csv --tier 주력
  python3 tools/calibrate.py logs/picks.csv --market 1X2 --since 2026-01-01
"""

from __future__ import annotations

import argparse
import csv
import math
import sys
from collections import defaultdict
from typing import Dict, List, Optional

# result 값 → 스테이크 1단위 기준 손익 계수(배당 b = odds-1 곱하기 전)
WIN_FRAC = {
    "WIN": 1.0,
    "HALF_WIN": 0.5,
    "PUSH": 0.0,
    "HALF_LOSE": -0.5,
    "LOSE": -1.0,
}
# 캘리브레이션·적중률 집계에서 실현값으로 쓰는 값(푸시는 제외)
OUTCOME = {"WIN": 1.0, "HALF_WIN": 1.0, "HALF_LOSE": 0.0, "LOSE": 0.0}


class Pick:
    __slots__ = ("row", "date", "league", "market", "tier", "p", "odds",
                 "closing", "stake", "result")

    def __init__(self, row: Dict[str, str]):
        self.row = row
        self.date = (row.get("date_kst") or "").strip()
        self.league = (row.get("league") or "").strip()
        self.market = (row.get("market") or "").strip()
        self.tier = (row.get("tier") or "").strip()
        self.result = (row.get("result") or "").strip().upper()
        self.p = _f(row.get("p_final")) or _f(row.get("p_model"))
        self.odds = _f(row.get("odds_taken"))
        self.closing = _f(row.get("closing_odds"))
        self.stake = _f(row.get("stake_units")) or 1.0


def _f(v: Optional[str]) -> Optional[float]:
    if v is None:
        return None
    v = str(v).strip()
    if not v:
        return None
    try:
        return float(v)
    except ValueError:
        return None


def load(path: str) -> List[Pick]:
    with open(path, newline="", encoding="utf-8-sig") as fh:
        return [Pick(r) for r in csv.DictReader(fh)]


# --------------------------------------------------------------------------
# 지표
# --------------------------------------------------------------------------


def brier(picks: List[Pick]) -> Optional[float]:
    """낮을수록 좋다. 0.25 = 무지성 50% 예측 수준."""
    vals = [(p.p, OUTCOME[p.result]) for p in picks
            if p.result in OUTCOME and p.p is not None]
    if not vals:
        return None
    return sum((p - o) ** 2 for p, o in vals) / len(vals)


def logloss(picks: List[Pick]) -> Optional[float]:
    vals = [(p.p, OUTCOME[p.result]) for p in picks
            if p.result in OUTCOME and p.p is not None]
    if not vals:
        return None
    acc = 0.0
    for p, o in vals:
        p = min(max(p, 1e-6), 1 - 1e-6)
        acc -= o * math.log(p) + (1 - o) * math.log(1 - p)
    return acc / len(vals)


def roi(picks: List[Pick]):
    staked = pnl = 0.0
    n = 0
    for p in picks:
        if p.result not in WIN_FRAC or p.odds is None:
            continue
        n += 1
        staked += p.stake
        pnl += p.stake * WIN_FRAC[p.result] * (p.odds - 1.0 if WIN_FRAC[p.result] > 0 else 1.0)
    return n, staked, pnl, (pnl / staked * 100 if staked else None)


def clv(picks: List[Pick]):
    """
    CLV = 잡은 배당 / 클로징 배당 - 1.
    양수면 시장이 내 방향으로 움직였다는 뜻이고, 장기 수익의 선행지표다.
    적중률보다 훨씬 빨리 수렴하므로 표본이 적을 때 이걸 본다.
    """
    vals = [(p.odds / p.closing - 1.0) * 100
            for p in picks
            if p.odds and p.closing and p.closing > 1.0]
    if not vals:
        return None
    beat = sum(1 for v in vals if v > 0)
    return {
        "n": len(vals),
        "mean": sum(vals) / len(vals),
        "beat_rate": beat / len(vals) * 100,
    }


def reliability(picks: List[Pick], bins=((0, .4), (.4, .5), (.5, .6),
                                         (.6, .7), (.7, .8), (.8, 1.01))):
    """구간별 '예측 평균확률 vs 실제 적중률'. 과신 여부가 여기서 드러난다."""
    buckets = defaultdict(list)
    for p in picks:
        if p.result not in OUTCOME or p.p is None:
            continue
        for lo, hi in bins:
            if lo <= p.p < hi:
                buckets[(lo, hi)].append((p.p, OUTCOME[p.result]))
                break
    out = []
    for lo, hi in bins:
        v = buckets.get((lo, hi), [])
        if not v:
            continue
        out.append({
            "range": f"{lo * 100:.0f}~{hi * 100:.0f}%",
            "n": len(v),
            "pred": sum(x for x, _ in v) / len(v) * 100,
            "act": sum(y for _, y in v) / len(v) * 100,
        })
    return out


# --------------------------------------------------------------------------
# 출력
# --------------------------------------------------------------------------


def report(picks: List[Pick], label: str) -> None:
    settled = [p for p in picks if p.result in WIN_FRAC]
    print(f"\n{'=' * 62}\n{label}\n{'=' * 62}")
    print(f"기록 {len(picks)}건 / 정산 완료 {len(settled)}건 / 미정산 {len(picks) - len(settled)}건")
    if not settled:
        print("정산된 기록이 없다. result 열을 채워라.")
        return

    scored = [p for p in settled if p.result in OUTCOME]
    if scored:
        hit = sum(OUTCOME[p.result] for p in scored) / len(scored) * 100
        print(f"적중률 {hit:.1f}%  (푸시 {len(settled) - len(scored)}건 제외)")

    b, ll = brier(settled), logloss(settled)
    if b is not None:
        print(f"Brier {b:.4f}   로그손실 {ll:.4f}")
        if len(scored) < 30:
            print("  → 표본 30건 미만이라 이 값은 해석하지 않는다.")
        elif b > 0.25:
            print("  → 0.25 초과. 늘 50%라고 답하는 것보다 못하다. 모델 자체를 의심하라.")
        elif b > 0.23:
            print("  → 경계선. 확률이 과신 쪽으로 치우쳤을 가능성이 크다.")

    n, staked, pnl, r = roi(settled)
    if r is not None:
        print(f"베팅 {n}건 / 스테이크 {staked:.1f}u / 손익 {pnl:+.2f}u / ROI {r:+.2f}%")

    c = clv(picks)
    if c:
        print(f"CLV 평균 {c['mean']:+.2f}%  (표본 {c['n']}건, 클로징 이긴 비율 {c['beat_rate']:.1f}%)")
        if c["mean"] > 0.5:
            print("  → 양수 CLV. 판단은 유효하다. 손실은 표본 부족일 가능성이 높다.")
        elif c["mean"] < -1.0:
            print("  → 음수 CLV. 시장이 반대로 움직였다. 픽 논리 자체를 손봐야 한다.")
    else:
        print("CLV 미산출 — closing_odds 열이 비어 있다. 킥오프 직전 배당을 반드시 기록하라.")

    rel = reliability(settled)
    if rel:
        print("\n캘리브레이션")
        print(f"  {'구간':<10}{'건수':>6}{'예측':>9}{'실제':>9}{'격차':>9}")
        for r_ in rel:
            gap = r_["act"] - r_["pred"]
            if r_["n"] < 10:
                flag = "  (표본부족)"
            else:
                flag = "  ←과신" if gap < -8 else ("  ←과소" if gap > 8 else "")
            print(f"  {r_['range']:<10}{r_['n']:>6}{r_['pred']:>8.1f}%"
                  f"{r_['act']:>8.1f}%{gap:>+8.1f}p{flag}")

    if len(settled) < 30:
        print(f"\n※ 정산 {len(settled)}건은 통계적으로 아무것도 말해주지 않는다.")
        print("  3%p 엣지를 소음과 구분하려면 수백 건이 필요하다.")
        print("  이 구간에서 유일하게 믿을 지표는 CLV다.")


def main() -> None:
    ap = argparse.ArgumentParser(description="픽 기록 캘리브레이션 리포트")
    ap.add_argument("csv", help="logs/picks.csv 경로")
    ap.add_argument("--tier", help="주력 / 부주력 등으로 필터")
    ap.add_argument("--market", help="1X2 / AH / U-O 등으로 필터")
    ap.add_argument("--league", help="리그로 필터")
    ap.add_argument("--since", help="YYYY-MM-DD 이후")
    ap.add_argument("--split", action="store_true", help="마켓별로 나눠서 출력")
    args = ap.parse_args()

    try:
        picks = load(args.csv)
    except FileNotFoundError:
        sys.exit(f"파일을 찾을 수 없다: {args.csv}")

    if args.tier:
        picks = [p for p in picks if p.tier == args.tier]
    if args.market:
        picks = [p for p in picks if p.market == args.market]
    if args.league:
        picks = [p for p in picks if p.league == args.league]
    if args.since:
        picks = [p for p in picks if p.date >= args.since]

    if not picks:
        sys.exit("조건에 맞는 기록이 없다.")

    report(picks, "전체")

    if args.split:
        for m in sorted({p.market for p in picks if p.market}):
            report([p for p in picks if p.market == m], f"마켓: {m}")


if __name__ == "__main__":
    try:
        main()
    except BrokenPipeError:   # `| head` 등으로 파이프가 끊긴 경우
        try:
            sys.stdout.close()
        finally:
            sys.exit(0)
