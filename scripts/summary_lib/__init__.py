"""Grok transcript summary pipeline modules.

telegram_summary.ipynb의 각 단계를 모듈로 분리한 패키지.

- config: .env 로딩, 경로, Grok/Telegram 설정
- transcript_io: transcript 파일 선택(latest.json 또는 폴더)과 텍스트 추출
- metadata: 티커/분기/세션/컨센서스 블록 추출
- prompts: 요약 프롬프트와 튜닝 파라미터
- grok_client: Grok API 호출(재시도 포함)
- summarizer: 청크 분할 -> 청크 요약 -> 최종 요약
- outputs: 배치 JSON/CSV 저장
- telegram_client: Telegram 메시지 빌드/분할/전송
"""
