# Asterisk Integration

## 프로젝트 개요

STT(음성 인식), TTS(음성 합성), 음성봇을 Asterisk와 연동하여 활용하는 예제들을 모아놓은 프로젝트입니다.
각 연동 케이스는 별도 브랜치로 관리하며, 해당 브랜치에서 구현 코드와 실행 방법을 확인할 수 있습니다.

## STT 연동

[STT-Integration](https://github.com/NotableDeveloper/Asterisk-Integration/tree/STT-Integration) 브랜치는 고객 전화 음성을 텍스트로 변환하여 웹 페이지에 표시하는 예제입니다.<br>
Asterisk의 ARI와 ExternalMedia로 통화 음성을 RTP로 전달받아 STT 모델로 인식합니다.<br>
최종 인식 결과를 WebSocket으로 웹 대화록에 표시하고, 중간·최종 인식 결과는 서버 로그에 기록합니다.
