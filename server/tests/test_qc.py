# tests/test_qc.py —— T9 录音质检：相似度纯逻辑 3 例 + monkeypatch 全链路 5 例
# 关键：qc.process_pending 用模块级 SessionLocal 开会话，与 conftest db fixture 不同源，
# 须 monkeypatch 指向"绑定当前 db fixture 引擎"的 sessionmaker（db.get_bind() 现场构造；
# 不可 from tests.conftest import TestingSession——python -m pytest 下 conftest 会被
# conftest / tests.conftest 双实例化，后者另建内存引擎导致 no such table）；启用质检须同时
# monkeypatch settings.asr_api_url 非空（settings 导入时已实例化，改 os.environ 无效）
import os

from sqlalchemy.orm import sessionmaker

from app.models import Message, MessageRecipient, QCLog, Recording, Text
from tests.conftest import make_user


def make_pending(db, tmp_path, content="下雨了，衣裳好收收了"):
    u = make_user(db)
    t = Text(content=content, dialect="台州话", category="日常用语",
              region_code="331004", dialect_code="dh331004")
    db.add(t)
    db.flush()
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"x")
    rec = Recording(user_id=u.id, text_id=t.id, file_path=str(wav), file_size=1,
                    duration=1.0, region_code="331004", dialect_code="dh331004",
                    qc_status="pending")
    db.add(rec)
    db.commit()
    return u, t, rec, wav


def patch_engine(monkeypatch, db):
    monkeypatch.setattr("app.services.qc.SessionLocal",
                        sessionmaker(bind=db.get_bind(), expire_on_commit=False))


def enable_qc(monkeypatch, db, asr):
    monkeypatch.setattr("app.core.config.settings.asr_api_url", "http://fake-asr")
    patch_engine(monkeypatch, db)
    monkeypatch.setattr("app.services.qc.call_asr", asr)


def test_similarity_identical_and_empty():
    from app.services.qc import similarity
    assert similarity("你们不要吵了", "你们不要吵了") == 1.0
    assert similarity("", "") == 1.0 and similarity("abc", "") == 0.0


def test_similarity_ignores_punctuation_and_case():
    from app.services.qc import similarity
    assert similarity("「下雨了。」", "下雨了") == 1.0
    assert similarity("Hello", "hello") == 1.0


def test_similarity_threshold_boundary():
    from app.services.qc import similarity
    # 4字对3字：距离1/长度4=0.25 → 0.75 ≥0.5 通过；8字对2字距离6/8 → 0.25 <0.5 不通过
    assert similarity("一二三四", "一二三") == 0.75
    assert similarity("一二三四五六七八", "一二") == 0.25


def test_qc_pass(db, tmp_path, monkeypatch):
    enable_qc(monkeypatch, db, lambda p: "下雨了，衣裳好收收了")
    u, t, rec, wav = make_pending(db, tmp_path)
    from app.services.qc import process_pending
    process_pending()
    db.expire_all()
    assert db.get(Recording, rec.id).qc_status == "passed"
    log = db.query(QCLog).filter_by(recording_id=rec.id).one()
    assert log.result == "passed" and log.similarity == 1.0
    assert os.path.exists(str(wav)) is True


def test_qc_fail_deletes_and_notifies(db, tmp_path, monkeypatch):
    enable_qc(monkeypatch, db, lambda p: "完全无关内容")
    u, t, rec, wav = make_pending(db, tmp_path, content="上盘镇")
    from app.services.qc import process_pending
    process_pending()
    db.expire_all()
    assert db.query(Recording).count() == 0                       # 录音已删（unique 解除可重录）
    assert os.path.exists(str(wav)) is False                       # 音频文件已删
    msg = db.query(Message).one()
    assert msg.title == "录音质检未通过"
    assert "上盘镇" in msg.content and "相似度" in msg.content
    assert db.query(MessageRecipient).filter_by(user_id=u.id).count() == 1
    assert db.query(QCLog).one().result == "failed"


def test_qc_error_keeps_pending(db, tmp_path, monkeypatch):
    def boom(p):
        raise RuntimeError("asr down")
    enable_qc(monkeypatch, db, boom)
    u, t, rec, wav = make_pending(db, tmp_path)
    from app.services.qc import process_pending
    process_pending()
    db.expire_all()
    assert db.get(Recording, rec.id).qc_status == "pending"        # 异常绝不误删
    log = db.query(QCLog).one()
    assert log.result == "error" and "asr down" in log.error_message
    assert os.path.exists(str(wav)) is True


def test_qc_retry_cap_skips(db, tmp_path, monkeypatch):
    enable_qc(monkeypatch, db, lambda p: "无关")
    u, t, rec, wav = make_pending(db, tmp_path, content="上盘镇")
    for _ in range(3):                                             # 预插 3 条 error（QC_MAX_RETRY=3）
        db.add(QCLog(recording_id=rec.id, user_id=u.id, text_id=rec.text_id,
                     text_content="上盘镇", asr_text="", similarity=None, result="error"))
    db.commit()
    from app.services.qc import process_pending
    process_pending()                                              # 不再处理，留待人工
    db.expire_all()
    assert db.query(Recording).count() == 1
    assert db.query(QCLog).filter_by(result="failed").count() == 0
    assert os.path.exists(str(wav)) is True


def test_qc_disabled_direct_pass(db, tmp_path, monkeypatch):
    monkeypatch.setattr("app.core.config.settings.asr_api_url", "")  # 质检停用
    patch_engine(monkeypatch, db)
    u, t, rec, wav = make_pending(db, tmp_path)
    from app.services.qc import process_pending
    process_pending()
    db.expire_all()
    assert db.get(Recording, rec.id).qc_status == "passed"         # 直通
    assert db.query(QCLog).count() == 0                            # 不写质检日志
