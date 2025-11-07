from difflib import SequenceMatcher
from typing import List, Dict, Set, Tuple
import json
from utils import parse_srt, normalize_text, SRTSegment

def find_all_overlapping_segments(seg: SRTSegment, segments: List[SRTSegment], threshold: float = 0.2) -> List[SRTSegment]:
    """시간적으로 겹치는 모든 세그먼트 찾기 (1:N 매칭 가능)"""
    overlapping = []
    for other_seg in segments:
        overlap_start = max(seg.start_time, other_seg.start_time)
        overlap_end = min(seg.end_time, other_seg.end_time)
        overlap_duration = max(0, overlap_end - overlap_start)

        seg_duration = seg.end_time - seg.start_time
        other_duration = other_seg.end_time - other_seg.start_time

        if seg_duration > 0 and other_duration > 0:
            # 둘 중 짧은 세그먼트 기준으로 겹침 비율 계산
            overlap_ratio = overlap_duration / min(seg_duration, other_duration)
            if overlap_ratio >= threshold:
                overlapping.append(other_seg)

    return overlapping

def find_text_based_match(seg: SRTSegment, segments: List[SRTSegment], threshold: float = 0.85) -> Tuple[SRTSegment, float]:
    text1_norm = normalize_text(seg.text)

    best_match = None
    best_similarity = 0.0

    for other_seg in segments:
        text2_norm = normalize_text(other_seg.text)
        similarity = SequenceMatcher(None, text1_norm, text2_norm).ratio()

        if similarity > best_similarity and similarity >= threshold:
            best_similarity = similarity
            best_match = other_seg

    return best_match, best_similarity

def detect_segment_patterns(segments1: List[SRTSegment], segments2: List[SRTSegment]):
    """세그먼트 병합/분할 패턴 감지"""

    patterns = {
        'one_to_one': [],      # 1:1 매칭
        'merged': [],           # N:1 (여러개가 하나로 합쳐짐)
        'split': [],            # 1:N (하나가 여러개로 쪼개짐)
        'missing': [],          # 매칭 없음 (실제 손실)
        'text_diff_only': [],   # 세그먼트는 매칭되지만 텍스트만 다름
        'timeline_mismatch': [], # 타임라인이 다름
    }

    matched_seg2_indices = set()

    for seg1 in segments1:
        overlapping = find_all_overlapping_segments(seg1, segments2, threshold=0.2)

        if len(overlapping) == 0:
            # 매칭되는 세그먼트가 없음
            text_match, similarity = find_text_based_match(seg1, segments2, threshold=0.85)
            if text_match:
                # 타임라인은 안 맞지만 텍스트는 일치
                matched_seg2_indices.add(text_match.index)
                patterns['timeline_mismatch'].append({
                    'seg1': seg1,
                    'seg2': text_match,
                    'similarity': similarity,
                    'time_diff_ms': abs((seg1.start_time + seg1.end_time)/2 -
                                        (text_match.start_time + text_match.end_time)/2)
                })
            else:
                patterns['missing'].append({
                    'seg1': seg1,
                    'seg2_list': []
                })

        elif len(overlapping) == 1:
            # 1:1 매칭
            seg2 = overlapping[0]
            matched_seg2_indices.add(seg2.index)

            text1_norm = normalize_text(seg1.text)
            text2_norm = normalize_text(seg2.text)
            similarity = SequenceMatcher(None, text1_norm, text2_norm).ratio()

            if similarity < 0.95:  # 5% 이상 차이
                patterns['text_diff_only'].append({
                    'seg1': seg1,
                    'seg2': seg2,
                    'similarity': similarity
                })
            else:
                patterns['one_to_one'].append({
                    'seg1': seg1,
                    'seg2': seg2,
                    'similarity': similarity
                })
        else:
            # 1:N 매칭 전에 텍스트 유사도 체크
            exact_match = None
            for seg2 in overlapping:
                text1_norm = normalize_text(seg1.text)
                text2_norm = normalize_text(seg2.text)
                if SequenceMatcher(None, text1_norm, text2_norm).ratio() > 0.95:
                    exact_match = seg2
                    break

            if exact_match:
                # 실제로는 1:1 매칭
                matched_seg2_indices.add(exact_match.index)
                patterns['one_to_one'].append({
                    'seg1': seg1,
                    'seg2': exact_match,
                    'similarity': 1.0
                })
            else:
                # 진짜 분할
                for seg2 in overlapping:
                    matched_seg2_indices.add(seg2.index)
                patterns['split'].append({
                    'seg1': seg1,
                    'seg2_list': overlapping
                })

    # segments2에서 매칭 안 된 것들 찾기 (역방향 체크 - 병합 감지)
    for seg2 in segments2:
        if seg2.index not in matched_seg2_indices:
            # 이 seg2와 겹치는 seg1들 찾기
            overlapping_seg1 = find_all_overlapping_segments(seg2, segments1, threshold=0.2)

            if len(overlapping_seg1) > 1:
                # N:1 매칭 (병합)
                patterns['merged'].append({
                    'seg1_list': overlapping_seg1,
                    'seg2': seg2
                })

    return patterns

def analyze_segment_patterns(patterns: Dict):
    """패턴 분석 및 리포트 생성"""

    print("="*80)
    print("  🔍 세그먼트 매칭 패턴 분석")
    print("="*80)
    print()

    print("【 매칭 패턴 통계 】")
    print(f"  ✅ 1:1 매칭 (거의 동일): {len(patterns['one_to_one'])}개")
    print(f"  📝 1:1 매칭 (텍스트 차이): {len(patterns['text_diff_only'])}개")
    print(f"  🔀 분할 (1→N): {len(patterns['split'])}개")
    print(f"  🔗 병합 (N→1): {len(patterns['merged'])}개")
    print(f"  ❌ 매칭 없음 (실제 손실): {len(patterns['missing'])}개")
    print(f"  ⏱️ 타임라인 불일치 (텍스트 일치): {len(patterns['timeline_mismatch'])}개")
    print()

    # 분할 상세 분석
    if patterns['split']:
        print("【 분할 사례 상세 (상위 5개) 】")
        for i, item in enumerate(patterns['split'][:5], 1):
            seg1 = item['seg1']
            seg2_list = item['seg2_list']
            print(f"\n{i}. 원본 1개 → VAD {len(seg2_list)}개로 분할")
            print(f"   원본 #{seg1.index}: [{seg1.time_str()}]")
            print(f"   → {seg1.text}")
            print(f"   VAD 세그먼트들:")
            for seg2 in seg2_list:
                print(f"     #{seg2.index}: [{seg2.time_str()}]")
                print(f"     → {seg2.text}")
        print()

    # 병합 상세 분석
    if patterns['merged']:
        print("【 병합 사례 상세 (상위 5개) 】")
        for i, item in enumerate(patterns['merged'][:5], 1):
            seg1_list = item['seg1_list']
            seg2 = item['seg2']
            print(f"\n{i}. 원본 {len(seg1_list)}개 → VAD 1개로 병합")
            print(f"   원본 세그먼트들:")
            for seg1 in seg1_list:
                print(f"     #{seg1.index}: [{seg1.time_str()}]")
                print(f"     → {seg1.text}")
            print(f"   VAD #{seg2.index}: [{seg2.time_str()}]")
            print(f"   → {seg2.text}")
        print()

    # 실제 손실 분석
    if patterns['missing']:
        print("【 실제 손실 사례 (상위 5개) 】")
        for i, item in enumerate(patterns['missing'][:5], 1):
            seg1 = item['seg1']
            print(f"\n{i}. 원본 #{seg1.index}: [{seg1.time_str()}]")
            print(f"   → {seg1.text}")
        print()

    # 텍스트 차이만 있는 경우
    if patterns['text_diff_only']:
        print("【 텍스트 차이 사례 (유사도 낮은 상위 5개) 】")
        sorted_diffs = sorted(patterns['text_diff_only'], key=lambda x: x['similarity'])

        for i, item in enumerate(sorted_diffs[:5], 1):
            seg1 = item['seg1']
            seg2 = item['seg2']
            sim = item['similarity']
            print(f"\n{i}. 유사도 {sim*100:.1f}% (#{seg1.index} ↔ #{seg2.index})")
            print(f"   원본: {seg1.text}")
            print(f"   VAD:  {seg2.text}")
        print()

    # 타임라인 불일치 상세체크
    if patterns['timeline_mismatch']:
        print("【 타임라인 불일치 사례 (상위 5개) 】")
        for i, item in enumerate(patterns['timeline_mismatch'][:5], 1):
            seg1 = item['seg1']
            seg2 = item['seg2']
            time_diff = item['time_diff_ms'] / 1000
            print(f"\n{i}. 시간 차이 {time_diff:.2f}초 (유사도 {item['similarity']*100:.1f}%)")
            print(f"   원본 #{seg1.index}: [{seg1.time_str()}]")
            print(f"   → {seg1.text}")
            print(f"   VAD #{seg2.index}: [{seg2.time_str()}]")
            print(f"   → {seg2.text}")
        print()

def generate_advanced_report(file1: str, file2: str, label1: str, label2: str, output_file: str = None):
    segments1 = parse_srt(file1)
    segments2 = parse_srt(file2)

    print("="*80)
    print(f"  고급 비교 리포트: {label1} vs {label2}")
    print("="*80)
    print()

    # 전체 통계
    total_words1 = sum(len(normalize_text(s.text).split()) for s in segments1)
    total_words2 = sum(len(normalize_text(s.text).split()) for s in segments2)

    print(f"📊 기본 통계:")
    print(f"   {label1}: {len(segments1)}개 세그먼트, {total_words1} 단어")
    print(f"   {label2}: {len(segments2)}개 세그먼트, {total_words2} 단어")
    print(f"   세그먼트 차이: {len(segments1) - len(segments2):+d}개")
    print(f"   단어 차이: {total_words1 - total_words2:+d}개")
    print(f"   단어 손실률: {((total_words1-total_words2)/total_words1*100):.1f}%")
    print()

    # 패턴 감지
    patterns = detect_segment_patterns(segments1, segments2)

    # 패턴 분석
    analyze_segment_patterns(patterns)

    # JSON 저장
    if output_file:
        report_data = {
            'summary': {
                'file1': file1,
                'file2': file2,
                'label1': label1,
                'label2': label2,
                'segments1': len(segments1),
                'segments2': len(segments2),
                'words1': total_words1,
                'words2': total_words2,
                'word_loss_rate': ((total_words1-total_words2)/total_words1*100)
            },
            'patterns': {
                'one_to_one_count': len(patterns['one_to_one']),
                'text_diff_count': len(patterns['text_diff_only']),
                'split_count': len(patterns['split']),
                'merged_count': len(patterns['merged']),
                'missing_count': len(patterns['missing'])
            },
            'details': {
                'missing': [
                    {
                        'seg1': {
                            'index': item['seg1'].index,
                            'time': item['seg1'].time_str(),
                            'text': item['seg1'].text
                        }
                    }
                    for item in patterns['missing']
                ],
                'text_diff_only': [
                    {
                        'seg1': {
                            'index': item['seg1'].index,
                            'time': item['seg1'].time_str(),
                            'text': item['seg1'].text
                        },
                        'seg2': {
                            'index': item['seg2'].index,
                            'time': item['seg2'].time_str(),
                            'text': item['seg2'].text
                        },
                        'similarity': item['similarity']
                    }
                    for item in patterns['text_diff_only']
                ],
                'split': [
                    {
                        'seg1': {
                            'index': item['seg1'].index,
                            'time': item['seg1'].time_str(),
                            'text': item['seg1'].text
                        },
                        'seg2_list': [
                            {
                                'index': seg.index,
                                'time': seg.time_str(),
                                'text': seg.text
                            }
                            for seg in item['seg2_list']
                        ]
                    }
                    for item in patterns['split']
                ],
                'merged': [
                    {
                        'seg1_list': [
                            {
                                'index': seg.index,
                                'time': seg.time_str(),
                                'text': seg.text
                            }
                            for seg in item['seg1_list']
                        ],
                        'seg2': {
                            'index': item['seg2'].index,
                            'time': item['seg2'].time_str(),
                            'text': item['seg2'].text
                        }
                    }
                    for item in patterns['merged']
                ]
            }
        }

        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(report_data, f, ensure_ascii=False, indent=2)

        print("="*80)
        print(f"✅ 리포트가 '{output_file}'에 저장되었습니다.")
        print("="*80)


if __name__ == '__main__':
    diff_srt_1 = "./compare/canary.srt"
    diff_srt_1_label = "Canary"
    diff_srt_2 = "./compare/canary_filtered.srt"
    diff_srt_2_label = "Canary VAD Filter"
    output_file = "./detailed_report_canary.json"

    generate_advanced_report(diff_srt_1, diff_srt_2, diff_srt_1_label, diff_srt_2_label, output_file)

