#!/usr/bin/env python3
"""
Go와 Python VAD 결과 비교 스크립트
두 버전의 출력을 파싱해서 음성 구간을 비교합니다.
"""

import re
import sys


def parse_segments(text):
    """로그에서 음성 구간 파싱 - 새로운 포맷"""
    segments = []
    # 새로운 포맷: "   1: 24.49s ~ 27.22s (2.73s)"
    pattern = r'\s+(\d+):\s+([\d.]+)s\s+~\s+([\d.]+)s\s+\(([\d.]+)s\)'

    for match in re.finditer(pattern, text):
        segments.append({
            'id': int(match.group(1)),
            'start': float(match.group(2)),
            'end': float(match.group(3)),
            'duration': float(match.group(4))
        })

    return segments


def parse_summary(text):
    """처리 결과 통계 파싱"""
    summary = {}

    # 전체 시간
    match = re.search(r'전체:\s+([\d.]+)s', text)
    if match:
        summary['total'] = float(match.group(1))

    # 음성 시간
    match = re.search(r'음성:\s+([\d.]+)s\s+\(([\d.]+)%\)', text)
    if match:
        summary['speech'] = float(match.group(1))
        summary['speech_pct'] = float(match.group(2))

    # 무음제거 시간
    match = re.search(r'무음제거:\s+([\d.]+)s\s+\(([\d.]+)%\)', text)
    if match:
        summary['silence'] = float(match.group(1))
        summary['silence_pct'] = float(match.group(2))

    return summary


def compare_segments(go_segments, python_segments, tolerance_ms=50):
    """두 버전의 구간 비교"""
    tolerance_sec = tolerance_ms / 1000.0

    print(f"\n{'='*60}")
    print("VAD 결과 비교")
    print(f"{'='*60}")
    print(f"Go 버전 음성 구간 수: {len(go_segments)}")
    print(f"Python 버전 음성 구간 수: {len(python_segments)}")
    print(f"허용 오차: ±{tolerance_ms}ms\n")

    if len(go_segments) != len(python_segments):
        print(f"⚠️  구간 개수가 다릅니다!")
        print(f"   Go: {len(go_segments)}개, Python: {len(python_segments)}개\n")

    # 둘 다 0개면 비교 스킵
    if len(go_segments) == 0 and len(python_segments) == 0:
        print("⚠️  양쪽 모두 음성 구간이 없습니다.\n")
        return

    # 각 구간 비교
    max_len = max(len(go_segments), len(python_segments))
    differences = []

    # 비교할 구간이 있으면 테이블 출력
    if max_len > 0:
        print(f"{'ID':>3} | {'Go Start':>9} | {'Py Start':>9} | {'Diff':>8} | {'Go End':>9} | {'Py End':>9} | {'Diff':>8} | {'Status':>10}")
        print("-" * 85)

        for i in range(max_len):
            if i >= len(go_segments):
                py_seg = python_segments[i]
                print(f"{i+1:>3} | {'N/A':>9} | {py_seg['start']:>9.2f} | {'N/A':>8} | {'N/A':>9} | {py_seg['end']:>9.2f} | {'N/A':>8} | {'Python만':>10}")
                differences.append(('Python만', i+1))
                continue

            if i >= len(python_segments):
                go_seg = go_segments[i]
                print(f"{i+1:>3} | {go_seg['start']:>9.2f} | {'N/A':>9} | {'N/A':>8} | {go_seg['end']:>9.2f} | {'N/A':>9} | {'N/A':>8} | {'Go만':>10}")
                differences.append(('Go만', i+1))
                continue

            go_seg = go_segments[i]
            py_seg = python_segments[i]

            start_diff = abs(go_seg['start'] - py_seg['start'])
            end_diff = abs(go_seg['end'] - py_seg['end'])

            start_ok = start_diff <= tolerance_sec
            end_ok = end_diff <= tolerance_sec

            status = "✅ 일치" if (start_ok and end_ok) else "❌ 차이"

            print(f"{i+1:>3} | {go_seg['start']:>9.2f} | {py_seg['start']:>9.2f} | {start_diff*1000:>7.0f}ms | "
                  f"{go_seg['end']:>9.2f} | {py_seg['end']:>9.2f} | {end_diff*1000:>7.0f}ms | {status:>10}")

            if not (start_ok and end_ok):
                differences.append(('차이', i+1, start_diff*1000, end_diff*1000))

    # 통계
    print(f"\n{'='*60}")
    print("통계")
    print(f"{'='*60}")

    matched = 0
    total_start_diff = 0.0
    total_end_diff = 0.0

    for i in range(min(len(go_segments), len(python_segments))):
        start_diff = abs(go_segments[i]['start'] - python_segments[i]['start'])
        end_diff = abs(go_segments[i]['end'] - python_segments[i]['end'])
        total_start_diff += start_diff
        total_end_diff += end_diff

        if start_diff <= tolerance_sec and end_diff <= tolerance_sec:
            matched += 1

    common_count = min(len(go_segments), len(python_segments))

    print(f"일치하는 구간: {matched}/{common_count}")

    if common_count > 0:
        print(f"일치율: {matched/common_count*100:.1f}%")
        print(f"평균 Start 차이: {total_start_diff/common_count*1000:.1f}ms")
        print(f"평균 End 차이: {total_end_diff/common_count*1000:.1f}ms")

    if differences:
        print(f"\n차이점 상세 (최대 10개):")
        for i, diff in enumerate(differences[:10]):
            if diff[0] == 'Go만':
                print(f"  - 구간 {diff[1]}: Go에만 존재")
            elif diff[0] == 'Python만':
                print(f"  - 구간 {diff[1]}: Python에만 존재")
            else:
                print(f"  - 구간 {diff[1]}: Start 차이 {diff[2]:.0f}ms, End 차이 {diff[3]:.0f}ms")

        if len(differences) > 10:
            print(f"  ... 외 {len(differences)-10}개 더 있음")
    elif common_count > 0:
        print("\n🎉 모든 구간이 일치합니다!")


def compare_summary(go_text, python_text):
    """처리 결과 통계 비교"""
    go_summary = parse_summary(go_text)
    python_summary = parse_summary(python_text)

    if not go_summary and not python_summary:
        return

    print(f"\n{'='*60}")
    print("처리 결과 통계 비교")
    print(f"{'='*60}")

    print(f"{'':15} | {'Go':>12} | {'Python':>12} | {'차이':>12}")
    print("-" * 60)

    if 'total' in go_summary and 'total' in python_summary:
        diff = go_summary['total'] - python_summary['total']
        print(f"{'전체 시간':15} | {go_summary['total']:>10.2f}s | {python_summary['total']:>10.2f}s | {diff:>10.2f}s")

    if 'speech' in go_summary and 'speech' in python_summary:
        diff = go_summary['speech'] - python_summary['speech']
        print(f"{'음성 시간':15} | {go_summary['speech']:>10.2f}s | {python_summary['speech']:>10.2f}s | {diff:>10.2f}s")

    if 'silence' in go_summary and 'silence' in python_summary:
        diff = go_summary['silence'] - python_summary['silence']
        print(f"{'무음 제거':15} | {go_summary['silence']:>10.2f}s | {python_summary['silence']:>10.2f}s | {diff:>10.2f}s")


def main():
    if len(sys.argv) != 3:
        print(f"사용법: {sys.argv[0]} <go_output.txt> <python_output.txt>")
        print("\n예시:")
        print("  1. Go 실행: go run *.go sample/arirang_1.mp3 > go_output.txt")
        print("  2. Python 실행: python vad_test.py ../sample/arirang_1.mp3 > python_output.txt")
        print("  3. 비교: python compare_results.py go_output.txt python_output.txt")
        sys.exit(1)

    go_file = sys.argv[1]
    python_file = sys.argv[2]

    # 파일 읽기
    try:
        with open(go_file, 'r', encoding='utf-8') as f:
            go_text = f.read()
    except Exception as e:
        print(f"❌ Go 출력 파일을 읽을 수 없습니다: {e}")
        sys.exit(1)

    try:
        with open(python_file, 'r', encoding='utf-8') as f:
            python_text = f.read()
    except Exception as e:
        print(f"❌ Python 출력 파일을 읽을 수 없습니다: {e}")
        sys.exit(1)

    # 구간 파싱
    go_segments = parse_segments(go_text)
    python_segments = parse_segments(python_text)

    # 파싱 실패 경고 (하지만 계속 진행)
    if not go_segments and "📋 최종 음성 구간:" in go_text:
        print("⚠️  Go 출력에서 음성 구간을 파싱할 수 없습니다.")
        print("   '📋 최종 음성 구간:' 섹션은 있지만 파싱 실패.\n")

    if not python_segments:
        print("⚠️  Python 출력에서 음성 구간을 파싱할 수 없습니다.\n")

    # 구간 비교 (0개여도 진행)
    compare_segments(go_segments, python_segments)

    # 통계 비교
    compare_summary(go_text, python_text)


if __name__ == '__main__':
    main()