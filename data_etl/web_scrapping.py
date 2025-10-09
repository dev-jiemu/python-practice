import requests
from bs4 import BeautifulSoup
import pandas as pd
import time
from collections import Counter
import re
from datetime import datetime, timedelta

def crawl_naver_news(keyword, pages=5):
    # 크롤링 차단 방지용 header 설정
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }

    articles = []
    print(f"'{keyword}' 키워드로 뉴스 수집 중...")

    for page in range(1, pages + 1):
        start = (page - 1) * 10 + 1
        url = f"https://search.naver.com/search.naver?where=news&query={keyword}&sort=1&ds=&de=&nso=so:dd,p:1w&start={start}"

        try:
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')

            # Profile(언론사/날짜) + 본문(제목) 세트로 구성

            # 언론사, 날짜 정보 추출
            profiles = soup.select('div[data-sds-comp="Profile"]')
            # 제목, 요약 정보 추출
            news_contents = soup.select('span.sds-comps-text-type-headline1')

            print(f"{page}페이지 - Profile: {len(profiles)}개, 제목: {len(news_contents)}개")
            for idx, title_elem in enumerate(news_contents):
                try:
                    # mark 태그는 제거할 것

                    # 제목
                    title = title_elem.get_text(strip=True)
                    title = re.sub(r'<mark>|</mark>', '', title)

                    # 제목 요소의 부모에서 요약문 찾기
                    parent = title_elem.find_parent('div', class_='sds-comps-vertical-layout')
                    summary = "요약문 없음"
                    if parent:
                        summary_elem = parent.select_one('span.sds-comps-text-type-body1')
                        if summary_elem:
                            summary = summary_elem.get_text(strip=True)
                            summary = re.sub(r'<mark>|</mark>', '', summary)

                    # 해당하는 Profile 정보 가져오기
                    press = "언론사 정보 없음"
                    date = "날짜 정보 없음"

                    if idx < len(profiles):
                        profile = profiles[idx]

                        # 언론사
                        press_elem = profile.select_one('span.sds-comps-text-type-body2.sds-comps-text-weight-sm')
                        if press_elem:
                            press = press_elem.get_text(strip=True)

                        # 날짜
                        date_elem = profile.select_one('span.sds-comps-profile-info-subtext span.sds-comps-text')
                        if date_elem:
                            date = date_elem.get_text(strip=True)

                    articles.append({
                        '제목': title,
                        '언론사': press,
                        '날짜': date,
                        '요약문': summary
                    })

                except Exception as e:
                    print(f"개별 기사 파싱 오류: {e}")
                    continue

            print(f"  → {page}페이지 수집 완료 (누적 {len(articles)}개)")
            time.sleep(1)

        except Exception as e:
            print(f"{page}페이지 요청 오류: {e}")
            continue

    print(f"\n✅ 총 {len(articles)}개 기사 수집 완료!")
    return articles


def process_and_save_data(articles, title):
    # 빈 리스트 체크
    if not articles:
        print("수집된 기사가 없습니다. 키워드나 페이지 수를 조정해보세요.")
        return pd.DataFrame()

    df = pd.DataFrame(articles)

    # 날짜 데이터 정제 (포맷 변경)
    df['날짜_정제'] = df['날짜'].apply(parse_date)

    # CSV 저장
    filename = f'naver_news_{title}_{datetime.now().strftime("%Y%m%d")}.csv'
    df.to_csv(filename, index=False, encoding='utf-8-sig')
    print(f"\n데이터가 '{filename}' 파일로 저장되었습니다.")

    return df


def parse_date(date_str):
    now = datetime.now()

    if '분' in date_str or '시간' in date_str:
        return now.strftime('%Y-%m-%d')
    elif '일' in date_str:
        try:
            days = int(re.search(r'(\d+)일', date_str).group(1))
            return (now - timedelta(days=days)).strftime('%Y-%m-%d')
        except:
            return date_str
    else:
        return date_str


def analyze_data(df):
    if df.empty:
        print("분석할 데이터가 없습니다.")
        return

    print("\n" + "=" * 50)
    print("데이터 분석 결과")
    print("=" * 50)

    # 일자별 기사 수 집계
    print("\n[1] 일자별 기사 수")
    date_counts = df['날짜_정제'].value_counts().sort_index()
    print(date_counts)

    # 언론사별 기사 수 TOP 10
    print("\n[2] 언론사별 기사 수 TOP 10")
    press_counts = df['언론사'].value_counts().head(10)
    print(press_counts)

    # 제목에서 가장 많이 등장한 단어 TOP 20
    print("\n[3] 제목 키워드 TOP 20")
    top_words = extract_keywords(df['제목'])
    for i, (word, count) in enumerate(top_words, 1):
        print(f"{i}. {word}: {count}회")


def extract_keywords(titles):
    # 불용어 리스트
    stopwords = {
        '의', '가', '이', '은', '들', '는', '좀', '잘', '걍', '과', '도', '를', '으로', '자',
        '에', '와', '한', '하다', '을', '를', '에서', '으로', '와', '과', '의', '로', '등',
        '및', '더', '것', '수', '등', '년', '월', '일', '위해', '통해', '대한', '하는',
        '있는', '있다', '되다', '된다', '많은', '크다', '작다', '좋다', '나쁘다'
    }

    words = []
    for title in titles:
        # 한글, 영문, 숫자만 추출
        cleaned = re.sub(r'[^가-힣a-zA-Z0-9\s]', ' ', title)
        # 단어 분리 (2글자 이상)
        tokens = [word for word in cleaned.split() if len(word) >= 2]
        # 불용어 제외
        tokens = [word for word in tokens if word not in stopwords]
        words.extend(tokens)
    word_counts = Counter(words)
    return word_counts.most_common(20)


if __name__ == "__main__":
    keyword = "박스오피스"

    articles = crawl_naver_news(keyword, pages=10)

    if len(articles) >= 50:
        print(f"\n✅ 목표 달성: {len(articles)}개 기사 수집!")
    else:
        print(f"\n⚠️ {len(articles)}개 기사 수집됨. 페이지 수를 늘리거나 키워드를 조정해보세요.")

    # 데이터 처리 및 저장
    df = process_and_save_data(articles, keyword)

    # 데이터 분석
    if not df.empty:
        analyze_data(df)

        # 데이터 미리보기
        print("\n" + "=" * 50)
        print("수집된 데이터 샘플 (처음 5개)")
        print("=" * 50)
        print(df.head())
