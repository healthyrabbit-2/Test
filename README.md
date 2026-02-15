# Telegram Unread Digest

텔레그램에서 **구독 중인 채널의 안 읽은 메시지**를 모아 요약하고,
- 로컬에서 열 수 있는 HTML 리포트 생성
- JSON 아카이브 생성(요약/원문 링크 포함)
- 텔레그램 메시지 형태로 나에게 재포스팅
을 한 번에 수행하는 스크립트입니다.

## 1) 설치

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 2) 환경 변수

```bash
export TG_API_ID="123456"
export TG_API_HASH="xxxxxxxxxxxxxxxxxxxxxxxx"
export TG_PHONE="+821012345678"   # 최초 로그인시에만 필요

# 텔레그램 재포스팅(옵션)
export TG_BOT_TOKEN="123456:ABCDEF..."
export TG_TARGET_CHAT_ID="123456789"

# 고급 옵션(선택)
export OPENAI_API_KEY="sk-..."      # 설정 시 LLM 요약 사용
export OPENAI_MODEL="gpt-4o-mini"
export OPENAI_BASE_URL="https://api.openai.com/v1"
```

> `TG_API_ID` / `TG_API_HASH`는 https://my.telegram.org 에서 발급합니다.

## 3) 실행

기본 실행(HTML + JSON 생성):

```bash
python telegram_digest.py --output-dir output --limit 50
```

텔레그램으로 재포스팅까지:

```bash
python telegram_digest.py --output-dir output --limit 50 --post
```

## 4) 산출물

`output/` 아래에 다음 파일이 생성됩니다.

- `digest_YYYYMMDD_HHMMSS.html`: 로컬 브라우저 리포트
- `digest_YYYYMMDD_HHMMSS.json`: 채널/요약/원문 링크를 포함한 구조화 데이터

JSON에는 각 메시지의 `message_link`가 보존되어, 이후 별도 DB/노트앱으로 관리하기 쉽습니다.

## 5) 동작 방식

1. Telethon으로 채널 다이얼로그 순회
2. `unread_count > 0` 인 채널에서 안 읽은 메시지 수집
3. 각 메시지를 요약(LLM 키가 있으면 원격 요약, 없으면 로컬 휴리스틱 요약)
4. HTML/JSON 저장
5. `--post` 시 Bot API `sendMessage`로 요약 전송

## 6) 주의사항

- 비공개 채널 링크는 `https://t.me/c/...` 형식으로 생성됩니다.
- 첫 실행 시 인증 코드 입력이 필요할 수 있습니다.
- 아주 긴 요약은 텔레그램 메시지 길이 제한에 걸릴 수 있으니 `--limit`로 조절하세요.
