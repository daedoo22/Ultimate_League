#!/usr/bin/env python3
"""
poisson.py — 기대득점(xG 기반)에서 1X2 / 언오버 / 아시안핸디 확률을 만든다.
Dixon-Coles 저스코어 보정 포함. 표준 라이브러리만 사용. Python 3.8+

왜 필요한가
-----------
기존 프롬프트는 "시나리오 A/B/C에 확률을 배분"해서 추정확률을 만들었다.
그건 서사에서 숫자를 뽑는 절차라 편향이 크고, 특히 무승부 확률이
구조적으로 과소평가된다(서사는 언제나 어느 한쪽이 이기는 이야기다).
확률은 득점 분포에서 나와야 하고, 서사는 그 분포를 설명하는 역할만 한다.

입력은 두 팀의 기대득점(lambda). 이 값은 최근 xG For/Against,
상대 수비 강도, 홈 어드밴티지를 반영해 만든다. 자세한 절차는
reference/확률_산출_규칙.md 참조.

사용 예
-------
  python3 tools/poisson.py --lh 1.65 --la 1.10
  python3 tools/poisson.py --lh 1.65 --la 1.10 --totals 2.5 3.0 --ah -0.75 -1.0
"""

from __future__ import annotations

import argparse
import math
from typing import Dict, List, Tuple

MAXG = 12  # 0~12골 격자면 꼬리 손실은 무시 가능한 수준


# --------------------------------------------------------------------------
# 스코어 격자
# --------------------------------------------------------------------------


def _pois(k: int, lam: float) -> float:
    return math.exp(-lam) * lam ** k / math.factorial(k)


def _tau(x: int, y: int, lh: float, la: float, rho: float) -> float:
    """Dixon-Coles 저스코어 보정항. 0-0과 1-1을 올리고 1-0/0-1을 낮춘다."""
    if x == 0 and y == 0:
        return 1.0 - lh * la * rho
    if x == 0 and y == 1:
        return 1.0 + lh * rho
    if x == 1 and y == 0:
        return 1.0 + la * rho
    if x == 1 and y == 1:
        return 1.0 - rho
    return 1.0


def score_grid(lh: float, la: float, rho: float = -0.13) -> List[List[float]]:
    """
    홈 x골, 원정 y골의 결합확률 격자.

    rho 기본값 -0.13은 Dixon-Coles 원논문의 추정치 부근이다.
    무승부가 실제보다 적게 나오는 순수 포아송의 약점을 보정한다.
    rho=0으로 두면 독립 포아송이 된다.
    """
    if lh <= 0 or la <= 0:
        raise ValueError("기대득점은 0보다 커야 한다")
    rho = max(-0.25, min(0.25, rho))

    g = [[0.0] * (MAXG + 1) for _ in range(MAXG + 1)]
    total = 0.0
    for x in range(MAXG + 1):
        px = _pois(x, lh)
        for y in range(MAXG + 1):
            v = px * _pois(y, la) * _tau(x, y, lh, la, rho)
            v = max(v, 0.0)          # tau가 음수로 가는 극단 케이스 방어
            g[x][y] = v
            total += v
    return [[v / total for v in row] for row in g]


# --------------------------------------------------------------------------
# 마켓별 확률
# --------------------------------------------------------------------------


def market_1x2(g: List[List[float]]) -> Tuple[float, float, float]:
    h = d = a = 0.0
    for x, row in enumerate(g):
        for y, p in enumerate(row):
            if x > y:
                h += p
            elif x == y:
                d += p
            else:
                a += p
    return h, d, a


def market_totals(g: List[List[float]], line: float) -> Dict[str, float]:
    """언더/오버/푸시. line이 정수면 푸시가 생긴다."""
    under = over = push = 0.0
    for x, row in enumerate(g):
        for y, p in enumerate(row):
            t = x + y
            if t < line:
                under += p
            elif t > line:
                over += p
            else:
                push += p
    return {"under": under, "over": over, "push": push}


def market_ah(g: List[List[float]], line: float) -> Dict[str, float]:
    """
    홈 기준 아시안핸디. line=-0.5면 홈 -0.5.
    쿼터 라인(.25/.75)은 인접 두 라인에 절반씩 나눠 계산한다.
    반환: win/push/lose(스테이크 기준)과 푸시 제외 순수 커버 확률.
    """
    q = round(line * 4) / 4
    if abs(q * 2 - round(q * 2)) > 1e-9:      # .25 또는 .75
        lo, hi = q - 0.25, q + 0.25
        a = market_ah(g, lo)
        b = market_ah(g, hi)
        win = 0.5 * (a["win"] + b["win"])
        push = 0.5 * (a["push"] + b["push"])
        lose = 0.5 * (a["lose"] + b["lose"])
    else:
        win = push = lose = 0.0
        for x, row in enumerate(g):
            for y, p in enumerate(row):
                m = (x - y) + q
                if m > 1e-9:
                    win += p
                elif m < -1e-9:
                    lose += p
                else:
                    push += p
    denom = win + lose
    return {
        "win": win,
        "push": push,
        "lose": lose,
        "cover": win / denom if denom > 0 else 0.5,   # 푸시 제외 2-way 공정확률
    }


def market_btts(g: List[List[float]]) -> float:
    return 1.0 - sum(g[0]) - sum(row[0] for row in g) + g[0][0]


def top_scores(g: List[List[float]], n: int = 6) -> List[Tuple[str, float]]:
    flat = [(f"{x}-{y}", p) for x, row in enumerate(g) for y, p in enumerate(row)]
    flat.sort(key=lambda t: -t[1])
    return flat[:n]


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def main() -> None:
    ap = argparse.ArgumentParser(description="기대득점 → 마켓 확률")
    ap.add_argument("--lh", type=float, required=True, help="홈 기대득점")
    ap.add_argument("--la", type=float, required=True, help="원정 기대득점")
    ap.add_argument("--rho", type=float, default=-0.13, help="Dixon-Coles rho (기본 -0.13, 0이면 독립 포아송)")
    ap.add_argument("--totals", type=float, nargs="*", default=[2.5], help="언오버 기준점")
    ap.add_argument("--ah", type=float, nargs="*", default=[], help="홈 기준 핸디 라인")
    args = ap.parse_args()

    g = score_grid(args.lh, args.la, args.rho)
    h, d, a = market_1x2(g)

    print(f"기대득점  홈 {args.lh:.2f} / 원정 {args.la:.2f}  (rho={args.rho})")
    print(f"총 기대득점 {args.lh + args.la:.2f}\n")
    print("[1X2]")
    print(f"  홈승 {h * 100:5.2f}%   무 {d * 100:5.2f}%   원정승 {a * 100:5.2f}%")
    print(f"  더블찬스  1X {(h + d) * 100:5.2f}%  12 {(h + a) * 100:5.2f}%  X2 {(d + a) * 100:5.2f}%")

    if args.rho != 0:
        g0 = score_grid(args.lh, args.la, 0.0)
        _, d0, _ = market_1x2(g0)
        print(f"  (독립 포아송 무승부 {d0 * 100:.2f}% → DC 보정 {d * 100:.2f}%)")

    print("\n[양팀득점]")
    print(f"  BTTS Yes {market_btts(g) * 100:5.2f}%")

    if args.totals:
        print("\n[언더/오버]")
        for L in args.totals:
            t = market_totals(g, L)
            extra = f"   푸시 {t['push'] * 100:.2f}%" if t["push"] > 0.005 else ""
            print(f"  {L:>4}  언더 {t['under'] * 100:5.2f}%  오버 {t['over'] * 100:5.2f}%{extra}")

    if args.ah:
        print("\n[아시안핸디 · 홈 기준]")
        for L in args.ah:
            r = market_ah(g, L)
            extra = f"  푸시 {r['push'] * 100:.2f}%" if r["push"] > 0.005 else ""
            print(f"  {L:+.2f}  승 {r['win'] * 100:5.2f}%  패 {r['lose'] * 100:5.2f}%{extra}"
                  f"   → 커버(푸시제외) {r['cover'] * 100:5.2f}%")

    print("\n[스코어 상위]")
    for s, p in top_scores(g):
        print(f"  {s}  {p * 100:5.2f}%")


if __name__ == "__main__":
    main()
