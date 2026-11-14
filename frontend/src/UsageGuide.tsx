type GuideImage = {
  src: string;
  alt: string;
  caption: string;
};

type GuideSection = {
  id: string;
  number: string;
  shortTitle: string;
  title: string;
  summary: string;
  instructions: string[];
  examples: string[];
  note: string;
  images: GuideImage[];
};

const GUIDE_IMAGES = {
  "guide-01-workspace.svg": new URL("./assets/guide-01-workspace.svg", import.meta.url).href,
  "guide-02-query-result.svg": new URL("./assets/guide-02-query-result.svg", import.meta.url).href,
  "guide-03-sql-evidence.svg": new URL("./assets/guide-03-sql-evidence.svg", import.meta.url).href,
  "guide-04-spatial-analysis.svg": new URL("./assets/guide-04-spatial-analysis.svg", import.meta.url).href,
  "guide-05-feature-analysis.svg": new URL("./assets/guide-05-feature-analysis.svg", import.meta.url).href,
  "guide-06-mcp-analysis.svg": new URL("./assets/guide-06-mcp-analysis.svg", import.meta.url).href,
  "guide-07-report-result.svg": new URL("./assets/guide-07-report-result.svg", import.meta.url).href,
  "guide-07-sentence-evidence.svg": new URL("./assets/guide-07-sentence-evidence.svg", import.meta.url).href,
  "guide-08-history.svg": new URL("./assets/guide-08-history.svg", import.meta.url).href,
} as const;

const image = (name: keyof typeof GUIDE_IMAGES) => GUIDE_IMAGES[name];

const SECTIONS: GuideSection[] = [
  {
    id: "guide-scope",
    number: "01",
    shortTitle: "지역과 범위",
    title: "1. 지역과 분석 범위 설정",
    summary: "질문하기 전에 전국·시도·시군구 중 분석 범위를 먼저 고정합니다.",
    instructions: [
      "상단 지역 선택에서 시·도를 고르고, 필요한 경우 오른쪽 칸에서 시·군·구를 선택합니다.",
      "시도 전체를 보려면 시·군·구를 ‘전체’로 둡니다. 전국 비교는 첫 번째 칸에서 ‘전국’을 선택합니다.",
      "상단 지역을 바꾸면 열려 있는 공간분석 지도도 같은 지역으로 즉시 갱신됩니다.",
      "이전 작업과 분리하려면 왼쪽 ‘새 대화’를 누른 뒤 지역을 다시 설정합니다.",
    ],
    examples: ["부산광역시 해운대구로 변경해줘", "강원특별자치도 전체를 비교해줘"],
    note: "지역명을 질문에 반복하지 않아도 상단에 선택된 지역이 기본 조회 범위로 사용됩니다.",
    images: [{
      src: image("guide-01-workspace.svg"),
      alt: "Schematic: Scope selection before asking a question. Illustrative workflow, no production data.",
      caption: "상단 지역 선택과 왼쪽 새 대화로 작업 범위를 먼저 정합니다.",
    }],
  },
  {
    id: "guide-query",
    number: "02",
    shortTitle: "데이터 질의",
    title: "2. 자연어로 데이터 질의",
    summary: "지표, 비교 기준, 단위와 원하는 출력 형태를 한 문장에 구체적으로 적습니다.",
    instructions: [
      "질문창에 지표명과 비교 대상을 함께 입력합니다. 예: ‘고위험 비율이 가장 높은 읍면동 5곳’.",
      "표준화 지수 대신 실제 값을 보려면 ‘원자료 기준으로, 단위와 기준값을 함께’라고 요청합니다.",
      "비교 질문은 분모를 명확히 합니다. 예: ‘해운대구 전체 대비’ 또는 ‘해당 읍면동 자체 대비’.",
      "후속 질문은 앞선 지역·등급·비교 조건을 이어받으므로 ‘그중 고령인구가 가장 많은 곳은?’처럼 물을 수 있습니다.",
    ],
    examples: [
      "고위험 비율이 가장 높은 읍면동 5곳을 실제 격자 수와 함께 보여줘",
      "노출성과 취약성 상위 요인을 원자료 단위와 기준값으로 비교해줘",
    ],
    note: "‘위험한 곳’처럼 모호한 표현보다 ‘종합 위험 4·5등급 비율’처럼 지표와 등급을 밝히면 결과가 정확해집니다.",
    images: [{
      src: image("guide-02-query-result.svg"),
      alt: "Schematic: A question flows to a result for review. Illustrative workflow, no production data.",
      caption: "답변, 인라인 차트, 원본 조회 표가 한 대화 안에 표시됩니다.",
    }],
  },
  {
    id: "guide-evidence",
    number: "03",
    shortTitle: "SQL과 검증",
    title: "3. 조회 결과·SQL·검증 상태 확인",
    summary: "답변을 인용하기 전에 조회 범위, 실행 SQL, 원본 표와 수치 대조 상태를 확인합니다.",
    instructions: [
      "‘조회 결과와 수치 대조 완료’ 표시가 있는지 확인합니다.",
      "‘원본 조회 결과’에서 사용된 행과 열, 건수, 비율이 설명과 일치하는지 확인합니다.",
      "‘실행 SQL 보기’를 펼쳐 WHERE 조건의 지역·등급·선택 범위가 질문과 같은지 확인합니다.",
      "재계산은 ‘다시 실행’, 공유는 ‘복사’, 보고서에 쓸 결과만 ‘보고서에 추가’를 사용합니다.",
    ],
    examples: ["이 결과에 사용된 SQL과 전체 조회 건수를 보여줘"],
    note: "수치 검증 실패가 표시되면 해당 서술을 최종 근거로 사용하지 말고 조건을 구체화해 다시 질문합니다.",
    images: [{
      src: image("guide-03-sql-evidence.svg"),
      alt: "Schematic: Review query conditions and compare source evidence. Illustrative workflow, no production data.",
      caption: "SQL을 펼쳐 실제 조회에 적용된 지역·등급·범위 조건을 확인합니다.",
    }],
  },
  {
    id: "guide-spatial",
    number: "04",
    shortTitle: "공간분석 지도",
    title: "4. 공간분석 지도 사용",
    summary: "채팅 결과를 GPKG 격자와 연결해 위치, 등급, 평가항목별 분포를 지도에서 확인합니다.",
    instructions: [
      "상단 ‘공간분석’ 또는 답변의 ‘지도에서 보기’를 누릅니다.",
      "‘평가항목’에서 종합 위험 또는 강풍·파랑·인구·고령인구 등 세부 항목을 고릅니다.",
      "1~5등급 필터로 표시 격자를 바꾸고 배경지도를 일반지도·위성영상 중 선택합니다.",
      "대화/지도 분리선과 지도/속성 테이블 분리선을 드래그해 모니터에 맞게 크기를 조절합니다.",
    ],
    examples: [
      "해운대구 종합 위험 4·5등급 격자만 지도에 보여줘",
      "고령인구 항목의 5등급 분포를 위성영상으로 보여줘",
    ],
    note: "상단 지역, 평가항목, 등급 필터는 현재 분석 문맥으로 유지되며 후속 질문과 지도 내 분석에 사용됩니다.",
    images: [{
      src: image("guide-04-spatial-analysis.svg"),
      alt: "Schematic: Scope and layer filters guide spatial exploration. Illustrative workflow, no production data.",
      caption: "대화와 지도를 함께 보며 평가항목·등급·배경지도를 변경합니다.",
    }],
  },
  {
    id: "guide-selection",
    number: "05",
    shortTitle: "격자와 공간연산",
    title: "5. 격자·선택 영역·공간 연산",
    summary: "특정 격자나 사용자가 그린 영역을 기준으로 인접·버퍼·중첩·핫스팟 분석을 수행합니다.",
    instructions: [
      "지도 격자를 클릭해 선택 피처의 원본 등급과 ‘왜 위험한지 분석’을 확인합니다.",
      "‘인접 격자’로 주변 격자를, ‘500m 주변’으로 거리 영향권을 분석합니다.",
      "‘영역 그리기’로 3개 이상의 꼭지점을 지정한 뒤 ‘통계·중첩 분석’을 실행합니다.",
      "결과를 임시 레이어로 보관하거나 채팅으로 보내 후속 질문을 이어가고, 반복 작업은 ‘저장 시나리오’로 저장합니다.",
    ],
    examples: [
      "이 격자 주변 500m 내 고령인구와 대피소를 분석해줘",
      "선택한 영역의 평균과 지역 전체 평균을 비교해줘",
    ],
    note: "선택 영역 ID는 데이터 값이 아니라 조회 범위를 구분하는 내부 표식자이며, SQL에는 선택된 실제 격자 목록이 적용됩니다.",
    images: [{
      src: image("guide-05-feature-analysis.svg"),
      alt: "Schematic: A selected area defines the scope of an operation. Illustrative workflow, no production data.",
      caption: "격자를 클릭하면 원본 등급과 인접·버퍼·후속 질의 기능이 표시됩니다.",
    }],
  },
  {
    id: "guide-mcp",
    number: "06",
    shortTitle: "MCP 시각화",
    title: "6. MCP 고급 시각화",
    summary: "조회된 전체 데이터를 기준으로 차트 후보를 비교하고 분석 결과를 보고서 자료로 사용합니다.",
    instructions: [
      "데이터 조회 결과 아래의 ‘MCP 고급 분석’을 누릅니다.",
      "누적 막대, 소형 다중 차트, 상관관계 히트맵, 산점도 등 생성된 후보 탭을 비교합니다.",
      "‘직접 설정’에서 차트 유형과 X축·Y축·그룹·집계 방식을 지정할 수 있습니다.",
      "제목, 축 단위, 분석 서술이 실제 조회 항목과 맞는지 확인한 뒤 보고서에 추가합니다.",
    ],
    examples: [
      "읍면동별 종합 위험 등급 구성을 누적 막대 차트로 보여줘",
      "고령인구와 종합 위험도의 관계를 산점도로 분석해줘",
    ],
    note: "차트를 보고서에 담기 전에 검증 상태와 분석 서술을 확인합니다. 수치 근거가 없는 결과는 보고서 자료로 사용하지 않습니다.",
    images: [{
      src: image("guide-06-mcp-analysis.svg"),
      alt: "Schematic: Compare visualization options and verify their labels. Illustrative workflow, no production data.",
      caption: "여러 차트 후보를 탭으로 비교하고 적합한 결과를 선택합니다.",
    }],
  },
  {
    id: "guide-report",
    number: "07",
    shortTitle: "보고서 작성",
    title: "7. 보고서 자료 수집과 작성",
    summary: "질의 결과, 지도, MCP 차트를 필요한 순서로 모은 뒤 검증된 보고서를 생성합니다.",
    instructions: [
      "사용할 질의 결과·지도·MCP 차트에서 ‘보고서에 추가’를 눌러 자료 바구니에 담습니다.",
      "입력창에 띄어쓰기 없는 명령어 ‘/보고서작성’을 입력해 전송합니다.",
      "작성 설정에서 자료 순서와 LLM 서술, 수치 검증, HWPX 생성 여부를 확인합니다.",
      "데이터·분석·시각화·서술·검증·조립·변환 진행 표시가 완료될 때까지 기다립니다.",
      "동시 사용자가 많으면 작업이 대기열에 들어갑니다. 브라우저를 닫지 않고 현재 상태를 확인합니다.",
    ],
    examples: ["/보고서작성", "모은 자료를 기준으로 정책 제언을 강화한 보고서를 작성해줘"],
    note: "보고서 자료는 최대 10건입니다. 서로 다른 지역 자료가 섞이지 않았는지 작성 전에 지역과 목록을 다시 확인합니다.",
    images: [{
      src: image("guide-07-report-result.svg"),
      alt: "Schematic: Collected evidence supports a draft that requires review. Illustrative workflow, no production data.",
      caption: "완료 후 지도·그래프·검증 상태와 Markdown·HWPX 결과를 확인합니다.",
    }],
  },
  {
    id: "guide-review",
    number: "08",
    shortTitle: "검토와 이력",
    title: "8. 검토·근거·다운로드·이력",
    summary: "완성된 문서를 편집하고 문장별 데이터 근거를 확인한 뒤 현재 PC로 다운로드합니다.",
    instructions: [
      "‘보고서 본문 미리보기’를 펼치고 밑줄 친 문장을 눌러 ‘문장 근거’를 엽니다.",
      "일치 통계값, 실행 SQL, GPKG 원본 필드, 데이터 조회 범위를 확인합니다.",
      "‘지도에서 보기’를 누르면 해당 문장의 지역·등급·평가항목이 공간분석에 적용됩니다.",
      "‘직접 편집’은 원본을 보존한 새 버전을 만듭니다. 대화로 ‘정책 제언을 더 짧게’처럼 수정할 수도 있습니다.",
      "Markdown·HWPX·PNG는 현재 PC의 브라우저 다운로드 폴더에 저장됩니다.",
      "‘분석 작업 이력’에서 세션을 이어서 열거나 필요 없는 세션을 삭제합니다.",
    ],
    examples: [
      "보고서의 정책 제언을 세 문단으로 줄여줘",
      "이 문장의 수치에 사용된 지역과 SQL 범위를 보여줘",
    ],
    note: "‘지도에서 보기’를 누른 뒤에도 보고서 스크롤 위치는 유지됩니다. 근거 패널은 아래쪽 분리선으로 높이를 조절할 수 있습니다.",
    images: [
      {
        src: image("guide-07-sentence-evidence.svg"),
        alt: "Schematic: Trace a statement to evidence and check its scope. Illustrative workflow, no production data.",
        caption: "밑줄 친 문장과 일치하는 통계값·SQL·지도 범위를 함께 확인합니다.",
      },
      {
        src: image("guide-08-history.svg"),
        alt: "Schematic: A saved session can be selected to resume work. Illustrative workflow, no production data.",
        caption: "계정별로 저장된 질의·분석·보고서 세션을 복원해 계속 질문합니다.",
      },
    ],
  },
];

export default function UsageGuideContent({ onClose }: { onClose: () => void }) {
  return <>
    <header className="usage-guide-header">
      <div>
        <small>FIELD MANUAL</small>
        <h2>질문에서 보고서까지, 8단계 실무 가이드</h2>
        <p>데이터 조회·공간분석·보고서 작성의 개념적 흐름을 설명합니다. 실제 운영 화면이나 데이터가 아닙니다.</p>
        <p lang="en">Self-authored schematics, not production screenshots. A configured external engine and data are required; this public source is not a standalone end-to-end demo.</p>
      </div>
      <button type="button" onClick={onClose}>닫기</button>
    </header>
    <div className="usage-guide-layout">
      <nav className="usage-guide-nav" aria-label="사용 방법 목차">
        <div><strong>업무 흐름</strong><span>8 STEPS</span></div>
        {SECTIONS.map((section) => <a key={section.id} href={`#${section.id}`}>
          <b>{section.number}</b><span>{section.shortTitle}</span>
        </a>)}
        <aside><strong>핵심 원칙</strong><p>지역·지표·비교 기준을 먼저 정하고, 수치는 SQL과 문장 근거로 다시 확인합니다.</p></aside>
      </nav>
      <div className="usage-guide-content">
        <section className="usage-guide-overview" aria-label="사용 전 확인사항">
          <div><span>DUCKDB</span><strong>정형 수치 조회</strong><p>통계·원자료·등급 계산</p></div>
          <div><span>GPKG</span><strong>공간 범위 확인</strong><p>격자·선택영역·중첩 분석</p></div>
          <div><span>REPORT</span><strong>근거 연결 보고서</strong><p>검증·편집·HWPX 다운로드</p></div>
        </section>
        {SECTIONS.map((section) => <article className="usage-guide-section" id={section.id} key={section.id}>
          <header><span>{section.number}</span><div><small>WORKFLOW</small><h3>{section.title}</h3><p>{section.summary}</p></div></header>
          <div className={`usage-guide-media ${section.images.length > 1 ? "gallery" : ""}`}>
            {section.images.map((asset) => <figure key={asset.src}>
              <img src={asset.src} alt={asset.alt} loading="lazy" />
              <figcaption><strong lang="en">Illustrative workflow, no production data</strong><br />{asset.caption}</figcaption>
            </figure>)}
          </div>
          <div className="usage-guide-instructions">
            <h4>실행 순서</h4>
            <ol>{section.instructions.map((instruction) => <li key={instruction}>{instruction}</li>)}</ol>
          </div>
          <div className="usage-guide-examples">
            <strong>질문 예시</strong>
            {section.examples.map((example) => <code key={example}>{example}</code>)}
          </div>
          <aside><strong>확인할 점</strong><p>{section.note}</p></aside>
        </article>)}
        <footer className="usage-guide-finish">
          <span>READY</span>
          <div><strong>지역을 선택한 뒤 첫 질문을 시작하세요.</strong><p>결과의 수치 근거를 확인하고 필요한 자료만 모아 <code>/보고서작성</code>으로 완성합니다.</p></div>
        </footer>
      </div>
    </div>
  </>;
}
