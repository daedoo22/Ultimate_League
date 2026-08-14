#!/usr/bin/env python3
"""
devig.py — 배당에서 부거지(마진)를 제거해 공정확률을 구하고,
모델확률과 블렌딩한 뒤 엣지를 계산한다.

의존성 없음(표준 라이브러리만). Python 3.8+

왜 필요한가
-----------
기존 규칙의 `p_raw / sum(p_raw)` (비례 정규화)는 구현이 쉽지만
favourite-longshot bias 때문에 **언더독 확률을 구조적으로 과대평가**한다.
실측하면(이 스크립트로 직접 확인 가능) 저마진 북에서 0.4~1.5%p,
마진 7% 이상인 고마진 북에서는 2%p 이상 벌어진다.
기존 프롬프트의 주력 픽 기준이 "엣지 4%p"였음을 감안하면,
마진 제거 방식만 바꿔도 엣지의 절반이 사라지는 경우가 있다.
즉 지금까지의 엣지 일부는 실제 우위가 아니라 계산 방식의 오차였다.

사용 예
-------
  python3 tools/devig.py 1x2 2.10 3.40 3.60
  python3 tools/devig.py 2way 1.91 1.95
  python3 tools/devig.py edge --odds 2.10 3.40 3.60 --model 0.52 0.26 0.22 --w 0.75 --pick 0
"""

from __future__ import annotations

import argparse
import math
from typing import List, Sequence, Tuple

# --------------------------------------------------------------------------
# 배당 변환
# --------------------------------------------------------------------------


def american_to_decimal(a: float) -> float:
    """미국식 배당 → 소수 배당."""
    if a == 0:
        raise ValueError("미국식 배당은 0이 될 수 없다")
    return 1.0 + (a / 100.0 if a > 0 else 100.0 / -a)


def raw_probs(odds: Sequence[float]) -> List[float]:
    """소수 배당 → 정규화 전 내재확률."""
    for o in odds:
        if o <= 1.0:
            raise ValueError(f"소수 배당은 1.0보다 커야 한다: {o}")
    return [1.0 / o for o in odds]


def booksum(odds: Sequence[float]) -> float:
    """오버라운드(합). 1.05면 마진 5%."""
    return sum(raw_probs(odds))


# --------------------------------------------------------------------------
# 마진 제거 3종
# --------------------------------------------------------------------------


def devig_proportional(odds: Sequence[float]) -> List[float]:
    """비례(승수) 방식. 기존 프롬프트가 쓰던 방식 — 비교용으로만 남긴다."""
    r = raw_probs(odds)
    s = sum(r)
    return [x / s for x in r]


def devig_power(odds: Sequence[float], tol: float = 1e-12) -> List[float]:
    """멱(power) 방식. p_i = r_i**k, sum(p) = 1이 되는 k를 이분법으로 찾는다."""
    r = raw_probs(odds)
    lo, hi = 0.2, 10.0
    for _ in range(200):
        k = 0.5 * (lo + hi)
        s = sum(x ** k for x in r)
        if abs(s - 1.0) < tol:
            break
        if s > 1.0:
            lo = k          # 합이 크면 k를 키워 확률을 줄인다
        else:
            hi = k
    k = 0.5 * (lo + hi)
    p = [x ** k for x in r]
    t = sum(p)
    return [x / t for x in p]


def devig_shin(odds: Sequence[float], tol: float = 1e-12) -> List[float]:
    """
    Shin(1992/1993) 방식. 북메이커가 정보우위 베터(z 비율)에 대비해
    마진을 붙인다고 보고 그 z를 역산한다.

        p_i = ( sqrt( z^2 + 4(1-z) * b_i^2 / B ) - z ) / ( 2(1-z) )

    b_i = 1/odds_i, B = sum(b_i), z는 sum(p_i) = 1을 만족하는 값.
    실증적으로 favourite-longshot bias를 가장 잘 잡아주는 축에 속하고,
    축구 1X2에서 비례 방식보다 안정적으로 낫다.
    """
    b = raw_probs(odds)
    B = sum(b)
    if B <= 1.0 + 1e-12:      # 마진이 없거나 음수(아비트리지)면 비례로 처리
        return devig_proportional(odds)

    def total(z: float) -> float:
        acc = 0.0
        for bi in b:
            inner = z * z + 4.0 * (1.0 - z) * bi * bi / B
            acc += (math.sqrt(max(inner, 0.0)) - z) / (2.0 * (1.0 - z))
        return acc

    lo, hi = 0.0, 0.5
    for _ in range(300):
        z = 0.5 * (lo + hi)
        s = total(z)
        if abs(s - 1.0) < tol:
            break
        if s > 1.0:
            lo = z            # z가 커질수록 합이 준다
        else:
            hi = z
    z = 0.5 * (lo + hi)
    p = []
    for bi in b:
        inner = z * z + 4.0 * (1.0 - z) * bi * bi / B
        p.append((math.sqrt(max(inner, 0.0)) - z) / (2.0 * (1.0 - z)))
    t = sum(p)
    return [x / t for x in p]


METHODS = {
    "shin": devig_shin,
    "power": devig_power,
    "proportional": devig_proportional,
}


def devig(odds: Sequence[float], method: str = "shin") -> List[float]:
    if method not in METHODS:
        raise ValueError(f"알 수 없는 방식: {method} (가능: {', '.join(METHODS)})")
    return METHODS[method](odds)


# --------------------------------------------------------------------------
# 블렌딩 · 엣지
# --------------------------------------------------------------------------


def blend(p_model: Sequence[float], p_market: Sequence[float],
          w_market: float = 0.75, max_dev_pp: float = 6.0) -> List[float]:
    """
    모델확률을 시장 공정확률 쪽으로 수축(shrink)시킨다.

    w_market  시장 가중치. 정보가 부족할수록 1.0에 가깝게 둔다.
    max_dev_pp 블렌딩 이후에도 시장 대비 이 %p 이상 벗어나지 못하게 자른다.

    클로징 라인은 공개 정보 기준으로 가장 강한 단일 예측자다.
    텍스트 분석이 그것을 통째로 이길 확률은 낮으므로, 모델은 '이동 폭'만
    담당하게 하고 위치는 시장에 맡긴다. 이 한 가지가 적중률보다
    확률 캘리브레이션을 가장 크게 개선한다.
    """
    if len(p_model) != len(p_market):
        raise ValueError("모델확률과 시장확률의 길이가 다르다")
    if not 0.0 <= w_market <= 1.0:
        raise ValueError("w_market은 0~1 사이여야 한다")

    cap = max_dev_pp / 100.0
    out = []
    for pm, pk in zip(p_model, p_market):
        v = w_market * pk + (1.0 - w_market) * pm
        v = min(max(v, pk - cap), pk + cap)
        out.append(min(max(v, 1e-6), 1.0 - 1e-6))
    t = sum(out)
    return [x / t for x in out]


def edge_pp(p_final: float, p_market: float) -> float:
    """엣지(%p). 블렌딩 이후 확률과 시장 공정확률의 차이."""
    return (p_final - p_market) * 100.0


def kelly_fraction(p: float, odds: float, cap: float = 0.02) -> float:
    """켈리 비율. cap으로 상한을 두는 프랙셔널 켈리 권장."""
    b = odds - 1.0
    if b <= 0:
        return 0.0
    f = (p * b - (1.0 - p)) / b
    return max(0.0, min(f, cap))


def fair_odds(p: float) -> float:
    return float("inf") if p <= 0 else 1.0 / p


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def _fmt(labels: Sequence[str], probs: Sequence[float]) -> str:
    rows = []
    for lab, p in zip(labels, probs):
        rows.append(f"  {lab:<10} {p * 100:6.2f}%   공정배당 {fair_odds(p):6.3f}")
    return "\n".join(rows)


def _cmd_market(args, labels: Sequence[str]) -> Tuple[List[float], List[str]]:
    odds = args.odds
    if len(odds) != len(labels):
        raise SystemExit(f"배당 {len(labels)}개가 필요하다")
    B = booksum(odds)
    lines = [f"오버라운드 {B * 100:.2f}%  (마진 {(B - 1) * 100:.2f}%)", ""]
    for name in ("shin", "power", "proportional"):
        p = devig(odds, name)
        lines.append(f"[{name}]")
        lines.append(_fmt(labels, p))
        lines.append("")
    shin = devig(odds, "shin")
    prop = devig(odds, "proportional")
    diff = max(abs(a - b) for a, b in zip(shin, prop)) * 100
    lines.append(f"shin vs proportional 최대 격차: {diff:.2f}%p")
    if diff >= 1.5:
        lines.append("→ 방식 차이만으로 이 정도가 벌어진다. 이 크기 이하의 '엣지'는 신호가 아니다.")
    return shin, lines


def main() -> None:
    ap = argparse.ArgumentParser(description="배당 마진 제거 · 블렌딩 · 엣지 계산")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p1 = sub.add_parser("1x2", help="홈/무/원정 3-way")
    p1.add_argument("odds", type=float, nargs=3, metavar=("홈", "무", "원정"))

    p2 = sub.add_parser("2way", help="핸디캡·언오버 등 2-way")
    p2.add_argument("odds", type=float, nargs=2, metavar=("A", "B"))

    p3 = sub.add_parser("edge", help="시장 대비 엣지 계산")
    p3.add_argument("--odds", type=float, nargs="+", required=True, help="시장 배당")
    p3.add_argument("--model", type=float, nargs="+", required=True, help="모델 추정확률(0~1)")
    p3.add_argument("--w", type=float, default=0.75, help="시장 가중치 (기본 0.75)")
    p3.add_argument("--maxdev", type=float, default=6.0, help="시장 대비 최대 이탈 %%p (기본 6)")
    p3.add_argument("--pick", type=int, default=None, help="선택 인덱스(0부터). 켈리까지 출력")
    p3.add_argument("--method", default="shin", choices=list(METHODS))

    args = ap.parse_args()

    if args.cmd == "1x2":
        _, lines = _cmd_market(args, ["홈승", "무승부", "원정승"])
        print("\n".join(lines))
        return

    if args.cmd == "2way":
        _, lines = _cmd_market(args, ["A", "B"])
        print("\n".join(lines))
        return

    # edge
    if len(args.odds) != len(args.model):
        raise SystemExit("배당 개수와 모델확률 개수가 같아야 한다")
    ms = sum(args.model)
    if abs(ms - 1.0) > 0.02:
        raise SystemExit(f"모델확률 합이 {ms:.4f}다. 1.0으로 맞춰라.")
    model = [x / ms for x in args.model]

    market = devig(args.odds, args.method)
    final = blend(model, market, w_market=args.w, max_dev_pp=args.maxdev)

    print(f"마진 제거: {args.method} / 시장가중치 w={args.w} / 이탈상한 {args.maxdev}%p")
    print(f"오버라운드 {booksum(args.odds) * 100:.2f}%\n")
    print(f"  {'#':<3}{'배당':>8}{'시장':>9}{'모델':>9}{'최종':>9}{'엣지':>9}")
    for i, o in enumerate(args.odds):
        e = edge_pp(final[i], market[i])
        print(f"  {i:<3}{o:>8.2f}{market[i] * 100:>8.2f}%{model[i] * 100:>8.2f}%"
              f"{final[i] * 100:>8.2f}%{e:>8.2f}p")

    if args.pick is not None:
        i = args.pick
        e = edge_pp(final[i], market[i])
        k = kelly_fraction(final[i], args.odds[i])
        print(f"\n선택 #{i}: 최종 {final[i] * 100:.2f}% / 엣지 {e:+.2f}%p "
              f"/ 공정배당 {fair_odds(final[i]):.3f} / 제시배당 {args.odds[i]:.2f}")
        print(f"켈리(2% 상한) {k * 100:.2f}% 뱅크롤")
        if e < 2.5:
            print("판정: PASS — 엣지가 마진 제거 오차 수준이다.")
        elif e < 4.0:
            print("판정: 부주력까지만.")
        else:
            print("판정: 주력 검토 가능(정보 게이트 통과 시).")


if __name__ == "__main__":
    main()
