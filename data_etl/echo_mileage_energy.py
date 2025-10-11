import pandas as pd
import requests
import platform
import time
import matplotlib.pyplot as plt

# 운영체제별 한글 폰트 자동 설정
system = platform.system()
if system == 'Windows':
    plt.rcParams['font.family'] = 'Malgun Gothic'
elif system == 'Darwin':  # Mac
    plt.rcParams['font.family'] = 'AppleGothic'
else:  # Linux
    plt.rcParams['font.family'] = 'NanumGothic'

plt.rcParams['axes.unicode_minus'] = False

# 소수점 2자리까지만 표현
pd.set_option('display.float_format', '{:.2f}'.format)

def extract_api_data(year, month):
    base_url = "http://openapi.seoul.go.kr:8088"
    api_key = "" # TODO : api key insert plz
    service = "energyUseDataSummaryInfo"
    data_type = "json"

    all_data = []
    batch_size = 10

    # url pattern : http://openapi.seoul.go.kr:8088/{api_key}/{data_type}/{service}/{start_index}/{end_index}/{month}/{day}
    # 일단 한번 호출해보고, total_count 값 확인해서 페이징 처리 조정
    first_url = f"{base_url}/{api_key}/{data_type}/{service}/1/1/{year}/{month}"

    print(f"{year}년 {month}월 에코 마일리지 데이터 조회")

    try:
        print("전체 데이터 개수 확인")
        response = requests.get(first_url, timeout=10)
        response.raise_for_status()
        data = response.json()

        total_count = data.get(service, {}).get('list_total_count', 0)
        print(f"전체 데이터 개수: {total_count}건")

        if total_count == 0:
            print("수집할 데이터가 없습니다.")
            return []

    except Exception as e:
        print(f"초기 요청 오류: {e}")
        return []

    start_index = 1

    while start_index <= total_count:
        end_index = min(start_index + batch_size - 1, total_count)

        url = f"{base_url}/{api_key}/{data_type}/{service}/{start_index}/{end_index}/{year}/{month}"

        try:
            print(f"{start_index}~{end_index}번 데이터 요청 중")
            response = requests.get(url, timeout=10)
            response.raise_for_status()

            data = response.json()

            result = data.get(service, {}).get('RESULT', {})
            result_code = result.get('CODE', '')

            if result_code != 'INFO-000':
                print(f"API 오류: {result.get('MESSAGE', '알 수 없는 오류')} (코드: {result_code})")
                break

            rows = data.get(service, {}).get('row', [])

            if not rows:
                print("응답 데이터가 없습니다.")
                break

            all_data.extend(rows)
            print(f" *** {len(rows)}건 수집 완료 (누적: {len(all_data)}/{total_count}건)")

            start_index = end_index + 1

            if end_index >= total_count:
                print("모든 데이터 수집 완료")
                break

            time.sleep(1) # 과호출 방지용 sleep

        except requests.exceptions.RequestException as e:
            print(f"네트워크 오류: {e}")
            break
        except ValueError as e:
            print(f"JSON 파싱 오류: {e}")
            break

    return all_data

def transform_api_data(raw_data):
    if not raw_data:
        print("변환할 데이터가 없음")
        return pd.DataFrame()

    df = pd.DataFrame(raw_data)

    columns_mapping = {
        'YEAR': '년도',
        'MON': '월',
        'MM_TYPE': '회원타입',
        'CNT': '건수',
        'EUS': '현년_전기사용량',
        'EUS1': '전년_전기사용량',
        'EUS2': '전전년_전기사용량',
        'ECO2_1': '전기_증감량',
        'ECO2_2': '전기_탄소증감량',
        'GUS': '현년_가스사용량',
        'GUS1': '전년_가스사용량',
        'GUS2': '전전년_가스사용량',
        'GCO2_1': '가스_증감량',
        'GCO2_2': '가스_탄소증감량',
        'WUS': '현년_수도사용량',
        'WUS1': '전년_수도사용량',
        'WUS2': '전전년_수도사용량',
        'WCO2_1': '수도_증감량',
        'WCO2_2': '수도_탄소증감량',
        'HUS': '현년_지역난방사용량',
        'HUS1': '전년_지역난방사용량',
        'HUS2': '전전년_지역난방사용량',
        'HCO2_1': '지역난방_증감량',
        'HCO2_2': '지역난방_탄소증감량',
        'REG_DATE': '등록일'
    }

    df = df[list(columns_mapping.keys())].rename(columns=columns_mapping)

    # 문자열로 오는거 전부 타입 변경
    exclude_from_numeric = ['년도', '월', '회원타입', '등록일']
    for col in df.columns:
        if col not in exclude_from_numeric:
            df[col] = pd.to_numeric(df[col], errors='coerce')

    print("=" * 60)
    print("1. 데이터 타입 정보")
    print("=" * 60)
    print(df.info())

    print("=" * 60)
    print("2. 컬럼 이름 목록")
    print("=" * 60)
    print(f"Columns: {df.columns.tolist()})")

    print("=" * 60)
    print("3. 실제 데이터 value (상위 5개 표현)")
    print("=" * 60)
    print(df.head())

    print("=" * 60)
    print("4. 기술 통계")
    print("=" * 60)
    print(df.describe())

    # 연도, 계절별로 grouping
    df['계절'] = df['월'].apply(get_season)

    # numeric field sum
    season_df = df.groupby(['년도', '계절']).sum(numeric_only=True).reset_index()

    print("=" * 60)
    print("5. 년도, 계절별로 grouping 한 데이터 (상위 5개 표현)")
    print("=" * 60)
    print(season_df.head())

    # 시각화를 위해 groupby 한 dataframe을 리턴함
    return season_df

def get_season(month):
    month = int(month)
    if month in [12, 1, 2]:
        return '겨울'
    elif month in [3, 4, 5]:
        return '봄'
    elif month in [6, 7, 8]:
        return '여름'
    else:
        return '가을'

def visualize_data(df):
    df['총_에너지_사용량'] = (df['현년_전기사용량'] + df['현년_가스사용량'] + df['현년_수도사용량'] + df['현년_지역난방사용량'])

    # 연도별 계산
    year_total = df.groupby('년도')['총_에너지_사용량'].sum().reset_index()

    plt.figure(figsize=(12, 6))
    plt.plot(year_total['년도'], year_total['총_에너지_사용량'], marker='o', linewidth=2, markersize=8)

    plt.title('연도별 에너지 사용 총액 변화 - 4324', fontsize=16, fontweight='bold')
    plt.xlabel('년도', fontsize=12)
    plt.ylabel('총 에너지 사용량', fontsize=12)
    plt.grid(True, alpha=0.3)

    for x, y in zip(year_total['년도'], year_total['총_에너지_사용량']):
        plt.text(x, y, f'{y:,.0f}', ha='center', va='bottom', fontsize=9)
    plt.tight_layout()
    plt.show()

    # 계절별 count 합쳐서 평균(mean)
    season_gas = df.groupby('계절')['현년_가스사용량'].mean().reset_index()

    # 계절별로 정렬해서 표현하기
    season_order = ['봄', '여름', '가을', '겨울']
    season_gas['계절'] = pd.Categorical(season_gas['계절'], categories=season_order, ordered=True)
    season_gas = season_gas.sort_values('계절')

    plt.figure(figsize=(10, 6))
    bars = plt.bar(season_gas['계절'], season_gas['현년_가스사용량'],color='skyblue', edgecolor='black')

    plt.title('계절별 가스 사용량 평균 - 4324', fontsize=16, fontweight='bold')
    plt.xlabel('계절', fontsize=12)
    plt.ylabel('가스 사용량 평균', fontsize=12)

    for bar in bars:
        height = bar.get_height()
        plt.text(bar.get_x() + bar.get_width()/2., height,f'{height:,.0f}', ha='center', va='bottom', fontsize=11, fontweight='bold')

    plt.tight_layout()
    plt.show()


def main():
    raw_data = []

    # 2015년 1월부터 2024년 12월까지 데이터를 요청
    for year in range(2015, 2025):  # 2015 ~ 2024
        for month in range(1, 13):
            # YYYY, MM
            raw_data.extend(extract_api_data(str(year), str(month).zfill(2)))

    dataframe = transform_api_data(raw_data)

    # 시각화
    visualize_data(dataframe)

if __name__ == "__main__":
    main()