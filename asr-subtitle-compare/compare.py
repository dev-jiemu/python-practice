# ASR 모델로 뽑은 자막 데이터 비교
# VAD Filter 포함, 미포함 둘다 비교
from difflib import SequenceMatcher
from typing import List, Tuple
from utils import parse_srt, normalize_text, calculate_wer, SRTSegment

def timeline_analysis(seg1: List[SRTSegment], seg2: List[SRTSegment], label1: str, label2: str):
    print(f"⏱️ 타임라인 분석:")
    print(f"   - {label1}: {seg1[0].start_time:.3f}s ~ {seg1[-1].end_time:.3f}s")
    print(f"   - {label2}: {seg2[0].start_time:.3f}s ~ {seg2[-1].end_time:.3f}s")
    print(f"   - 시작 시간 차이: {abs(seg1[0].start_time - seg2[0].start_time)*1000:.0f}ms")
    print(f"   - 종료 시간 차이: {abs(seg1[-1].end_time - seg2[-1].end_time)*1000:.0f}ms\n")


def segment_analysis(seg1: List[SRTSegment], seg2: List[SRTSegment], label1: str, label2: str):
    avg_duration1 = sum([s.end_time - s.start_time for s in seg1]) / len(seg1)
    avg_duration2 = sum([s.end_time - s.start_time for s in seg2]) / len(seg2)

    avg_words1 = sum([len(s.text.split()) for s in seg1]) / len(seg1)
    avg_words2 = sum([len(s.text.split()) for s in seg2]) / len(seg2)

    print(f"📋 세그먼트 구조:")
    print(f"   - {label1}: {len(seg1)}개 세그먼트")
    print(f"      평균 길이: {avg_duration1:.2f}초, 평균 {avg_words1:.1f} 단어")
    print(f"   - {label2}: {len(seg2)}개 세그먼트")
    print(f"      평균 길이: {avg_duration2:.2f}초, 평균 {avg_words2:.1f} 단어\n")

def compare_srt_files(file1: str, file2:str, label1: str, label2: str):
    segments1 = parse_srt(file1)
    segments2 = parse_srt(file2)

    # 1. 전체 텍스트 추출
    text1 = ' '.join([s.text for s in segments1])
    text2 = ' '.join([s.text for s in segments2])

    text1_norm = normalize_text(text1)
    text2_norm = normalize_text(text2)

    # 2. 텍스트 유사도 (SequenceMatcher)
    similarity = SequenceMatcher(None, text1_norm, text2_norm).ratio()

    print(f"=== {label1} vs {label2} ===\n")
    print(f"📊 전체 텍스트 유사도: {similarity * 100:.2f}%\n")

    # 3. 단어 수준 비교 (WER 계산)
    words1 = text1_norm.split()
    words2 = text2_norm.split()

    wer = calculate_wer(words1, words2)
    print(f"📝 단어 오류율 (WER): {wer:.2f}%")
    print(f"   - {label1}: {len(words1)} 단어")
    print(f"   - {label2}: {len(words2)} 단어\n")

    # 4. 타임라인 비교
    timeline_analysis(segments1, segments2, label1, label2)

    # 5. 세그먼트 구조 비교
    segment_analysis(segments1, segments2, label1, label2)

    return {
        'similarity': similarity,
        'wer': wer,
        'segments_count': (len(segments1), len(segments2)),
        'words_count': (len(words1), len(words2))
    }

if __name__ == '__main__':
    diff_srt_1 = "./compare/canary.srt"
    diff_srt_1_label = "Canary"
    diff_srt_2 = "./compare/canary_filtered.srt"
    diff_srt_2_label = "Canary VAD Filter"

    _ = compare_srt_files(diff_srt_1, diff_srt_2, diff_srt_1_label, diff_srt_2_label)