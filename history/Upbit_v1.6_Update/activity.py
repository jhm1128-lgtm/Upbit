"""UI activity signal, distinct from investment or order-entry signals."""
def activity_state(running,worker_alive,scan_text,record_error):
    if record_error: return 'red','기록 오류 · 중지'
    if not running:
        return ('yellow','중지 처리 중') if worker_alive else ('red','중지됨')
    if '오류' in scan_text: return 'yellow','조회 오류 · 재시도 대기'
    if ('스캔' in scan_text and '완료' not in scan_text) or '조회 중' in scan_text:
        return 'yellow','조회 · 검색 중'
    return 'green','실행 중 · 다음 검색 대기'
