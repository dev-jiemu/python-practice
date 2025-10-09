import requests
import pandas as pd
import time
import re
import matplotlib.pyplot as plt
import seaborn as sns
import platform

# 운영체제별 한글 폰트 자동 설정
system = platform.system()
if system == 'Windows':
    plt.rcParams['font.family'] = 'Malgun Gothic'
elif system == 'Darwin':  # Mac OS
    plt.rcParams['font.family'] = 'AppleGothic'
else:  # Linux
    plt.rcParams['font.family'] = 'NanumGothic'

plt.rcParams['axes.unicode_minus'] = False

# Extract
def extract_api_data():
    base_url = "http://openapi.seoul.go.kr:8088"
    api_key = "" # TODO : api-key insert plz
    service = "TbPublicWifiInfo_GN"
    data_type = "json"

    all_data = []
    batch_size = 1000

    # 일단 한번 호출해보고, total_count 값 확인해서 페이징 처리 조정
    first_url = f"{base_url}/{api_key}/{data_type}/{service}/1/1/"

    try:
        print("📊 전체 데이터 개수 확인 중...")
        response = requests.get(first_url, timeout=10)
        response.raise_for_status()
        data = response.json()

        total_count = data.get(service, {}).get('list_total_count', 0)
        print(f"✅ 전체 데이터 개수: {total_count}건\n")

        if total_count == 0:
            print("⚠️ 수집할 데이터가 없습니다.")
            return []

    except Exception as e:
        print(f"❌ 초기 요청 오류: {e}")
        return []

    start_index = 1

    while start_index <= total_count:
        end_index = min(start_index + batch_size - 1, total_count)

        url = f"{base_url}/{api_key}/{data_type}/{service}/{start_index}/{end_index}/"

        try:
            print(f"📡{start_index}~{end_index}번 데이터 요청 중...")
            response = requests.get(url, timeout=10)
            response.raise_for_status()

            data = response.json()

            result = data.get(service, {}).get('RESULT', {})
            result_code = result.get('CODE', '')

            if result_code != 'INFO-000':
                print(f"⚠️ API 오류: {result.get('MESSAGE', '알 수 없는 오류')} (코드: {result_code})")
                break

            rows = data.get(service, {}).get('row', [])

            if not rows:
                print("⚠️ 응답에 데이터가 없습니다.")
                break

            all_data.extend(rows)
            print(f"  → {len(rows)}건 수집 완료 (누적: {len(all_data)}/{total_count}건)")

            start_index = end_index + 1

            if end_index >= total_count:
                print("✅ 모든 데이터 수집 완료!")
                break

            time.sleep(0.5)

        except requests.exceptions.RequestException as e:
            print(f"❌ 네트워크 오류: {e}")
            break
        except ValueError as e:
            print(f"❌ JSON 파싱 오류: {e}")
            break

    return all_data

# Transform
def transform_api_data(raw_data):
    if not raw_data:
        print("⚠️ 정제할 데이터가 없습니다.")
        return pd.DataFrame()

    df = pd.DataFrame(raw_data)
    print(f"📊 원본 데이터: {len(df)}건, {len(df.columns)}개 컬럼")

    columns_mapping = {
        'X_SWIFI_MGR_NO': '관리번호',
        'X_SWIFI_WRDOFC': '자치구',
        'X_SWIFI_MAIN_NM': '설치장소명',
        'X_SWIFI_ADRES1': '도로명주소',
        'X_SWIFI_ADRES2': '상세주소',
        'X_SWIFI_INSTL_FLOOR': '설치위치',
        'X_SWIFI_INSTL_TY': '설치유형',
        'X_SWIFI_INSTL_MBY': '설치기관',
        'X_SWIFI_SVC_SE': '서비스구분',
        'X_SWIFI_CMCWR': '망종류',
        'X_SWIFI_CNSTC_YEAR': '설치년도',
        'X_SWIFI_INOUT_DOOR': '실내외구분',
        'X_SWIFI_REMARS3': '비고',
        'LAT': '위도',
        'LNT': '경도',
        'WORK_DTTM': '작업일시',
    }

    df = df[list(columns_mapping.keys())].rename(columns=columns_mapping)
    print(f"✅ 컬럼 선택 완료: {len(df.columns)}개 컬럼")

    # 데이터 타입 변환
    print("\n[데이터 타입 변환]")
    df['위도'] = pd.to_numeric(df['위도'], errors='coerce')
    df['경도'] = pd.to_numeric(df['경도'], errors='coerce')
    df['설치년도'] = pd.to_numeric(df['설치년도'], errors='coerce')
    df['동'] = df['도로명주소'].apply(extract_dong)
    df['설치유형_간소화'] = df['설치유형'].apply(lambda x: x.split('-')[0].strip() if '-' in str(x) else x)

    return df

# 도로명 주소 매핑 : 동으로만 추출했다가 '기타' 로 너무 많이 분류되서 일부 보정
def extract_dong(address):
    address = str(address)

    match = re.search(r'(\w+동)', address)
    if match:
        return match.group(1)

    road_mapping = {
        '테헤란로': '역삼동',
        '강남대로': '역삼동',
        '언주로': '논현동',
        '봉은사로': '삼성동',
        '영동대로': '삼성동',
        '선릉로': '역삼동',
        '도곡로': '도곡동',
        '개포로': '개포동',
        '양재천로': '양재동',
        '학동로': '논현동',
        '압구정로': '압구정동',
        '남부순환로': '도곡동',
        '헌릉로': '일원동',
        '광평로': '수서동',
        '밤고개로': '수서동',
        '개포동': '개포동',
        '자곡로': '자곡동',
    }

    for road, dong in road_mapping.items():
        if road in address:
            return dong

    return '기타'

# Load
def load_to_csv(df, filename='gangnam_wifi_data.csv'):
    if df.empty:
        print("⚠️ 저장할 데이터가 없습니다.")
        return

    df.to_csv(filename, index=False, encoding='utf-8-sig')
    print(f"💾 '{filename}' 파일로 저장 완료!")

# visualize for matplotlib, seaborn
def visualize_data(df):
    # 상위 15개 추출
    plt.figure(figsize=(12, 6))
    dong_counts = df['동'].value_counts().head(15)

    sns.barplot(x=dong_counts.values, y=dong_counts.index, palette='viridis')
    plt.title('강남구 동별 공공와이파이 설치 개수 TOP 15', fontsize=16, fontweight='bold')
    plt.xlabel('설치 개수', fontsize=12)
    plt.ylabel('동', fontsize=12)

    # 막대에 숫자 표시
    for i, v in enumerate(dong_counts.values):
        plt.text(v + 5, i, str(v), va='center', fontsize=10)

    plt.tight_layout()
    plt.savefig('visualization_1_dong_distribution.png', dpi=300, bbox_inches='tight')
    print("  ✅ 저장: visualization_1_dong_distribution.png")
    plt.show()

    print("연도별 와이파이 설치 추이")
    plt.figure(figsize=(12, 6))
    year_counts = df['설치년도'].value_counts().sort_index()

    plt.plot(year_counts.index, year_counts.values, marker='o', linewidth=2, markersize=8, color='#2E86AB')
    plt.fill_between(year_counts.index, year_counts.values, alpha=0.3, color='#2E86AB')

    plt.title('강남구 공공와이파이 연도별 설치 추이', fontsize=16, fontweight='bold')
    plt.xlabel('설치년도', fontsize=12)
    plt.ylabel('설치 개수', fontsize=12)
    plt.grid(True, alpha=0.3, linestyle='--')

    # 각 점에 숫자 표시
    for x, y in zip(year_counts.index, year_counts.values):
        plt.text(x, y + 5, str(y), ha='center', fontsize=9)

    plt.tight_layout()
    plt.savefig('visualization_2_year_trend.png', dpi=300, bbox_inches='tight')
    print("  ✅ 저장: visualization_2_year_trend.png")
    plt.show()

if __name__ == "__main__":
    raw_data = extract_api_data()
    cleaned_df = transform_api_data(raw_data)
    load_to_csv(cleaned_df)

    if not cleaned_df.empty:
        print("\n" + "=" * 60)
        print("📊 정제된 데이터 샘플 (처음 5개)")
        print("=" * 60)
        print(cleaned_df.head())

        print("\n" + "=" * 60)
        print("📈 데이터 타입 정보")
        print("=" * 60)
        print(cleaned_df.info())

        print("\n" + "=" * 60)
        print("📋 기술 통계")
        print("=" * 60)
        print(cleaned_df.describe())

        print("\n" + "=" * 60)
        print("📊 통계 내보기")
        print("=" * 60)
        print(f"설치년도: 평균 {cleaned_df['설치년도'].mean():.0f}년, "
              f"{cleaned_df['설치년도'].min():.0f}~{cleaned_df['설치년도'].max():.0f}년")
        print(f"위도: {cleaned_df['위도'].min():.2f}~{cleaned_df['위도'].max():.2f} (강남구 범위)")
        print(f"경도: {cleaned_df['경도'].min():.2f}~{cleaned_df['경도'].max():.2f}")
        print("=" * 60)

        # 시각화
        visualize_data(cleaned_df)