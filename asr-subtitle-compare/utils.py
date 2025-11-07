import re
from dataclasses import dataclass
from typing import List

@dataclass
class SRTSegment:
    index: int
    start_time: float  # seconds
    end_time: float
    text: str

    @staticmethod
    def parse_time(time_str: str) -> float:
        """00:00:19,200 -> seconds"""
        time_str = time_str.strip()
        h, m, s = time_str.replace(',', '.').split(':')
        return int(h) * 3600 + int(m) * 60 + float(s)

    def format_time(self, seconds: float) -> str:
        """seconds -> 00:00:19.200"""
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = seconds % 60
        return f"{h:02d}:{m:02d}:{s:06.3f}"

    def time_str(self) -> str:
        return f"{self.format_time(self.start_time)} --> {self.format_time(self.end_time)}"


def parse_srt(filepath: str) -> List[SRTSegment]:
    segments = []
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read().strip().split('\n\n')

    for block in content:
        lines = block.strip().split('\n')
        if len(lines) >= 3:
            try:
                index = int(lines[0])
                times = lines[1].split(' --> ')
                start = SRTSegment.parse_time(times[0])
                end = SRTSegment.parse_time(times[1])
                text = ' '.join(lines[2:])
                segments.append(SRTSegment(index, start, end, text))
            except Exception as e:
                print(f"Warning: 파싱 실패한 블록: {lines[0] if lines else 'empty'}")
                continue

    return segments

def normalize_text(text: str) -> str:
    """텍스트 정규화"""
    text = text.lower()
    text = re.sub(r'[^\w\s]', '', text)  # 구두점 제거
    text = re.sub(r'\s+', ' ', text)  # 공백 정규화
    return text.strip()

def calculate_wer(reference: List[str], hypothesis: List[str]) -> float:
    """Word Error Rate 계산 (Levenshtein 거리 기반)"""
    if len(reference) == 0:
        return 100.0 if len(hypothesis) > 0 else 0.0

    d = [[0] * (len(hypothesis) + 1) for _ in range(len(reference) + 1)]

    for i in range(len(reference) + 1):
        d[i][0] = i
    for j in range(len(hypothesis) + 1):
        d[0][j] = j

    for i in range(1, len(reference) + 1):
        for j in range(1, len(hypothesis) + 1):
            if reference[i-1] == hypothesis[j-1]:
                d[i][j] = d[i-1][j-1]
            else:
                substitution = d[i-1][j-1] + 1
                insertion = d[i][j-1] + 1
                deletion = d[i-1][j] + 1
                d[i][j] = min(substitution, insertion, deletion)

    return (d[len(reference)][len(hypothesis)] / len(reference)) * 100