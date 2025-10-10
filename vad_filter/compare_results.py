#!/usr/bin/env python3
"""
Go와 Python VAD 결과 비교 스크립트
두 버전의 출력을 파싱해서 음성 구간을 비교합니다.
"""

import re
import sys


def parse_segments(text):
    """로그에서 음성 구간 파싱"""
    segments = []
    pattern = r'음성 구간 (\d+): ([\d.]+)s ~ ([\d.]+)s \(([\d.]+)s\)'
    
    for match in re.finditer(pattern, text):
        segments.append({
            'id': int(match.group(1)),
            'start': float(match.group(2)),
            'end': float(match.group(3)),
            'duration': float(match.group(4))
        })
    
    return segments


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
    
    # 각 구간 비교
    max_len = max(len(go_segments), len(python_segments))
    differences = []
    
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
    for i in range(min(len(go_segments), len(python_segments))):
        start_diff = abs(go_segments[i]['start'] - python_segments[i]['start'])
        end_diff = abs(go_segments[i]['end'] - python_segments[i]['end'])
        if start_diff <= tolerance_sec and end_diff <= tolerance_sec:
            matched += 1
    
    print(f"일치하는 구간: {matched}/{min(len(go_segments), len(python_segments))}")
    
    if matched > 0:
        print(f"일치율: {matched/min(len(go_segments), len(python_segments))*100:.1f}%")
    
    if differences:
        print(f"\n차이점 상세:")
        for diff in differences:
            if diff[0] == 'Go만':
                print(f"  - 구간 {diff[1]}: Go에만 존재")
            elif diff[0] == 'Python만':
                print(f"  - 구간 {diff[1]}: Python에만 존재")
            else:
                print(f"  - 구간 {diff[1]}: Start 차이 {diff[2]:.0f}ms, End 차이 {diff[3]:.0f}ms")
    else:
        print("\n🎉 모든 구간이 일치합니다!")


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
    
    if not go_segments:
        print("❌ Go 출력에서 음성 구간을 찾을 수 없습니다.")
        sys.exit(1)
    
    if not python_segments:
        print("❌ Python 출력에서 음성 구간을 찾을 수 없습니다.")
        sys.exit(1)
    
    # 비교
    compare_segments(go_segments, python_segments)


if __name__ == '__main__':
    main()
