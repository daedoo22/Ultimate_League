#!/usr/bin/env python3
"""얼티미트 리그전 4개 팀 제비뽑기 프로그램"""

from __future__ import annotations

import argparse
import random
from pathlib import Path
from typing import List

TEAM_COUNT = 4


def split_into_teams(names: List[str], team_count: int = TEAM_COUNT) -> List[List[str]]:
    """이름 목록을 섞은 뒤 팀 수만큼 균등하게 나눕니다."""
    if len(names) < team_count:
        raise ValueError(f"최소 {team_count}명 이상이 필요합니다.")

    shuffled = names[:]
    random.shuffle(shuffled)

    teams = [[] for _ in range(team_count)]
    for idx, name in enumerate(shuffled):
        teams[idx % team_count].append(name)

    return teams


def parse_names(raw_text: str) -> List[str]:
    """쉼표/줄바꿈 기준으로 이름 목록을 파싱합니다."""
    normalized = raw_text.replace("\n", ",")
    return [name.strip() for name in normalized.split(",") if name.strip()]


def load_names_from_file(file_path: str) -> List[str]:
    """텍스트 파일에서 이름 목록을 읽어옵니다."""
    content = Path(file_path).read_text(encoding="utf-8")
    return parse_names(content)


def print_teams(teams: List[List[str]]) -> None:
    print("\n🎯 제비뽑기 결과")
    print("=" * 30)
    for i, members in enumerate(teams, start=1):
        print(f"팀 {i} ({len(members)}명)")
        for member in members:
            print(f"  - {member}")
        print("-" * 30)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="참가자 이름을 받아 4개 팀으로 무작위 배정합니다."
    )
    parser.add_argument(
        "--file",
        help="명렬표 텍스트 파일 경로 (이름은 쉼표 또는 줄바꿈으로 구분)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        help="랜덤 시드 (같은 결과 재현이 필요할 때 사용)",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    print("얼티미트 리그전 팀 제비뽑기 프로그램")

    if args.seed is not None:
        random.seed(args.seed)

    try:
        if args.file:
            names = load_names_from_file(args.file)
            print(f"파일에서 명렬표를 읽었습니다: {args.file}")
        else:
            print(f"참가자 이름을 쉼표(,)로 입력하세요. (최소 {TEAM_COUNT}명)")
            raw = input("입력: ").strip()
            names = parse_names(raw)

        teams = split_into_teams(names)
    except FileNotFoundError:
        print("\n❌ 오류: 명렬표 파일을 찾을 수 없습니다.")
        return
    except ValueError as error:
        print(f"\n❌ 오류: {error}")
        return

    print_teams(teams)


if __name__ == "__main__":
    main()
